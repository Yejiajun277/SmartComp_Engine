# -*- coding: utf-8 -*-
"""
agents/market_agent.py - 市场分析 Agent
"""

from __future__ import annotations

import re

import config
from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from models.domain import (
    Citation,
    CompetitorData,
    ConclusionItem,
    EvidenceBundle,
    MarketAnalysis,
    MarketShareItem,
    MessageEnvelope,
    UserPersona,
    UserReputation,
)


class MarketAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("market_agent")
        super().__init__(
            agent_id="MarketAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(
        self,
        product_name: str,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        competitors_data: dict[str, CompetitorData] | None = None,
    ) -> MarketAnalysis:
        competitors_data = competitors_data or self._build_competitors_data(evidence_bundles)
        citations = self._collect_unique_citations(evidence_bundles)

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=self._build_competitors_text(competitors_data, evidence_bundles),
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                analysis = self._parse_market_analysis(product_name, result, evidence_bundles, competitors_data, citations)
                if analysis.market_share_data:
                    self._log(f"市场 LLM 分析完成，竞品数={len(analysis.market_share_data)}")
                    return analysis
            self._log("市场 LLM 分析失败，降级到规则引擎")

        analysis = self._rule_analyze(product_name, competitors_data, evidence_bundles, citations)
        self._log(f"市场规则分析完成，竞品数={len(analysis.market_share_data)}")
        return analysis

    def _parse_market_analysis(
        self,
        product_name: str,
        result: dict,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        competitors_data: dict[str, CompetitorData],
        citations: list[Citation],
    ) -> MarketAnalysis:
        topic_citations = self._topic_citation_ids(
            evidence_bundles,
            {"market_share", "channels", "user_reviews"},
            8,
        )
        share_items: list[MarketShareItem] = []
        for item in result.get("market_share_data", []):
            competitor = str(item.get("competitor", "")).strip()
            if not competitor:
                continue
            citation_ids = self._competitor_citation_ids(evidence_bundles, competitor, "market_share", 3)
            share_estimate = str(item.get("share_estimate", "")).strip()
            trend = str(item.get("trend", "")).strip()
            share_items.append(
                MarketShareItem(
                    competitor=competitor,
                    share_estimate=share_estimate,
                    trend=trend,
                    market_position=self._market_position(share_estimate),
                    growth_signal=self._growth_signal(share_estimate, trend),
                    channel_motion=self._channel_motion(competitors_data.get(competitor)),
                    citations=citation_ids,
                )
            )

        reputation: dict[str, UserReputation] = {}
        raw_reputation = result.get("user_reputation", {})
        if isinstance(raw_reputation, dict):
            for competitor, item in raw_reputation.items():
                if not isinstance(item, dict):
                    continue
                citation_ids = self._competitor_citation_ids(evidence_bundles, competitor, "user_reviews", 3)
                keywords = [str(value).strip() for value in item.get("keywords", []) if str(value).strip()]
                reputation[str(competitor)] = UserReputation(
                    score=str(item.get("score", "")).strip(),
                    keywords=keywords[:8],
                    highlights=[value for value in keywords if not self._is_risk_word(value)][:3],
                    risks=[value for value in keywords if self._is_risk_word(value)][:3],
                    citations=citation_ids,
                )

        personas = self._build_personas(competitors_data, evidence_bundles, [])
        growth_trends = str(result.get("growth_trends", "")).strip()
        channel_analysis = str(result.get("channel_analysis", "")).strip()
        summary = str(result.get("summary", "")).strip()
        conclusions = self._build_conclusions(growth_trends, channel_analysis, summary, topic_citations)
        return MarketAnalysis(
            market_share_data=share_items,
            growth_trends=growth_trends,
            user_reputation=reputation,
            channel_analysis=channel_analysis,
            user_personas=personas,
            conclusions=conclusions,
            citations=citations,
            message=MessageEnvelope(
                task_id=f"{product_name}:market",
                agent_role=self.agent_id,
                payload_type="market_analysis",
                payload={"market_share_count": len(share_items), "llm": True},
                citations=[citation.id for citation in citations],
            ),
            summary=summary or growth_trends,
        )

    def _rule_analyze(
        self,
        product_name: str,
        competitors_data: dict[str, CompetitorData],
        evidence_bundles: dict[str, list[EvidenceBundle]],
        citations: list[Citation],
    ) -> MarketAnalysis:
        share_items: list[MarketShareItem] = []
        reputation: dict[str, UserReputation] = {}
        for competitor, data in competitors_data.items():
            citation_ids = self._competitor_citation_ids(evidence_bundles, competitor, "market_share", 3)
            trend = self._infer_trend(data.market_share)
            share_items.append(
                MarketShareItem(
                    competitor=competitor,
                    share_estimate=data.market_share[:160] or "暂无可比市场份额信息。",
                    trend=trend,
                    market_position=self._market_position(data.market_share),
                    growth_signal=self._growth_signal(data.market_share, trend),
                    channel_motion=self._channel_motion(data),
                    citations=citation_ids,
                )
            )
            review_citations = self._competitor_citation_ids(evidence_bundles, competitor, "user_reviews", 3)
            keywords = self._keywords(data.user_reviews)
            reputation[competitor] = UserReputation(
                score=self._score(data.user_reviews),
                keywords=keywords[:8],
                highlights=[word for word in keywords if not self._is_risk_word(word)][:3],
                risks=[word for word in keywords if self._is_risk_word(word)][:3],
                citations=review_citations,
            )

        personas = self._build_personas(competitors_data, evidence_bundles, [])
        growth = self._build_growth_trends(share_items)
        channel = self._build_channel_analysis(competitors_data)
        summary = (
            "市场层面应优先判断相对位置、增长方向和渠道抓手。"
            "\n\n"
            "公开信息不足以支持精确份额时，应把结论写成相对格局和机会窗口。"
            "\n\n"
            "用户口碑和渠道信息要服务于 ICP 与落地动作，而不是只做信息摘录。"
        )
        return MarketAnalysis(
            market_share_data=share_items,
            growth_trends=growth,
            user_reputation=reputation,
            channel_analysis=channel,
            user_personas=personas,
            conclusions=self._build_conclusions(
                growth,
                channel,
                summary,
                self._topic_citation_ids(evidence_bundles, {"market_share", "channels", "user_reviews"}, 8),
            ),
            citations=citations,
            message=MessageEnvelope(
                task_id=f"{product_name}:market",
                agent_role=self.agent_id,
                payload_type="market_analysis",
                payload={"market_share_count": len(share_items), "llm": False},
                citations=[citation.id for citation in citations],
            ),
            summary=summary,
        )

    @staticmethod
    def _build_competitors_text(
        competitors_data: dict[str, CompetitorData],
        evidence_bundles: dict[str, list[EvidenceBundle]],
    ) -> str:
        lines: list[str] = []
        for name, data in competitors_data.items():
            lines.append(f"\n### {name}")
            lines.append(f"- 市场份额/规模: {data.market_share[:1000]}")
            lines.append(f"- 用户口碑: {data.user_reviews[:900]}")
            lines.append(f"- 渠道/生态: {data.channels[:900]}")
            lines.append(f"- 产品与优势: {(data.product_features + ' ' + data.strengths)[:600]}")
            bundle_facts = []
            for bundle in evidence_bundles.get(name, []):
                if bundle.topic in {"market_share", "user_reviews", "channels"}:
                    bundle_facts.extend(bundle.key_facts[:2])
            if bundle_facts:
                lines.append(f"- 市场证据: {'；'.join(bundle_facts[:8])}")
        return "\n".join(lines)

    @staticmethod
    def _build_competitors_data(evidence_bundles: dict[str, list[EvidenceBundle]]) -> dict[str, CompetitorData]:
        data: dict[str, CompetitorData] = {}
        for competitor, bundles in evidence_bundles.items():
            topic_map = {bundle.topic: bundle for bundle in bundles}
            data[competitor] = CompetitorData(
                name=competitor,
                product_features=topic_map.get("product_features", EvidenceBundle(competitor, "")).summary,
                pricing_info=topic_map.get("pricing_info", EvidenceBundle(competitor, "")).summary,
                market_share=topic_map.get("market_share", EvidenceBundle(competitor, "")).summary,
                user_reviews=topic_map.get("user_reviews", EvidenceBundle(competitor, "")).summary,
                channels=topic_map.get("channels", EvidenceBundle(competitor, "")).summary,
            )
        return data

    @staticmethod
    def _build_conclusions(growth: str, channel: str, summary: str, citations: list[str]) -> list[ConclusionItem]:
        statements = [growth, channel, summary]
        return [
            ConclusionItem(
                id=f"market:conclusion:{index}",
                dimension="market",
                statement=statement.split("。")[0][:160],
                citations=citations,
                confidence=0.72,
                evidence_topics=["market_share", "channels", "user_reviews"],
            )
            for index, statement in enumerate(statements, start=1)
            if statement
        ]

    def _build_personas(
        self,
        competitors_data: dict[str, CompetitorData],
        evidence_bundles: dict[str, list[EvidenceBundle]],
        fallback_citations: list[str],
    ) -> list[UserPersona]:
        personas: list[UserPersona] = []
        for competitor, data in competitors_data.items():
            citations = self._competitor_citation_ids(evidence_bundles, competitor, "channels", 2)
            personas.append(
                UserPersona(
                    name=f"{competitor} 核心用户",
                    segment=self._segment(data.channels, data.user_reviews),
                    needs=self._needs(data.channels, data.market_share),
                    complaints=self._complaints(data.user_reviews),
                    preferred_channels=self._preferred_channels(data.channels),
                    persona_summary=f"{self._segment(data.channels, data.user_reviews)} 更关注 {'、'.join(self._needs(data.channels, data.market_share)[:2])}。",
                    citations=citations or fallback_citations,
                )
            )
        return personas

    @staticmethod
    def _market_position(text: str) -> str:
        if any(token in text for token in ("第一", "领先", "头部", "覆盖", "市占")):
            return "更像头部平台或强势玩家"
        if any(token in text for token in ("细分", "垂直", "场景", "蓝海")):
            return "更像场景型强者"
        return "当前更适合做相对位置判断"

    @staticmethod
    def _growth_signal(text: str, trend: str) -> str:
        if trend:
            return f"趋势判断为 {trend}。"
        if any(token in text for token in ("增长", "提升", "突破", "扩大", "渗透")):
            return text[:100]
        return "公开信息更多在描述位置，而不是明确增长。"

    @staticmethod
    def _channel_motion(data: CompetitorData | None) -> str:
        if not data or not data.channels:
            return "渠道动作信息有限。"
        return data.channels[:120]

    @staticmethod
    def _infer_trend(text: str) -> str:
        if any(token in text for token in ("增长", "扩大", "领先", "提升", "突破", "上升")):
            return "上升"
        if any(token in text for token in ("下滑", "放缓", "承压", "下降")):
            return "下降"
        return "稳定"

    @staticmethod
    def _score(text: str) -> str:
        if any(token in text for token in ("投诉", "问题", "复杂", "不足", "退款", "推诿")):
            return "中性偏谨慎"
        if text:
            return "中性偏正向"
        return "未知"

    @staticmethod
    def _segment(channel_text: str, review_text: str) -> str:
        text = f"{channel_text} {review_text}"
        if any(token in text for token in ("企业", "组织", "团队", "协同", "政务")):
            return "企业协同团队"
        if any(token in text for token in ("销售", "客户", "私域", "运营")):
            return "业务增长团队"
        if any(token in text for token in ("开发者", "API", "模型", "代码")):
            return "开发者与技术团队"
        return "泛团队用户"

    @staticmethod
    def _needs(channel_text: str, market_text: str) -> list[str]:
        words = MarketAgent._keywords(f"{channel_text} {market_text}")
        filtered = [word for word in words if word not in {"企业", "团队", "客户", "用户", "市场"}]
        return filtered[:4] or ["效率提升", "业务增长"]

    @staticmethod
    def _complaints(text: str) -> list[str]:
        parts = re.findall(r"[^。！？!?]*(?:复杂|问题|投诉|限制|昂贵|不足|退款|推诿)[^。！？!?]*", text or "")
        return [part.strip()[:48] for part in parts[:3]]

    @staticmethod
    def _preferred_channels(text: str) -> list[str]:
        words = MarketAgent._keywords(text)
        keep = [word for word in words if any(token in word for token in ("生态", "伙伴", "直销", "区域", "服务", "代理", "官网"))]
        return keep[:4] or words[:4]

    @staticmethod
    def _keywords(text: str) -> list[str]:
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", text or "")
        result: list[str] = []
        for word in words:
            lowered = word.lower()
            if lowered not in result:
                result.append(lowered)
        return result[:16]

    @staticmethod
    def _is_risk_word(text: str) -> bool:
        return any(token in text for token in ("投诉", "复杂", "不足", "退款", "限制", "贵", "推诿", "问题"))

    @staticmethod
    def _build_growth_trends(share_items: list[MarketShareItem]) -> str:
        if not share_items:
            return "当前市场信息有限，建议优先补齐官方或研究机构披露。"
        leading = "；".join(f"{item.competitor}: {item.growth_signal}" for item in share_items[:3])
        return f"公开资料更适合判断相对位置和增长方向。{leading}"

    @staticmethod
    def _build_channel_analysis(competitors_data: dict[str, CompetitorData]) -> str:
        motions = [
            f"{name}: {data.channels[:80]}" for name, data in competitors_data.items() if data.channels
        ][:3]
        return "；".join(motions) or "渠道侧公开信息有限，需补齐生态伙伴、销售方式和目标客群。"

    @staticmethod
    def _collect_unique_citations(evidence_bundles: dict[str, list[EvidenceBundle]]) -> list[Citation]:
        seen: dict[str, Citation] = {}
        priority = {"official": 4, "media": 3, "community": 2, "complaint": 1, "aggregator": 0}
        for bundles in evidence_bundles.values():
            for bundle in bundles:
                for citation in bundle.citations:
                    if citation.source_quality != "low_quality":
                        seen.setdefault(citation.id, citation)
        return sorted(
            seen.values(),
            key=lambda item: (priority.get(item.source_quality, 0), item.confidence, item.title),
            reverse=True,
        )

    @staticmethod
    def _topic_citation_ids(
        evidence_bundles: dict[str, list[EvidenceBundle]],
        topics: set[str],
        limit: int = 3,
    ) -> list[str]:
        grouped = [
            [
                citation.id
                for bundle in bundles
                if bundle.topic in topics
                for citation in bundle.citations
                if citation.source_quality != "low_quality"
            ]
            for bundles in evidence_bundles.values()
        ]
        ids = [
            citation_id
            for index in range(max((len(items) for items in grouped), default=0))
            for items in grouped
            for citation_id in items[index:index + 1]
        ]
        return list(dict.fromkeys(ids))[:limit]

    @staticmethod
    def _competitor_citation_ids(
        evidence_bundles: dict[str, list[EvidenceBundle]],
        competitor: str,
        topic: str | None = None,
        limit: int = 3,
    ) -> list[str]:
        ids = [
            citation.id
            for bundle in evidence_bundles.get(competitor, [])
            if topic is None or bundle.topic == topic
            for citation in bundle.citations
            if citation.source_quality != "low_quality"
        ]
        return list(dict.fromkeys(ids))[:limit]
