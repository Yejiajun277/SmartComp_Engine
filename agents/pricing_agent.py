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
        super().__init__(
            agent_id="PricingAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData]) -> PricingAnalysis:
        """
        主运行逻辑：全量数据分析定价对比

        Args:
            product_name: 用户产品名称
            competitors_data: 竞品采集数据

        Returns:
            PricingAnalysis: 定价分析结果
        """
        self._log("💰 开始定价分析...")

        competitors_text = self._build_competitors_text(product_name, competitors_data)

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=competitors_text,
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                analysis = self._parse_pricing_analysis(result)
                self._log(f"✅ 定价分析完成: {len(analysis.pricing_comparison)}个竞品定价对比")
                return analysis
            else:
                self._log("⚠️ LLM定价分析失败，降级到规则引擎")

        return self._rule_analyze(product_name, competitors_data)

    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData]) -> str:
        """构建竞品定价数据文本"""
        lines = []
        for name, data in competitors_data.items():
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            lines.append(f"- 定价信息: {data.pricing_info[:300]}")
            lines.append(f"- 优势: {data.strengths[:200]}")
            lines.append(f"- 劣势: {data.weaknesses[:200]}")
        return "\n".join(lines)

    def _parse_pricing_analysis(self, result: dict) -> PricingAnalysis:
        """解析LLM返回的定价分析结果"""
        pricing_comparison = []
        for pc in result.get("pricing_comparison", []):
            pricing_comparison.append(PricingItem(
                competitor=pc.get("competitor", ""),
                free_tier=pc.get("free_tier", ""),
                paid_tier=pc.get("paid_tier", ""),
                pricing_model=pc.get("pricing_model", ""),
            ))

        return PricingAnalysis(
            pricing_comparison=pricing_comparison,
            pricing_strategy_analysis=result.get("pricing_strategy_analysis", ""),
            value_ranking=result.get("value_ranking", []),
            summary=result.get("summary", ""),
        )

    def _rule_analyze(self, product_name: str,
                       competitors_data: dict[str, CompetitorData]) -> PricingAnalysis:
        """规则引擎定价分析"""
        import re
        pricing_comparison = []
        for name, data in competitors_data.items():
            pricing_comparison.append(PricingItem(
                competitor=name,
                free_tier=data.pricing_info[:100] if data.pricing_info else "未知",
                paid_tier="",
                pricing_model="",
            ))

        return PricingAnalysis(
            pricing_comparison=pricing_comparison,
            pricing_strategy_analysis="(规则引擎分析，详情请启用LLM)",
            value_ranking=[],
            summary="基于搜索结果的简单定价信息提取（建议启用LLM获得深度分析）",
        )
