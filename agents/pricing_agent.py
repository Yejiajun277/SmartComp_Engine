# -*- coding: utf-8 -*-
"""
agents/pricing_agent.py - 定价分析 Agent
"""

from __future__ import annotations

from agents.base_agent import BaseAgent
from models.domain import (
    Citation,
    ConclusionItem,
    EvidenceBundle,
    MessageEnvelope,
    PricingAnalysis,
    PricingItem,
    PricingModel,
)


class PricingAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_id="PricingAgent",
            system_prompt="你负责基于结构化证据做定价与计费分析。",
        )

    async def run(
        self,
        product_name: str,
        evidence_bundles: dict[str, list[EvidenceBundle]],
    ) -> PricingAnalysis:
        pricing_comparison: list[PricingItem] = []
        pricing_models: list[PricingModel] = []
        conclusions: list[ConclusionItem] = []
        citations = self._collect_unique_citations(evidence_bundles)

        model_counts: dict[str, int] = {}
        free_tier_count = 0
        evidence_summaries: list[str] = []
        for competitor, bundles in evidence_bundles.items():
            bundle = self._find_bundle(bundles, "pricing_info")
            summary = bundle.summary if bundle else ""
            evidence_summaries.append(summary)
            model = self._guess_model(summary)
            free_tier = self._extract_free_tier(summary)
            paid_tier = self._extract_paid_tier(summary)
            billing_basis = self._extract_billing_basis(summary, model)
            citation_ids = [item.id for item in bundle.citations[:3]] if bundle else []
            pricing_comparison.append(
                PricingItem(
                    competitor=competitor,
                    free_tier=free_tier,
                    paid_tier=paid_tier,
                    pricing_model=model,
                    citations=citation_ids,
                )
            )
            pricing_models.append(
                PricingModel(
                    competitor=competitor,
                    model=model,
                    free_tier=free_tier,
                    paid_tier=paid_tier,
                    billing_basis=billing_basis,
                    citations=citation_ids,
                )
            )
            model_counts[model] = model_counts.get(model, 0) + 1
            if "免费" in free_tier:
                free_tier_count += 1

        ranked = sorted(
            pricing_comparison,
            key=lambda item: (0 if "免费" in item.free_tier else 1, -len(item.paid_tier), item.competitor),
        )
        value_ranking = [item.competitor for item in ranked]
        dominant_model = max(model_counts.items(), key=lambda item: item[1])[0] if model_counts else "subscription"

        conclusions.append(
            ConclusionItem(
                id="pricing:conclusion:1",
                dimension="pricing",
                statement=f"竞品当前以 {dominant_model} 为主导计费模式，说明采购决策仍然偏向可解释、可预算的商业模型。",
                citations=[citation.id for citation in citations[:3]],
                confidence=0.71,
                evidence_topics=["pricing_info"],
            )
        )
        conclusions.append(
            ConclusionItem(
                id="pricing:conclusion:2",
                dimension="pricing",
                statement=f"{free_tier_count} 个竞品明确保留免费或低门槛入口，这意味着试用转化仍是该赛道的重要获客方式。",
                citations=[citation.id for citation in citations[:3]],
                confidence=0.68,
                evidence_topics=["pricing_info"],
            )
        )
        conclusions.append(
            ConclusionItem(
                id="pricing:conclusion:3",
                dimension="pricing",
                statement="如果我方只强调价格高低，而不解释适用场景、席位边界和增购逻辑，用户很难真正理解方案价值。",
                citations=[citation.id for citation in citations[1:4] or citations[:2]],
                confidence=0.64,
                evidence_topics=["pricing_info"],
            )
        )

        pricing_strategy_analysis = (
            f"从现有证据看，竞品多数采用 {dominant_model} 或混合计费，把基础能力作为进入门槛，把进阶能力、席位扩展或 AI 能力作为增购点。"
            "这类设计的核心目标不是单纯提价，而是让不同规模团队可以先进入、再逐步升级。"
            "因此我方在报告里应把“免费入口、升级节点、计费单位、增购理由”讲完整，否则对比只会停留在片段价格。"
        )

        message = MessageEnvelope(
            task_id=f"{product_name}:pricing",
            agent_role=self.agent_id,
            payload_type="pricing_analysis",
            payload={
                "pricing_model_count": len(pricing_models),
                "comparison_count": len(pricing_comparison),
                "dominant_model": dominant_model,
            },
            citations=[citation.id for citation in citations],
        )
        self._log(f"定价分析完成，模型数={len(pricing_models)}")
        return PricingAnalysis(
            pricing_comparison=pricing_comparison,
            pricing_strategy_analysis=pricing_strategy_analysis,
            value_ranking=value_ranking,
            pricing_models=pricing_models,
            conclusions=conclusions,
            citations=citations,
            message=message,
            summary=self._build_summary(pricing_comparison, pricing_models, dominant_model),
        )

    def _build_summary(
        self,
        pricing_comparison: list[PricingItem],
        pricing_models: list[PricingModel],
        dominant_model: str,
    ) -> str:
        free_names = [item.competitor for item in pricing_comparison if "免费" in item.free_tier][:4]
        basis_names = [f"{item.competitor} 采用 {item.billing_basis}" for item in pricing_models[:3]]
        paragraph_1 = (
            f"从免费/付费层级看，{', '.join(free_names) if free_names else '大部分竞品'} 都保留了低门槛入口，"
            "先让团队试用，再通过高级功能、席位或算力能力完成升级。"
        )
        paragraph_2 = (
            f"从计费模式看，当前主导模型是 {dominant_model}。"
            f"{'；'.join(basis_names) if basis_names else '现有公开信息仍以套餐与席位计费为主。'}"
        )
        paragraph_3 = (
            "从价格带表达看，报告不能只放“贵/便宜”判断，必须同时解释什么功能留在免费版、什么能力触发升级，以及升级后是否形成真正价值闭环。"
        )
        return "\n\n".join([paragraph_1, paragraph_2, paragraph_3])

    @staticmethod
    def _find_bundle(bundles: list[EvidenceBundle], topic: str) -> EvidenceBundle | None:
        for bundle in bundles:
            if bundle.topic == topic:
                return bundle
        return None

    @staticmethod
    def _guess_model(summary: str) -> str:
        text = summary.lower()
        if "按量" in summary or "usage" in text or "调用" in summary:
            return "usage-based"
        if "用户" in summary or "seat" in text or "席位" in summary:
            return "per-seat"
        if "免费" in summary or "freemium" in text:
            return "freemium"
        return "subscription"

    @staticmethod
    def _extract_free_tier(summary: str) -> str:
        if not summary:
            return "未知"
        if "免费" in summary:
            return summary[:80]
        return "未明确披露免费层"

    @staticmethod
    def _extract_paid_tier(summary: str) -> str:
        if not summary:
            return "未知"
        return summary[:160]

    @staticmethod
    def _extract_billing_basis(summary: str, model: str) -> str:
        text = summary.lower()
        if "席位" in summary or "seat" in text or "用户" in summary:
            return "seat"
        if "按量" in summary or "调用" in summary or "usage" in text:
            return "usage"
        if model == "freemium":
            return "mixed"
        return "package"

    @staticmethod
    def _collect_unique_citations(evidence_bundles: dict[str, list[EvidenceBundle]]) -> list[Citation]:
        seen: dict[str, Citation] = {}
        for bundles in evidence_bundles.values():
            for bundle in bundles:
                for citation in bundle.citations:
                    seen.setdefault(citation.id, citation)
        return list(seen.values())
