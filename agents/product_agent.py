# -*- coding: utf-8 -*-
"""
agents/product_agent.py - 产品分析 Agent
"""

from __future__ import annotations

from collections import defaultdict

import config
from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from models.domain import (
    Citation,
    CompetitorData,
    CompetitiveAdvantage,
    ConclusionItem,
    EvidenceBundle,
    FeatureComparison,
    FeatureNode,
    MessageEnvelope,
    ProductAnalysis,
)


FALLBACK_FEATURE_KEYWORDS = {
    "AI 助手": ["ai", "智能", "助理", "copilot", "agent", "大模型"],
    "自动化工作流": ["workflow", "自动化", "流程", "审批", "编排"],
    "集成能力": ["integration", "集成", "api", "插件", "开放平台", "连接器", "webhook"],
    "协作能力": ["协作", "共享", "团队", "多人", "文档", "会议"],
    "数据分析": ["分析", "报表", "dashboard", "洞察", "指标", "表格"],
    "移动端体验": ["移动", "app", "手机", "小程序"],
    "安全与权限": ["安全", "权限", "合规", "审计", "私有化"],
    "生态与插件": ["生态", "插件", "市场", "伙伴", "开放"],
}


class ProductAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("product_agent")
        super().__init__(
            agent_id="ProductAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(
        self,
        product_name: str,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        competitors_data: dict[str, CompetitorData] | None = None,
    ) -> ProductAnalysis:
        competitors_data = competitors_data or self._build_competitors_data(evidence_bundles)
        citations = self._collect_unique_citations(evidence_bundles)

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=self._build_competitors_text(competitors_data, evidence_bundles),
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                analysis = self._parse_product_analysis(product_name, result, evidence_bundles, citations)
                if analysis.feature_matrix:
                    self._log(
                        f"产品 LLM 分析完成，功能维度={len(analysis.feature_matrix)}，"
                        f"优势项={len(analysis.competitive_advantages)}"
                    )
                    return analysis
            self._log("产品 LLM 分析失败，降级到规则引擎")

        analysis = self._rule_analyze(product_name, evidence_bundles, competitors_data, citations)
        self._log(f"产品规则分析完成，功能维度={len(analysis.feature_matrix)}")
        return analysis

    def _parse_product_analysis(
        self,
        product_name: str,
        result: dict,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        citations: list[Citation],
    ) -> ProductAnalysis:
        competitor_names = list(evidence_bundles)
        feature_matrix: list[FeatureComparison] = []
        feature_tree: list[FeatureNode] = []

        for index, item in enumerate(result.get("feature_matrix", [])[:15], start=1):
            feature = str(item.get("feature", "")).strip()
            values = item.get("values", {}) if isinstance(item.get("values"), dict) else {}
            if not feature:
                continue
            normalized_values = {
                name: self._normalize_support_value(values.get(name, values.get(str(name), "")))
                for name in [product_name, *competitor_names]
            }
            if not normalized_values.get(product_name):
                normalized_values[product_name] = self._infer_product_value(feature, values)
            competitor_citations = self._feature_competitor_citations(
                evidence_bundles,
                normalized_values,
                topic="product_features",
                limit_per_competitor=2,
            )
            citation_ids = self._collect_feature_citations(competitor_citations, limit=4)
            feature_matrix.append(
                FeatureComparison(
                    feature=feature,
                    values=normalized_values,
                    citations=citation_ids,
                    competitor_citations=competitor_citations,
                )
            )
            feature_tree.append(
                FeatureNode(
                    name=feature,
                    description=f"围绕 {feature} 的关键能力布局",
                    supported_competitors=[
                        name for name, value in normalized_values.items() if value in {"✅", "支持", "supported"}
                    ],
                )
            )
            if index >= 15:
                break

        advantages: list[CompetitiveAdvantage] = []
        for item in result.get("competitive_advantages", []):
            competitor = str(item.get("competitor", "")).strip()
            if not competitor:
                continue
            citation_ids = self._competitor_citation_ids(evidence_bundles, competitor, limit=4)
            advantages.append(
                CompetitiveAdvantage(
                    competitor=competitor,
                    our_advantage=self._trim(str(item.get("our_advantage", "")).strip(), 120),
                    their_advantage=self._trim(str(item.get("their_advantage", "")).strip(), 120),
                    their_strength=self._trim(str(item.get("their_strength", item.get("their_advantage", ""))).strip(), 76),
                    their_weakness=self._trim(str(item.get("their_weakness", "")).strip(), 120),
                    recommended_countermove=self._trim(str(item.get("recommended_countermove", "")).strip(), 120),
                    citations=citation_ids,
                )
            )

        differentiation_points = [
            str(item).strip() for item in result.get("differentiation_points", []) if str(item).strip()
        ][:5]
        summary = str(result.get("summary", "")).strip()
        default_citations = [item.id for item in citations[:3]]
        conclusions = self._build_conclusions(
            summary=summary,
            points=differentiation_points,
            citations=default_citations,
        )
        return ProductAnalysis(
            feature_matrix=feature_matrix,
            competitive_advantages=advantages,
            differentiation_points=differentiation_points,
            feature_tree=feature_tree,
            conclusions=conclusions,
            citations=citations,
            message=MessageEnvelope(
                task_id=f"{product_name}:product",
                agent_role=self.agent_id,
                payload_type="product_analysis",
                payload={
                    "feature_count": len(feature_matrix),
                    "conclusion_count": len(conclusions),
                    "llm": True,
                },
                citations=[citation.id for citation in citations],
            ),
            summary=summary or self._build_summary(feature_matrix, advantages, differentiation_points),
        )

    def _rule_analyze(
        self,
        product_name: str,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        competitors_data: dict[str, CompetitorData],
        citations: list[Citation],
    ) -> ProductAnalysis:
        competitor_names = list(competitors_data)
        feature_matrix: list[FeatureComparison] = []
        feature_tree: list[FeatureNode] = []
        feature_support_counts: dict[str, int] = defaultdict(int)

        for feature, keywords in FALLBACK_FEATURE_KEYWORDS.items():
            values: dict[str, str] = {product_name: "🔶"}
            competitor_citations: dict[str, list[str]] = {}
            supported: list[str] = []
            for competitor in competitor_names:
                data = competitors_data[competitor]
                text = f"{data.product_features} {data.strengths} {data.channels}".lower()
                hit_count = sum(1 for keyword in keywords if keyword.lower() in text)
                value = "✅" if hit_count >= 2 else "🔶" if hit_count == 1 else "❌"
                values[competitor] = value
                if value == "✅":
                    supported.append(competitor)
                    feature_support_counts[feature] += 1
                competitor_citations[competitor] = self._competitor_citation_ids(
                    evidence_bundles,
                    competitor,
                    "product_features",
                    2,
                )

            feature_matrix.append(
                FeatureComparison(
                    feature=feature,
                    values=values,
                    citations=self._collect_feature_citations(competitor_citations, limit=4),
                    competitor_citations=competitor_citations,
                )
            )
            feature_tree.append(
                FeatureNode(
                    name=feature,
                    description=f"围绕 {feature} 的关键能力布局",
                    supported_competitors=supported,
                )
            )

        advantages = [
            CompetitiveAdvantage(
                competitor=name,
                our_advantage=f"{product_name} 应围绕高频场景给出更清晰的交付结果。",
                their_advantage=self._trim(data.strengths or "对方已有公开能力表达。", 120),
                their_strength=self._trim(data.strengths or "对方已有公开能力表达。", 76),
                their_weakness=self._trim(data.weaknesses, 120),
                recommended_countermove="优先用场景结果对冲单点功能对比。",
                citations=self._competitor_citation_ids(evidence_bundles, name, limit=4),
            )
            for name, data in competitors_data.items()
        ]
        top_features = [
            feature for feature, _ in sorted(feature_support_counts.items(), key=lambda item: (-item[1], item[0]))
        ][:3]
        points = [
            f"优先把 {top_features[0]} 做成可见卖点，并与真实业务场景绑定。"
            if top_features
            else "优先围绕高频核心能力建立清晰卖点。",
            f"把 {top_features[1]} 和集成能力一起包装成标准化方案。"
            if len(top_features) > 1
            else "把自动化与集成能力做成一体化方案。",
            "围绕用户反馈中反复出现的复杂、上手慢、成本高等问题做减法。",
        ]
        default_citations = [item.id for item in citations[:3]]
        summary = self._build_summary(feature_matrix, advantages, points)
        return ProductAnalysis(
            feature_matrix=feature_matrix,
            competitive_advantages=advantages,
            differentiation_points=points,
            feature_tree=feature_tree,
            conclusions=self._build_conclusions(summary, points, default_citations),
            citations=citations,
            message=MessageEnvelope(
                task_id=f"{product_name}:product",
                agent_role=self.agent_id,
                payload_type="product_analysis",
                payload={"feature_count": len(feature_matrix), "llm": False},
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
            lines.append(f"- 产品功能: {data.product_features[:900]}")
            lines.append(f"- 优势: {data.strengths[:400]}")
            lines.append(f"- 劣势: {data.weaknesses[:400]}")
            lines.append(f"- 定价: {data.pricing_info[:500]}")
            lines.append(f"- 市场/渠道: {(data.market_share + ' ' + data.channels)[:700]}")
            bundle_facts = []
            for bundle in evidence_bundles.get(name, []):
                bundle_facts.extend(bundle.key_facts[:2])
            if bundle_facts:
                lines.append(f"- 关键证据: {'；'.join(bundle_facts[:6])}")
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
                strengths="；".join(fact for bundle in bundles for fact in bundle.key_facts[:1])[:400],
                weaknesses="；".join(fact for bundle in bundles for fact in bundle.evidence_quotes[:1])[:400],
                search_sources=[citation.url for bundle in bundles for citation in bundle.citations if citation.url],
            )
        return data

    @staticmethod
    def _normalize_support_value(value: object) -> str:
        text = str(value or "").strip()
        if text in {"✅", "✓", "有", "支持", "完整支持", "supported"}:
            return "✅"
        if text in {"🔶", "△", "部分", "部分支持", "partial"}:
            return "🔶"
        if text in {"❌", "✗", "无", "不支持", "unknown", "unsupported"}:
            return "❌"
        return text[:24] if text else ""

    @staticmethod
    def _infer_product_value(feature: str, values: dict) -> str:
        text = f"{feature} {' '.join(str(item) for item in values.values())}"
        if any(token in text for token in ("独有", "领先", "优势", "强", "完整")):
            return "✅"
        return "🔶"

    @staticmethod
    def _build_conclusions(summary: str, points: list[str], citations: list[str]) -> list[ConclusionItem]:
        items: list[ConclusionItem] = []
        if summary:
            items.append(
                ConclusionItem(
                    id="product:conclusion:1",
                    dimension="product",
                    statement=summary.split("。")[0][:160],
                    citations=citations,
                    confidence=0.78,
                    evidence_topics=["product_features"],
                )
            )
        for index, point in enumerate(points[:2], start=2):
            items.append(
                ConclusionItem(
                    id=f"product:conclusion:{index}",
                    dimension="product",
                    statement=point,
                    citations=citations,
                    confidence=0.72,
                    evidence_topics=["product_features", "user_reviews"],
                )
            )
        return items

    @staticmethod
    def _build_summary(
        feature_matrix: list[FeatureComparison],
        advantages: list[CompetitiveAdvantage],
        points: list[str],
    ) -> str:
        feature_names = "、".join(item.feature for item in feature_matrix[:5])
        adv_text = "；".join(
            f"{item.competitor}: {item.our_advantage or item.their_advantage}" for item in advantages[:3]
        )
        point_text = "；".join(points[:3])
        return "\n\n".join(
            [
                f"产品层面的核心对比维度集中在 {feature_names}。",
                f"逐竞品看，{adv_text}。",
                f"差异化上应优先落到 {point_text}。",
            ]
        )

    @staticmethod
    def _collect_unique_citations(evidence_bundles: dict[str, list[EvidenceBundle]]) -> list[Citation]:
        seen: dict[str, Citation] = {}
        priority = {
            "official": 5,
            "media": 4,
            "community": 3,
            "complaint": 2,
            "aggregator": 1,
            "low_quality": 0,
        }
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
    def _topic_citation_ids(
        evidence_bundles: dict[str, list[EvidenceBundle]],
        topic: str,
        limit: int = 3,
    ) -> list[str]:
        ids = [
            citation.id
            for bundles in evidence_bundles.values()
            for bundle in bundles
            if bundle.topic == topic
            for citation in bundle.citations
        ]
        return ProductAgent._dedupe(ids)[:limit]

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
        return ProductAgent._dedupe(ids)[:limit]

    @staticmethod
    def _feature_competitor_citations(
        evidence_bundles: dict[str, list[EvidenceBundle]],
        values: dict[str, str],
        topic: str,
        limit_per_competitor: int = 2,
    ) -> dict[str, list[str]]:
        competitor_citations: dict[str, list[str]] = {}
        for competitor, value in values.items():
            if not str(value or "").strip():
                continue
            competitor_citations[competitor] = ProductAgent._competitor_citation_ids(
                evidence_bundles,
                competitor,
                topic=topic,
                limit=limit_per_competitor,
            )
        return competitor_citations

    @staticmethod
    def _collect_feature_citations(
        competitor_citations: dict[str, list[str]],
        limit: int = 4,
    ) -> list[str]:
        ids: list[str] = []
        for citation_ids in competitor_citations.values():
            ids.extend(citation_ids)
        return ProductAgent._dedupe(ids)[:limit]

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in items if item))

    @staticmethod
    def _trim(text: str, max_len: int) -> str:
        compact = " ".join((text or "").split())
        if len(compact) <= max_len:
            return compact
        return compact[:max_len].rstrip("，,；;：:") + "..."
