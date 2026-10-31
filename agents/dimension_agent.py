# -*- coding: utf-8 -*-
"""
agents/dimension_agent.py — 维度生成Agent

职责：推断产品品类，为产品分析和定价分析生成动态子维度
LLM调用：1次
外部工具：无
提示词来源：prompts/dimension_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import (
    CompetitorList, CompetitorData,
    DimensionConfig, ProductCategory, SubDimension,
)
from core.prompt_loader import load as load_prompts
from itertools import zip_longest
import config


class DimensionAgent(BaseAgent):
    """维度生成Agent — 品类推断 + 子维度生成"""

    def __init__(self):
        prompts = load_prompts("dimension_agent")
        super().__init__(
            agent_id="DimensionAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_generate = prompts["prompt_generate"]

    async def run(self, product_description: str,
                  competitor_list: CompetitorList,
                  competitors_data: dict[str, CompetitorData] | None = None,
                  target_product_data: CompetitorData | None = None) -> DimensionConfig:
        """
        推断品类并生成产品/定价分析的子维度

        Args:
            product_description: 用户产品描述
            competitor_list: 竞品发现结果
            competitors_data: 本轮已采集的竞品事实，供失败回退定义比较范围
            target_product_data: 本轮已采集的目标产品事实

        Returns:
            DimensionConfig: 动态维度配置
        """
        self._log("📐 开始维度生成...")

        competitors_text = self._build_competitors_text(competitor_list)

        if config.ENABLE_LLM:
            prompt = self._prompt_generate.format(
                product_description=product_description,
                competitors_text=competitors_text,
            )
            result = await self.async_ask_llm_json(prompt, max_tokens=2048)
            if result:
                try:
                    dim_config = self._parse_config(result)
                except (TypeError, ValueError):
                    self._log("⚠️ LLM维度配置无效，依据本轮采集数据保留比较范围")
                else:
                    self._log(
                        f"✅ 维度生成完成: 品类={dim_config.product_category.level1}/{dim_config.product_category.level2}, "
                        f"产品子维度={len(dim_config.product_sub_dimensions)}个, "
                        f"定价子维度={len(dim_config.pricing_sub_dimensions)}个"
                    )
                    return dim_config
            else:
                self._log("⚠️ LLM维度生成失败，依据本轮采集数据保留比较范围")

        return self._rule_generate(competitor_list, competitors_data, target_product_data)

    def _build_competitors_text(self, competitor_list: CompetitorList) -> str:
        """构建竞品列表文本"""
        lines = []
        for c in competitor_list.competitors:
            lines.append(f"- {c.name}: {c.brief}")
        return "\n".join(lines)

    def _parse_config(self, result: dict) -> DimensionConfig:
        """Validate a complete proposal before exposing it as model-generated."""
        if not isinstance(result, dict):
            raise ValueError("Dimension proposal must be an object")
        cat = result.get("product_category")
        if not isinstance(cat, dict) or any(
            not isinstance(cat.get(key), str) or not cat[key].strip()
            for key in ("level1", "level2")
        ):
            raise ValueError("Dimension category is missing")

        def parse_dimensions(key):
            proposed = result.get(key)
            if not isinstance(proposed, list) or not 4 <= len(proposed) <= 6:
                raise ValueError("Expected four to six category-specific dimensions")
            parsed, seen = [], set()
            for item in proposed:
                if not isinstance(item, dict) or any(
                    not isinstance(item.get(field), str) or not item[field].strip()
                    for field in ("name", "description")
                ):
                    raise ValueError("Dimension name and description must be nonempty strings")
                name = item["name"].strip()
                if name.casefold() in seen:
                    raise ValueError("Duplicate dimension name")
                seen.add(name.casefold())
                parsed.append(SubDimension(name=name, description=item["description"].strip()))
            return parsed

        product_dims = parse_dimensions("product_sub_dimensions")
        pricing_dims = parse_dimensions("pricing_sub_dimensions")
        reasoning = result.get("reasoning", "")
        if not isinstance(reasoning, str):
            raise ValueError("Dimension reasoning must be text")
        return DimensionConfig(
            product_category=ProductCategory(
                level1=cat["level1"].strip(),
                level2=cat["level2"].strip(),
            ),
            product_sub_dimensions=product_dims,
            pricing_sub_dimensions=pricing_dims,
            reasoning=reasoning.strip(),
        )

    def _rule_generate(self, competitor_list: CompetitorList,
                       competitors_data: dict[str, CompetitorData] | None = None,
                       target_product_data: CompetitorData | None = None) -> DimensionConfig:
        """Use this run's collected labels as scope, without inferring support."""
        names = {}
        entities = ([target_product_data] if target_product_data else []) + list((competitors_data or {}).values())
        # Round-robin scope keeps a long target feature list from hiding rivals.
        for group in zip_longest(*(entity.product_features for entity in entities)):
            for feature in group:
                if feature is not None and isinstance(feature.name, str) and feature.name.strip():
                    name = feature.name.strip()
                    names.setdefault(name.casefold(), name)
                if len(names) >= 6:
                    break
            if len(names) >= 6:
                break
        selected = list(names.values())
        category = competitor_list.product_category
        category = category.strip() if isinstance(category, str) else ""
        self._log(f"   规则降级：由当前采集功能名称保留{len(selected)}个比较维度")
        explanation = (
            "规则降级：品类沿用本轮发现结果；比较范围取自本轮目标产品与竞品的采集功能名称。"
            "这些名称不表示相关能力已经核实，支持情况仍需逐项证据；定价维度待补充。"
            if selected else
            "规则降级：品类沿用本轮发现结果；缺少可用采集功能名称，产品与定价维度待补充。"
        )
        return DimensionConfig(
            product_category=ProductCategory(level2=category),
            product_sub_dimensions=[
                SubDimension(name=name, description="采集资料中的功能名称，仅定义比较范围；支持情况需逐项证据。")
                for name in selected
            ],
            pricing_sub_dimensions=[],
            reasoning=explanation,
        )
