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
    CompetitorList, CompetitorInfo,
    DimensionConfig, ProductCategory, SubDimension,
)
from core.prompt_loader import load as load_prompts
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
                  competitor_list: CompetitorList) -> DimensionConfig:
        """
        推断品类并生成产品/定价分析的子维度

        Args:
            product_description: 用户产品描述
            competitor_list: 竞品发现结果

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
                dim_config = self._parse_config(result)
                self._log(
                    f"✅ 维度生成完成: 品类={dim_config.product_category.level1}/{dim_config.product_category.level2}, "
                    f"产品子维度={len(dim_config.product_sub_dimensions)}个, "
                    f"定价子维度={len(dim_config.pricing_sub_dimensions)}个"
                )
                return dim_config
            else:
                self._log("⚠️ LLM维度生成失败，降级到默认维度")

        return self._rule_generate(competitor_list)

    def _build_competitors_text(self, competitor_list: CompetitorList) -> str:
        """构建竞品列表文本"""
        lines = []
        for c in competitor_list.competitors:
            lines.append(f"- {c.name}: {c.brief}")
        return "\n".join(lines)

    def _parse_config(self, result: dict) -> DimensionConfig:
        """解析LLM返回的维度配置"""
        cat = result.get("product_category", {})
        product_dims = [
            SubDimension(name=d.get("name", ""), description=d.get("description", ""))
            for d in result.get("product_sub_dimensions", [])
        ]
        pricing_dims = [
            SubDimension(name=d.get("name", ""), description=d.get("description", ""))
            for d in result.get("pricing_sub_dimensions", [])
        ]
        return DimensionConfig(
            product_category=ProductCategory(
                level1=cat.get("level1", ""),
                level2=cat.get("level2", ""),
            ),
            product_sub_dimensions=product_dims,
            pricing_sub_dimensions=pricing_dims,
            reasoning=result.get("reasoning", ""),
        )

    def _rule_generate(self, competitor_list: CompetitorList) -> DimensionConfig:
        """规则引擎降级：返回通用维度"""
        self._log("   使用通用默认维度")
        return DimensionConfig(
            product_category=ProductCategory(level1="通用", level2="通用产品"),
            product_sub_dimensions=[
                SubDimension(name="核心功能", description="主要功能的完整度和质量"),
                SubDimension(name="用户体验", description="交互设计、易用性、流畅度"),
                SubDimension(name="技术创新", description="技术方案的先进性和差异化"),
                SubDimension(name="产品成熟度", description="功能稳定性和完善程度"),
            ],
            pricing_sub_dimensions=[
                SubDimension(name="定价模式", description="免费增值/订阅/一次性买断等"),
                SubDimension(name="价格梯度", description="不同版本/套餐的价格差异"),
                SubDimension(name="性价比", description="功能覆盖与价格的综合评估"),
                SubDimension(name="促销策略", description="优惠活动、折扣、试用期"),
            ],
            reasoning="规则引擎降级，使用通用维度",
        )
