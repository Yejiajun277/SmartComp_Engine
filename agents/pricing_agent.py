# -*- coding: utf-8 -*-
"""
agents/pricing_agent.py - 定价分析 Agent
"""

from __future__ import annotations

import config
from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from models.domain import (
    Citation,
    CompetitorData,
    ConclusionItem,
    EvidenceBundle,
    MessageEnvelope,
    PricingAnalysis,
    PricingItem,
    PricingModel,
)


class PricingAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("pricing_agent")
        super().__init__(
            agent_id="PricingAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(
        self,
        product_name: str,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        competitors_data: dict[str, CompetitorData] | None = None,
    ) -> PricingAnalysis:
        competitors_data = competitors_data or self._build_competitors_data(evidence_bundles)
        citations = self._collect_unique_citations(evidence_bundles)

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=self._build_competitors_text(competitors_data, evidence_bundles),
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                analysis = self._parse_pricing_analysis(product_name, result, evidence_bundles, citations)
                if analysis.pricing_comparison:
                    self._log(f"定价 LLM 分析完成，竞品数={len(analysis.pricing_comparison)}")
                    return analysis
            self._log("定价 LLM 分析失败，降级到规则引擎")

        analysis = self._rule_analyze(product_name, competitors_data, evidence_bundles, citations)
        self._log(f"定价规则分析完成，竞品数={len(analysis.pricing_comparison)}")
        return analysis

    def _parse_pricing_analysis(
        self,
        product_name: str,
        result: dict,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        citations: list[Citation],
    ) -> PricingAnalysis:
        pricing_items: list[PricingItem] = []
        pricing_models: list[PricingModel] = []
        default_citations = [item.id for item in citations[:3]]

        for item in result.get("pricing_comparison", []):
            competitor = str(item.get("competitor", "")).strip()
            if not competitor:
                continue
            model = str(item.get("pricing_model", "")).strip() or "未明确披露"
            free_tier = str(item.get("free_tier", "")).strip()
            paid_tier = str(item.get("paid_tier", "")).strip()
            citation_ids = self._competitor_citation_ids(evidence_bundles, competitor, "pricing_info", 3)
            entry_offer = self._build_entry_offer(free_tier, paid_tier)
            upgrade_trigger = self._build_upgrade_trigger(paid_tier or free_tier)
            billing_unit = self._infer_billing_unit(model, paid_tier)
            pricing_signal = self._build_pricing_signal(model, citation_ids)
            pricing_risk = self._build_pricing_risk(f"{free_tier} {paid_tier} {model}")
            pricing_items.append(
                PricingItem(
                    competitor=competitor,
                    free_tier=free_tier,
                    paid_tier=paid_tier,
                    pricing_model=model,
                    entry_offer=entry_offer,
                    upgrade_trigger=upgrade_trigger,
                    billing_unit=billing_unit,
                    pricing_signal=pricing_signal,
                    pricing_risk=pricing_risk,
                    citations=citation_ids or default_citations,
                )
            )
            pricing_models.append(
                PricingModel(
                    competitor=competitor,
                    model=model,
                    free_tier=free_tier,
                    paid_tier=paid_tier,
                    billing_basis=billing_unit,
                    entry_offer=entry_offer,
                    upgrade_trigger=upgrade_trigger,
                    pricing_signal=pricing_signal,
                    pricing_risk=pricing_risk,
                    citations=citation_ids or default_citations,
                )
            )

        strategy = str(result.get("pricing_strategy_analysis", "")).strip()
        summary = str(result.get("summary", "")).strip()
        value_ranking = [str(item).strip() for item in result.get("value_ranking", []) if str(item).strip()]
        conclusions = self._build_conclusions(strategy, summary, default_citations)
        return PricingAnalysis(
            pricing_comparison=pricing_items,
            pricing_strategy_analysis=strategy,
            value_ranking=value_ranking,
            pricing_models=pricing_models,
            conclusions=conclusions,
            citations=citations,
            message=MessageEnvelope(
                task_id=f"{product_name}:pricing",
                agent_role=self.agent_id,
                payload_type="pricing_analysis",
                payload={"comparison_count": len(pricing_items), "llm": True},
                citations=[citation.id for citation in citations],
            ),
            summary=summary or strategy,
        )

    def _rule_analyze(
        self,
        product_name: str,
        competitors_data: dict[str, CompetitorData],
        evidence_bundles: dict[str, list[EvidenceBundle]],
        citations: list[Citation],
    ) -> PricingAnalysis:
        items: list[PricingItem] = []
        models: list[PricingModel] = []
        for competitor, data in competitors_data.items():
            text = data.pricing_info
            model = self._guess_model(text)
            free_tier = self._extract_free_tier(text)
            paid_tier = self._extract_paid_tier(text)
            citation_ids = self._competitor_citation_ids(evidence_bundles, competitor, "pricing_info", 3)
            entry_offer = self._build_entry_offer(free_tier, paid_tier)
            upgrade_trigger = self._build_upgrade_trigger(paid_tier or text)
            billing_unit = self._infer_billing_unit(model, paid_tier)
            pricing_signal = self._build_pricing_signal(model, citation_ids)
            pricing_risk = self._build_pricing_risk(text)
            items.append(
                PricingItem(
                    competitor=competitor,
                    free_tier=free_tier,
                    paid_tier=paid_tier,
                    pricing_model=model,
                    entry_offer=entry_offer,
                    upgrade_trigger=upgrade_trigger,
                    billing_unit=billing_unit,
                    pricing_signal=pricing_signal,
                    pricing_risk=pricing_risk,
                    citations=citation_ids,
                )
            )
            models.append(
                PricingModel(
                    competitor=competitor,
                    model=model,
                    free_tier=free_tier,
                    paid_tier=paid_tier,
                    billing_basis=billing_unit,
                    entry_offer=entry_offer,
                    upgrade_trigger=upgrade_trigger,
                    pricing_signal=pricing_signal,
                    pricing_risk=pricing_risk,
                    citations=citation_ids,
                )
            )

        dominant = self._dominant_model(items)
        strategy = (
            f"从现有证据看，竞品主要采用 {dominant} 或混合计费。"
            "真正影响采购判断的是免费入口、升级触发点、计费单位和增购边界是否清楚。"
        )
        summary = self._build_summary(items, dominant)
        default_citations = [item.id for item in citations[:3]]
        return PricingAnalysis(
            pricing_comparison=items,
            pricing_strategy_analysis=strategy,
            value_ranking=[item.competitor for item in items],
            pricing_models=models,
            conclusions=self._build_conclusions(strategy, summary, default_citations),
            citations=citations,
            message=MessageEnvelope(
                task_id=f"{product_name}:pricing",
                agent_role=self.agent_id,
                payload_type="pricing_analysis",
                payload={"comparison_count": len(items), "llm": False},
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
            lines.append(f"- 定价信息: {data.pricing_info[:1200]}")
            lines.append(f"- 产品功能: {data.product_features[:400]}")
            lines.append(f"- 用户反馈: {data.user_reviews[:500]}")
            bundle_facts = []
            for bundle in evidence_bundles.get(name, []):
                if bundle.topic == "pricing_info":
                    bundle_facts.extend(bundle.key_facts[:4])
            if bundle_facts:
                lines.append(f"- 定价证据: {'；'.join(bundle_facts[:6])}")
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
    def _build_conclusions(strategy: str, summary: str, citations: list[str]) -> list[ConclusionItem]:
        statements = [strategy, summary]
        return [
            ConclusionItem(
                id=f"pricing:conclusion:{index}",
                dimension="pricing",
                statement=statement.split("。")[0][:160],
                citations=citations,
                confidence=0.74,
                evidence_topics=["pricing_info"],
            )
            for index, statement in enumerate(statements, start=1)
            if statement
        ]

    @staticmethod
    def _build_entry_offer(free_tier: str, paid_tier: str) -> str:
        if "免费" in free_tier:
            return "免费入口明确，适合先试后买。"
        if "试用" in free_tier:
            return "有试用入口，但需要讲清试用边界。"
        return f"进入门槛依赖付费说明：{paid_tier[:48] or '未明确'}"

    @staticmethod
    def _build_upgrade_trigger(text: str) -> str:
        if not text:
            return "升级触发点公开表达不够集中。"
        for token in ("企业版", "专业版", "席位", "用户", "用量", "AI", "存储", "安全", "私有化"):
            if token in text:
                return text[:72]
        return text[:72]

    @staticmethod
    def _infer_billing_unit(model: str, text: str) -> str:
        source = f"{model} {text}".lower()
        if any(token in source for token in ("seat", "席位", "用户", "账号")):
            return "seat"
        if any(token in source for token in ("usage", "按量", "调用", "token", "用量")):
            return "usage"
        if any(token in source for token in ("订阅", "包年", "月")):
            return "subscription"
        return "package"

    @staticmethod
    def _build_pricing_signal(model: str, citation_ids: list[str]) -> str:
        if citation_ids:
            return f"当前证据支持 {model} 判断，但关键价格仍建议优先核对官方页面。"
        return f"{model} 判断缺少高可信来源，需要补证据。"

    @staticmethod
    def _build_pricing_risk(text: str) -> str:
        for token in ("复杂", "不透明", "增购", "投诉", "退款", "推诿", "涨价", "限制"):
            if token in text:
                return text[:72]
        return ""

    @staticmethod
    def _guess_model(text: str) -> str:
        lowered = text.lower()
        if any(token in lowered for token in ("按量", "调用", "token", "usage")):
            return "按量付费"
        if any(token in lowered for token in ("席位", "seat", "用户数")):
            return "按席位订阅"
        if "免费" in text:
            return "免费增值"
        if any(token in text for token in ("订阅", "包年", "包月", "会员")):
            return "订阅制"
        return "未明确披露"

    @staticmethod
    def _extract_free_tier(text: str) -> str:
        if not text:
            return "未明确披露免费层。"
        for part in PricingAgent._split_sentences(text):
            if "免费" in part or "试用" in part:
                return part[:100]
        return "未明确披露免费层。"

    @staticmethod
    def _extract_paid_tier(text: str) -> str:
        if not text:
            return "公开付费层信息有限。"
        for part in PricingAgent._split_sentences(text):
            if any(token in part for token in ("元", "美元", "付费", "专业版", "企业版", "订阅", "收费")):
                return part[:140]
        return text[:140]

    @staticmethod
    def _dominant_model(items: list[PricingItem]) -> str:
        counts: dict[str, int] = {}
        for item in items:
            counts[item.pricing_model] = counts.get(item.pricing_model, 0) + 1
        return max(counts.items(), key=lambda item: item[1])[0] if counts else "未明确披露"

    @staticmethod
    def _build_summary(items: list[PricingItem], dominant: str) -> str:
        names = "、".join(item.competitor for item in items[:4])
        return (
            f"定价层面，{names or '主要竞品'} 的公开信息显示主流模式偏向 {dominant}。"
            "\n\n"
            "报告应重点解释免费入口、付费层级、升级触发点和计费单位，而不是只罗列价格。"
            "\n\n"
            "如果价格来自媒体或聚合页面，正式结论需要优先用官方价格页复核。"
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        import re

        return [part.strip() for part in re.split(r"[\n\r。！？!?；;]+", text or "") if part.strip()]

    @staticmethod
    def _collect_unique_citations(evidence_bundles: dict[str, list[EvidenceBundle]]) -> list[Citation]:
        seen: dict[str, Citation] = {}
        priority = {"official": 4, "media": 3, "community": 2, "complaint": 1, "aggregator": 0}
        for bundles in evidence_bundles.values():
            for bundle in bundles:
                for citation in bundle.citations:
                    seen.setdefault(citation.id, citation)
        return sorted(
            seen.values(),
            key=lambda item: (priority.get(item.source_quality, 0), item.confidence, item.title),
            reverse=True,
        )

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
        ]
        return list(dict.fromkeys(ids))[:limit]
