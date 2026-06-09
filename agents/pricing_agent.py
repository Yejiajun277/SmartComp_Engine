# -*- coding: utf-8 -*-
"""
agents/pricing_agent.py — 定价分析Agent

职责：对比各竞品定价策略、促销模式、性价比
LLM调用：1次
外部工具：无
提示词来源：prompts/pricing_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import CompetitorData, PricingAnalysis, PricingItem
from core.prompt_loader import load as load_prompts
import config
import json


class PricingAgent(BaseAgent):
    """定价分析Agent — 价格策略对比"""

    def __init__(self):
        prompts = load_prompts("pricing_agent")
        self._system_prompt_template = prompts["system_prompt"]
        self._prompt_analyze = prompts["prompt_analyze"]
        super().__init__(
            agent_id="PricingAgent",
            system_prompt=self._system_prompt_template,
        )

    def set_sub_dimensions(self, sub_dimensions_text: str):
        """注入动态子维度（由 DimensionAgent 生成）"""
        self.system_prompt = self._system_prompt_template.format(
            sub_dimensions=sub_dimensions_text
        )

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData],
                  target_product_data: CompetitorData | None = None,
                  sub_dimensions: str = "",
                  feedback: str = "") -> PricingAnalysis:
        """
        主运行逻辑：全量数据分析定价对比

        Args:
            product_name: 用户产品名称
            competitors_data: 竞品采集数据

        Returns:
            PricingAnalysis: 定价分析结果
        """
        self._log("💰 开始定价分析...")

        if sub_dimensions:
            self.set_sub_dimensions(sub_dimensions)

        competitors_text = self._build_competitors_text(product_name, competitors_data, target_product_data)

        # 注入质检反馈
        if feedback:
            competitors_text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=competitors_text,
            )
            result, truncated = self.ask_llm_json_with_truncation_check(prompt, max_tokens=4096)
            if result:
                if truncated and len(competitors_data) >= 2:
                    self._log(f"⚠️ 检测到输出截断，启动分片重试...")
                    chunked = await self._run_chunked(product_name, competitors_data, target_product_data, feedback)
                    if chunked:
                        return chunked
                analysis = self._parse_pricing_analysis(result)
                self._log(f"✅ 定价分析完成: {len(analysis.pricing_comparison)}个竞品定价对比")
                return analysis
            else:
                if truncated and len(competitors_data) >= 2:
                    self._log(f"⚠️ JSON解析失败+截断，尝试分片重试...")
                    chunked = await self._run_chunked(product_name, competitors_data, target_product_data, feedback)
                    if chunked:
                        return chunked
                self._log("⚠️ LLM定价分析失败，降级到规则引擎")

        return self._rule_analyze(product_name, competitors_data)

    async def _run_chunked(self, product_name: str,
                           competitors_data: dict[str, CompetitorData],
                           target_product_data: CompetitorData | None,
                           feedback: str) -> PricingAnalysis | None:
        """分片重试：将竞品拆成多批分别调用LLM，再合并结果。"""
        all_names = list(competitors_data.keys())
        if len(all_names) < 2:
            return None

        mid = len(all_names) // 2
        chunks = [
            {name: competitors_data[name] for name in all_names[:mid]},
            {name: competitors_data[name] for name in all_names[mid:]},
        ]

        all_items = []
        analyses = []
        all_citations = []

        for i, chunk in enumerate(chunks):
            self._log(f"  📦 分片 {i+1}/{len(chunks)}: {list(chunk.keys())}")
            chunk_text = self._build_competitors_text(product_name, chunk, target_product_data)
            if feedback:
                chunk_text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"

            prompt = self._prompt_analyze.format(product_name=product_name, competitors_text=chunk_text)
            result, truncated = self.ask_llm_json_with_truncation_check(prompt, max_tokens=4096)
            if not result:
                self._log(f"  ⚠️ 分片 {i+1} 调用失败，跳过")
                continue

            if truncated and len(chunk) >= 2:
                self._log(f"  ⚠️ 分片 {i+1} 仍然截断，继续拆分...")
                sub = await self._run_chunked(product_name, chunk, target_product_data, feedback)
                if sub:
                    all_items.extend(sub.pricing_comparison)
                    all_citations.extend(sub.citations)
                    if sub.pricing_strategy_analysis:
                        analyses.append(sub.pricing_strategy_analysis)
                continue

            parsed = self._parse_pricing_analysis(result)
            all_items.extend(parsed.pricing_comparison)
            all_citations.extend(parsed.citations)
            if parsed.pricing_strategy_analysis:
                analyses.append(parsed.pricing_strategy_analysis)

        if not all_items:
            return None

        self._log(f"✅ 分片合并完成: {len(all_items)}个竞品定价对比")
        return PricingAnalysis(
            pricing_comparison=all_items,
            pricing_strategy_analysis="；".join(analyses) if analyses else "",
            value_ranking=[],
            summary="",
            citations=list(set(all_citations)),
        )

    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData],
                                 target_product_data: CompetitorData | None = None) -> str:
        """构建竞品定价数据文本，附带引用来源编号"""
        lines = []

        def append_entity(name: str, data: CompetitorData):
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            if data.pricing_tiers:
                pricing_text = "; ".join([f"{pt.tier_name}: {pt.price}" for pt in data.pricing_tiers])
                lines.append(f"- 定价信息: {pricing_text[:300]}")
            else:
                lines.append("- 定价信息: 暂无数据")
            lines.append(f"- 优势: {data.strengths[:200]}")
            lines.append(f"- 劣势: {data.weaknesses[:200]}")
            if data.citations:
                lines.append(f"- 数据来源:")
                lines.append(self.build_citations_text(data.citations))

        if target_product_data:
            append_entity(product_name, target_product_data)
        for name, data in competitors_data.items():
            append_entity(name, data)
        return "\n".join(lines)

    def _parse_pricing_analysis(self, result: dict) -> PricingAnalysis:
        """解析LLM返回的定价分析结果，提取引用 ID"""
        all_citation_ids = []

        pricing_comparison = []
        for pc in result.get("pricing_comparison", []):
            pc_cites = self.extract_citation_ids(pc)
            all_citation_ids.extend(pc_cites)
            pricing_comparison.append(PricingItem(
                competitor=pc.get("competitor", ""),
                free_tier=pc.get("free_tier", ""),
                paid_tier=pc.get("paid_tier", ""),
                pricing_model=pc.get("pricing_model", ""),
                citations=pc_cites,
            ))

        return PricingAnalysis(
            pricing_comparison=pricing_comparison,
            pricing_strategy_analysis=result.get("pricing_strategy_analysis", ""),
            value_ranking=result.get("value_ranking", []),
            summary=result.get("summary", ""),
            citations=list(set(all_citation_ids)),
        )

    def _rule_analyze(self, product_name: str,
                       competitors_data: dict[str, CompetitorData]) -> PricingAnalysis:
        """规则引擎定价分析"""
        import re
        pricing_comparison = []
        for name, data in competitors_data.items():
            # 从结构化定价层级提取免费版信息
            free_tier = "未知"
            if data.pricing_tiers:
                for pt in data.pricing_tiers:
                    if "免费" in pt.tier_name or "free" in pt.tier_name.lower():
                        free_tier = f"{pt.tier_name}: {pt.price}"
                        break
                if free_tier == "未知" and data.pricing_tiers:
                    free_tier = f"{data.pricing_tiers[0].tier_name}: {data.pricing_tiers[0].price}"
            pricing_comparison.append(PricingItem(
                competitor=name,
                free_tier=free_tier,
                paid_tier="",
                pricing_model="",
            ))

        return PricingAnalysis(
            pricing_comparison=pricing_comparison,
            pricing_strategy_analysis="(规则引擎分析，详情请启用LLM)",
            value_ranking=[],
            summary="基于搜索结果的简单定价信息提取（建议启用LLM获得深度分析）",
        )
