# -*- coding: utf-8 -*-
"""
agents/market_agent.py - 市场分析 Agent
"""

from __future__ import annotations

import re

from agents.base_agent import BaseAgent
from models.domain import (
    Citation,
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
        super().__init__(
            agent_id="MarketAgent",
            system_prompt="你负责基于结构化证据做市场、口碑和用户画像分析。",
        )

    async def run(
        self,
        product_name: str,
        evidence_bundles: dict[str, list[EvidenceBundle]],
    ) -> MarketAnalysis:
        share_items: list[MarketShareItem] = []
        user_reputation: dict[str, UserReputation] = {}
        personas: list[UserPersona] = []
        conclusions: list[ConclusionItem] = []
        citations = self._collect_unique_citations(evidence_bundles)

        growth_signals = 0
        channel_terms: list[str] = []
        for competitor, bundles in evidence_bundles.items():
            market_bundle = self._find_bundle(bundles, "market_share")
            review_bundle = self._find_bundle(bundles, "user_reviews")
            channel_bundle = self._find_bundle(bundles, "channels")
            market_summary = market_bundle.summary if market_bundle else ""
            review_text = review_bundle.summary if review_bundle else ""
            channel_text = channel_bundle.summary if channel_bundle else ""

            trend = self._infer_trend(market_summary)
            if trend == "增长":
                growth_signals += 1
            share_items.append(
                MarketShareItem(
                    competitor=competitor,
                    share_estimate=(market_summary[:140] if market_summary else "未知"),
                    trend=trend,
                    citations=[item.id for item in (market_bundle.citations[:3] if market_bundle else [])],
                )
            )
            user_reputation[competitor] = UserReputation(
                score=self._score(review_text),
                keywords=self._keywords(review_text)[:6],
                citations=[item.id for item in (review_bundle.citations[:3] if review_bundle else [])],
            )
            personas.append(
                UserPersona(
                    name=f"{competitor} 核心用户",
                    segment=self._segment(channel_text, review_text),
                    needs=self._keywords(f"{channel_text} {market_summary}")[:4],
                    complaints=self._complaints(review_text),
                    preferred_channels=self._keywords(channel_text)[:4],
                    citations=[
                        item.id
                        for item in (
                            (review_bundle.citations if review_bundle else [])
                            + (channel_bundle.citations if channel_bundle else [])
                        )[:4]
                    ],
                )
            )
            channel_terms.extend(self._keywords(channel_text)[:3])

        conclusions.append(
            ConclusionItem(
                id="market:conclusion:1",
                dimension="market",
                statement=f"在 {len(share_items)} 个竞品里，有 {growth_signals} 个呈现明显增长信号，说明赛道仍在扩张而不是单纯存量替换。",
                citations=[citation.id for citation in citations[:3]],
                confidence=0.7,
                evidence_topics=["market_share"],
            )
        )
        conclusions.append(
            ConclusionItem(
                id="market:conclusion:2",
                dimension="market",
                statement="用户评价最有价值的部分不是好评本身，而是对复杂度、交付周期、售后响应等问题的反复提及，这些往往直接决定续费与口碑扩散。",
                citations=[citation.id for citation in citations[1:4] or citations[:2]],
                confidence=0.67,
                evidence_topics=["user_reviews"],
            )
        )
        conclusions.append(
            ConclusionItem(
                id="market:conclusion:3",
                dimension="market",
                statement="渠道与画像信息显示，竞品多数不是在争夺抽象用户，而是在争夺明确的团队场景与组织类型，因此报告中的 ICP 必须落到可执行用户群。",
                citations=[citation.id for citation in citations[:3]],
                confidence=0.66,
                evidence_topics=["channels", "user_reviews"],
            )
        )

        growth_trends = (
            "公开证据显示，这条赛道仍然由增长、替换和能力升级共同驱动。"
            "有的竞品靠市场份额和客户规模建立头部优势，有的竞品则靠细分场景和生态位置切入。"
            "因此市场判断应关注增长来源，而不是只看单点规模。"
        )
        channel_analysis = (
            "渠道侧能看到明显的生态合作、直销和服务商分工。"
            f"当前高频出现的渠道关键词包括：{', '.join(list(dict.fromkeys(channel_terms))[:6]) or '生态、伙伴、直销'}。"
            "这说明成交逻辑通常和场景方案、实施能力绑定。"
        )

        message = MessageEnvelope(
            task_id=f"{product_name}:market",
            agent_role=self.agent_id,
            payload_type="market_analysis",
            payload={
                "market_share_count": len(share_items),
                "persona_count": len(personas),
                "growth_signals": growth_signals,
            },
            citations=[citation.id for citation in citations],
        )
        self._log(f"市场分析完成，画像数={len(personas)}")
        return MarketAnalysis(
            market_share_data=share_items,
            growth_trends=growth_trends,
            user_reputation=user_reputation,
            channel_analysis=channel_analysis,
            user_personas=personas,
            conclusions=conclusions,
            citations=citations,
            message=message,
            summary=self._build_summary(share_items, user_reputation, personas),
        )

    def _build_summary(
        self,
        share_items: list[MarketShareItem],
        user_reputation: dict[str, UserReputation],
        personas: list[UserPersona],
    ) -> str:
        share_lines = [f"{item.competitor}：{item.trend}" for item in share_items[:4]]
        reputation_lines = [
            f"{competitor} 口碑关键词：{', '.join(profile.keywords[:4]) or '暂无'}"
            for competitor, profile in list(user_reputation.items())[:2]
        ]
        persona_lines = [
            f"{persona.name} 关注 {', '.join(persona.needs[:3]) or '效率与协作'}。"
            for persona in personas[:2]
        ]
        paragraph_1 = (
            "从市场格局看，公开信息能提供趋势判断，但未必能提供完全可比的精确市占率。"
            f"{'；'.join(share_lines) if share_lines else '当前更适合做相对强弱判断。'}"
        )
        paragraph_2 = (
            "从用户口碑看，真实竞争不只发生在功能层，而是发生在上手难度、实施体验和问题响应速度。"
            f"{' '.join(reputation_lines)}"
        )
        paragraph_3 = (
            "从用户画像与渠道看，竞品普遍围绕明确组织类型和场景成交。"
            f"{' '.join(persona_lines)}"
        )
        return "\n\n".join([paragraph_1, paragraph_2, paragraph_3])

    @staticmethod
    def _find_bundle(bundles: list[EvidenceBundle], topic: str) -> EvidenceBundle | None:
        for bundle in bundles:
            if bundle.topic == topic:
                return bundle
        return None

    @staticmethod
    def _collect_unique_citations(evidence_bundles: dict[str, list[EvidenceBundle]]) -> list[Citation]:
        seen: dict[str, Citation] = {}
        for bundles in evidence_bundles.values():
            for bundle in bundles:
                for citation in bundle.citations:
                    seen.setdefault(citation.id, citation)
        return list(seen.values())

    @staticmethod
    def _infer_trend(text: str) -> str:
        if any(token in text for token in ("增长", "扩大", "领先", "提升")):
            return "增长"
        if any(token in text for token in ("下滑", "放缓", "承压")):
            return "承压"
        return "待核验"

    @staticmethod
    def _score(text: str) -> str:
        if any(token in text for token in ("投诉", "问题", "复杂", "不足", "退费")):
            return "中性偏谨慎"
        if text:
            return "中性偏正向"
        return "未知"

    @staticmethod
    def _segment(channel_text: str, review_text: str) -> str:
        text = f"{channel_text} {review_text}"
        if any(token in text for token in ("企业", "组织", "团队", "协同")):
            return "企业团队"
        if any(token in text for token in ("商家", "销售", "客户")):
            return "业务增长团队"
        return "泛团队用户"

    @staticmethod
    def _keywords(text: str) -> list[str]:
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", text or "")
        return list(dict.fromkeys(word.lower() for word in words[:16]))

    @staticmethod
    def _complaints(text: str) -> list[str]:
        parts = re.findall(r"[^。！？!?]*(?:复杂|问题|投诉|限制|昂贵|不足|退费)[^。！？!?]*", text or "")
        cleaned = [part.strip() for part in parts if part.strip()]
        return cleaned[:4]
