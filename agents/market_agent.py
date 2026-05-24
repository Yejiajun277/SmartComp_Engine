# -*- coding: utf-8 -*-
"""
agents/market_agent.py — 市场分析Agent

职责：分析市场份额、增长趋势、用户口碑、渠道策略
LLM调用：1次
外部工具：无
提示词来源：prompts/market_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import CompetitorData, MarketAnalysis, MarketShareItem, UserReputation
from core.prompt_loader import load as load_prompts
import config
import json


class MarketAgent(BaseAgent):
    """市场分析Agent — 市场格局与趋势"""

    def __init__(self):
        prompts = load_prompts("market_agent")
        super().__init__(
            agent_id="MarketAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData]) -> MarketAnalysis:
        """
        主运行逻辑：全量数据分析市场格局

        Args:
            product_name: 用户产品名称
            competitors_data: 竞品采集数据

        Returns:
            MarketAnalysis: 市场分析结果
        """
        self._log("📈 开始市场分析...")

        competitors_text = self._build_competitors_text(product_name, competitors_data)

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=competitors_text,
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                analysis = self._parse_market_analysis(result)
                self._log(f"✅ 市场分析完成: {len(analysis.market_share_data)}个竞品市场数据")
                return analysis
            else:
                self._log("⚠️ LLM市场分析失败，降级到规则引擎")

        return self._rule_analyze(product_name, competitors_data)

    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData]) -> str:
        """构建竞品市场数据文本"""
        lines = []
        for name, data in competitors_data.items():
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            lines.append(f"- 市场份额: {data.market_share[:300]}")
            lines.append(f"- 用户评价: {data.user_reviews[:300]}")
            lines.append(f"- 渠道策略: {data.channels[:200]}")
        return "\n".join(lines)

    def _parse_market_analysis(self, result: dict) -> MarketAnalysis:
        """解析LLM返回的市场分析结果"""
        market_share_data = []
        for ms in result.get("market_share_data", []):
            market_share_data.append(MarketShareItem(
                competitor=ms.get("competitor", ""),
                share_estimate=ms.get("share_estimate", ""),
                trend=ms.get("trend", ""),
            ))

        user_reputation = {}
        for name, rep in result.get("user_reputation", {}).items():
            user_reputation[name] = UserReputation(
                score=rep.get("score", ""),
                keywords=rep.get("keywords", []),
            )

        return MarketAnalysis(
            market_share_data=market_share_data,
            growth_trends=result.get("growth_trends", ""),
            user_reputation=user_reputation,
            channel_analysis=result.get("channel_analysis", ""),
            summary=result.get("summary", ""),
        )

    def _rule_analyze(self, product_name: str,
                       competitors_data: dict[str, CompetitorData]) -> MarketAnalysis:
        """规则引擎市场分析"""
        market_share_data = []
        for name, data in competitors_data.items():
            market_share_data.append(MarketShareItem(
                competitor=name,
                share_estimate=data.market_share[:100] if data.market_share else "未知",
                trend="未知",
            ))

        return MarketAnalysis(
            market_share_data=market_share_data,
            growth_trends="(规则引擎分析，详情请启用LLM)",
            user_reputation={},
            channel_analysis="",
            summary="基于搜索结果的简单市场信息提取（建议启用LLM获得深度分析）",
        )
