# -*- coding: utf-8 -*-
"""
agents/market_agent.py — 市场分析Agent

职责：分析市场份额、增长趋势、用户口碑、渠道策略
LLM调用：1次
外部工具：无
提示词来源：prompts/market_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import CompetitorData, MarketAnalysis, MarketShareItem, UserReputation, UserProfile
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
                  competitors_data: dict[str, CompetitorData],
                  target_product_data: CompetitorData | None = None,
                  feedback: str = "") -> MarketAnalysis:
        """
        主运行逻辑：全量数据分析市场格局

        Args:
            product_name: 用户产品名称
            competitors_data: 竞品采集数据

        Returns:
            MarketAnalysis: 市场分析结果
        """
        self._log("📈 开始市场分析...")

        competitors_text = self._build_competitors_text(product_name, competitors_data, target_product_data)

        # 注入质检反馈
        if feedback:
            competitors_text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=competitors_text,
            )
            result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=4096)
            if result:
                if truncated and len(competitors_data) >= 2:
                    self._log(f"⚠️ 检测到输出截断，启动分片重试...")
                    chunked = await self._run_chunked(product_name, competitors_data, target_product_data, feedback)
                    if chunked:
                        return chunked
                analysis = self._parse_market_analysis(result)
                self._log(f"✅ 市场分析完成: {len(analysis.market_share_data)}个竞品市场数据")
                return analysis
            else:
                if truncated and len(competitors_data) >= 2:
                    self._log(f"⚠️ JSON解析失败+截断，尝试分片重试...")
                    chunked = await self._run_chunked(product_name, competitors_data, target_product_data, feedback)
                    if chunked:
                        return chunked
                self._log("⚠️ LLM市场分析失败，降级到规则引擎")

        return self._rule_analyze(product_name, competitors_data)

    async def _run_chunked(self, product_name: str,
                           competitors_data: dict[str, CompetitorData],
                           target_product_data: CompetitorData | None,
                           feedback: str) -> MarketAnalysis | None:
        """分片重试：将竞品拆成多批分别调用LLM，再合并结果。"""
        all_names = list(competitors_data.keys())
        if len(all_names) < 2:
            return None

        mid = len(all_names) // 2
        chunks = [
            {name: competitors_data[name] for name in all_names[:mid]},
            {name: competitors_data[name] for name in all_names[mid:]},
        ]

        all_share = []
        all_reputation = {}
        all_profiles = {}
        analyses = []
        all_citations = []

        for i, chunk in enumerate(chunks):
            self._log(f"  📦 分片 {i+1}/{len(chunks)}: {list(chunk.keys())}")
            chunk_text = self._build_competitors_text(product_name, chunk, target_product_data)
            if feedback:
                chunk_text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"

            prompt = self._prompt_analyze.format(product_name=product_name, competitors_text=chunk_text)
            result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=4096)
            if not result:
                self._log(f"  ⚠️ 分片 {i+1} 调用失败，跳过")
                continue

            if truncated and len(chunk) >= 2:
                self._log(f"  ⚠️ 分片 {i+1} 仍然截断，继续拆分...")
                sub = await self._run_chunked(product_name, chunk, target_product_data, feedback)
                if sub:
                    all_share.extend(sub.market_share_data)
                    all_reputation.update(sub.user_reputation)
                    all_profiles.update(sub.user_profiles)
                    all_citations.extend(sub.citations)
                    if sub.growth_trends:
                        analyses.append(sub.growth_trends)
                continue

            parsed = self._parse_market_analysis(result)
            all_share.extend(parsed.market_share_data)
            all_reputation.update(parsed.user_reputation)
            all_profiles.update(parsed.user_profiles)
            all_citations.extend(parsed.citations)
            if parsed.growth_trends:
                analyses.append(parsed.growth_trends)

        if not all_share and not all_reputation:
            return None

        self._log(f"✅ 分片合并完成: {len(all_share)}个市场份额, {len(all_reputation)}个口碑, {len(all_profiles)}个画像")
        return MarketAnalysis(
            market_share_data=all_share,
            growth_trends="；".join(analyses) if analyses else "",
            user_reputation=all_reputation,
            user_profiles=all_profiles,
            channel_analysis="",
            summary="",
            citations=list(set(all_citations)),
        )

    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData],
                                 target_product_data: CompetitorData | None = None) -> str:
        """构建竞品市场数据文本，附带引用来源编号"""
        lines = []

        def append_entity(name: str, data: CompetitorData):
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            lines.append(f"- 市场份额: {data.market_share[:300]}")
            lines.append(f"- 用户评价: {data.user_reviews[:300]}")
            lines.append(f"- 渠道策略: {data.channels[:200]}")
            if data.citations:
                lines.append(f"- 数据来源:")
                lines.append(self.build_citations_text(data.citations))

        if target_product_data:
            append_entity(product_name, target_product_data)
        for name, data in competitors_data.items():
            append_entity(name, data)
        return "\n".join(lines)

    # 商业/财务术语黑名单（pain_points 中不允许出现）
    _COMMERCIAL_TERMS = {
        "定价", "涨幅", "C端", "B端", "获客", "变现", "营收", "毛利",
        "净利", "ARPU", "LTV", "CAC", "ROI", "GMV", "付费率",
        "续费", "客单价", "转化率", "复购", "漏斗", "投放",
    }

    @classmethod
    def _sanitize_pain_points(cls, pain_points: list[str]) -> list[str]:
        """过滤掉商业/财务术语，只保留用户视角的痛点"""
        cleaned = []
        for pp in pain_points:
            if not pp or not pp.strip():
                continue
            # 检查是否包含商业术语
            if any(term in pp for term in cls._COMMERCIAL_TERMS):
                continue
            cleaned.append(pp.strip())
        return cleaned if cleaned else ["暂无用户视角痛点数据"]

    @staticmethod
    def _normalize_trend(trend: str) -> str:
        """标准化趋势描述为枚举值"""
        t = trend.strip()
        if any(k in t for k in ["上升", "增长", "上涨", "↗", "↑", "高速", "快速增长"]):
            return "上升"
        elif any(k in t for k in ["下降", "下滑", "下跌", "↘", "↓", "小幅下降"]):
            return "下降"
        else:
            return "稳定"

    def _parse_market_analysis(self, result: dict) -> MarketAnalysis:
        """解析LLM返回的市场分析结果，提取引用 ID"""
        all_citation_ids = []

        market_share_data = []
        for ms in result.get("market_share_data", []):
            ms_cites = self.extract_citation_ids(ms)
            all_citation_ids.extend(ms_cites)
            market_share_data.append(MarketShareItem(
                competitor=ms.get("competitor", ""),
                share_estimate=ms.get("share_estimate", ""),
                trend=self._normalize_trend(ms.get("trend", "")),
                citations=ms_cites,
            ))

        user_reputation = {}
        for name, rep in result.get("user_reputation", {}).items():
            rep_cites = self.extract_citation_ids(rep)
            all_citation_ids.extend(rep_cites)
            user_reputation[name] = UserReputation(
                score=rep.get("score", ""),
                keywords=rep.get("keywords", []),
                citations=rep_cites,
            )

        user_profiles = {}
        for name, profile in result.get("user_profiles", {}).items():
            profile_cites = self.extract_citation_ids(profile)
            all_citation_ids.extend(profile_cites)
            user_profiles[name] = UserProfile(
                target_audience=profile.get("target_audience", ""),
                age_range=profile.get("age_range", ""),
                occupation_distribution=profile.get("occupation_distribution", []),
                use_cases=profile.get("use_cases", []),
                pain_points=self._sanitize_pain_points(profile.get("pain_points", [])),
                citations=profile_cites,
            )

        return MarketAnalysis(
            market_share_data=market_share_data,
            growth_trends=result.get("growth_trends", ""),
            user_reputation=user_reputation,
            user_profiles=user_profiles,
            channel_analysis=result.get("channel_analysis", ""),
            summary=result.get("summary", ""),
            citations=list(set(all_citation_ids)),
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
