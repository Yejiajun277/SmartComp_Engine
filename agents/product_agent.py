# -*- coding: utf-8 -*-
"""
agents/product_agent.py - 产品分析 Agent
"""

from __future__ import annotations

from collections import defaultdict

from agents.base_agent import BaseAgent
from models.domain import (
    Citation,
    CompetitiveAdvantage,
    ConclusionItem,
    EvidenceBundle,
    FeatureComparison,
    FeatureNode,
    MessageEnvelope,
    ProductAnalysis,
)


FEATURE_KEYWORDS = {
    "AI 助手": ["ai", "智能", "助理", "copilot", "agent", "大模型"],
    "自动化工作流": ["workflow", "自动化", "流程", "审批", "编排"],
    "集成能力": ["integration", "集成", "api", "插件", "开放平台", "连接器"],
    "协作能力": ["协作", "共享", "团队", "多人", "文档", "会议"],
    "数据分析": ["分析", "报表", "dashboard", "洞察", "指标"],
}


class ProductAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            agent_id="ProductAgent",
            system_prompt="你负责基于结构化证据做产品能力对比分析。",
        )

    async def run(
        self,
        product_name: str,
        evidence_bundles: dict[str, list[EvidenceBundle]],
    ) -> ProductAnalysis:
        feature_matrix: list[FeatureComparison] = []
        feature_tree: list[FeatureNode] = []
        advantages: list[CompetitiveAdvantage] = []
        conclusions: list[ConclusionItem] = []
        citations = self._collect_unique_citations(evidence_bundles)

        product_text_map = {
            competitor: self._merge_bundle_text(bundles, "product_features")
            for competitor, bundles in evidence_bundles.items()
        }
        pricing_text_map = {
            competitor: self._merge_bundle_text(bundles, "pricing_info")
            for competitor, bundles in evidence_bundles.items()
        }

        feature_support_counts: dict[str, int] = defaultdict(int)
        for feature, keywords in FEATURE_KEYWORDS.items():
            values: dict[str, str] = {}
            feature_citations: list[str] = []
            supported: list[str] = []
            for competitor, bundles in evidence_bundles.items():
                bundle = self._find_bundle(bundles, "product_features")
                text = product_text_map.get(competitor, "").lower()
                has_feature = any(keyword in text for keyword in keywords)
                values[competitor] = "supported" if has_feature else "unknown"
                if has_feature:
                    supported.append(competitor)
                    feature_support_counts[feature] += 1
                if bundle:
                    feature_citations.extend(item.id for item in bundle.citations[:2])

            feature_matrix.append(
                FeatureComparison(
                    feature=feature,
                    values=values,
                    citations=self._dedupe(feature_citations),
                )
            )
            feature_tree.append(
                FeatureNode(
                    name=feature,
                    description=f"围绕 {feature} 的关键能力布局",
                    supported_competitors=supported,
                )
            )

        for competitor, bundles in evidence_bundles.items():
            product_bundle = self._find_bundle(bundles, "product_features")
            pricing_bundle = self._find_bundle(bundles, "pricing_info")
            review_bundle = self._find_bundle(bundles, "user_reviews")
            product_text = product_text_map.get(competitor, "")
            pricing_text = pricing_text_map.get(competitor, "")
            review_text = review_bundle.summary if review_bundle else ""
            competitor_focus = self._infer_competitor_focus(product_text, pricing_text)
            tradeoff = self._infer_competitor_tradeoff(review_text, product_text)
            citations_ids: list[str] = []
            if product_bundle:
                citations_ids.extend(item.id for item in product_bundle.citations[:2])
            if pricing_bundle:
                citations_ids.extend(item.id for item in pricing_bundle.citations[:1])
            if review_bundle:
                citations_ids.extend(item.id for item in review_bundle.citations[:1])
            advantages.append(
                CompetitiveAdvantage(
                    competitor=competitor,
                    our_advantage=f"{product_name} 应优先围绕 {competitor_focus} 做更聚焦、更易理解的能力表达。",
                    their_advantage=tradeoff,
                    citations=self._dedupe(citations_ids),
                )
            )

        top_features = [
            feature for feature, _ in sorted(feature_support_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        differentiation_points = [
            f"优先把 {top_features[0]} 做成可见卖点，并与真实业务场景绑定。"
            if top_features
            else "优先围绕高频核心能力建立清晰卖点。",
            f"把 {top_features[1]} 和集成能力一起包装成标准化方案。"
            if len(top_features) > 1
            else "把自动化与集成能力做成一体化方案。",
            "围绕用户反馈中反复出现的复杂、上手慢、成本高等问题做减法。",
        ]

        if top_features:
            conclusions.append(
                ConclusionItem(
                    id="product:conclusion:1",
                    dimension="product",
                    statement=f"主流竞品的能力重心集中在 {', '.join(top_features[:3])}，说明这是用户评估产品时最先比较的能力层。",
                    citations=[citation.id for citation in citations[:3]],
                    confidence=0.72,
                    evidence_topics=["product_features"],
                )
            )
        conclusions.append(
            ConclusionItem(
                id="product:conclusion:2",
                dimension="product",
                statement="差异化空间不在于再堆一个功能列表，而在于把自动化、集成与协作串成一条更短的交付路径。",
                citations=[citation.id for citation in citations[:3]],
                confidence=0.69,
                evidence_topics=["product_features", "pricing_info"],
            )
        )
        conclusions.append(
            ConclusionItem(
                id="product:conclusion:3",
                dimension="product",
                statement="如果继续沿用宽而平的能力叙述，报告能看到的将只是同质化竞争，很难形成可执行的产品抓手。",
                citations=[citation.id for citation in citations[1:4] or citations[:2]],
                confidence=0.65,
                evidence_topics=["product_features", "user_reviews"],
            )
        )

        message = MessageEnvelope(
            task_id=f"{product_name}:product",
            agent_role=self.agent_id,
            payload_type="product_analysis",
            payload={
                "feature_count": len(feature_matrix),
                "conclusion_count": len(conclusions),
                "top_features": top_features[:3],
            },
            citations=[citation.id for citation in citations],
        )
        summary = self._build_summary(top_features, feature_matrix, advantages)
        self._log(f"产品分析完成，功能维度={len(feature_matrix)}")
        return ProductAnalysis(
            feature_matrix=feature_matrix,
            competitive_advantages=advantages,
            differentiation_points=differentiation_points,
            feature_tree=feature_tree,
            conclusions=conclusions,
            citations=citations,
            message=message,
            summary=summary,
        )

    def _build_summary(
        self,
        top_features: list[str],
        feature_matrix: list[FeatureComparison],
        advantages: list[CompetitiveAdvantage],
    ) -> str:
        supported_lines = []
        for item in feature_matrix[:3]:
            supported = [name for name, value in item.values.items() if value == "supported"]
            if supported:
                supported_lines.append(f"{item.feature} 主要由 {', '.join(supported[:4])} 覆盖。")
        paragraph_1 = (
            f"从功能覆盖看，竞品对外表达最集中的能力是 {', '.join(top_features[:3]) or '协作与效率提升'}。"
            f"{' '.join(supported_lines[:2])}"
        )
        paragraph_2 = (
            "从差异化角度看，真正可被用户感知的不是单个功能点，而是是否能把集成、自动化与协作串成闭环。"
            "这意味着报告里需要强调可交付场景，而不是继续罗列能力名词。"
        )
        competitor_examples = " ".join(
            f"{item.competitor}：{item.their_advantage[:60]}。"
            for item in advantages[:2]
            if item.their_advantage
        )
        paragraph_3 = (
            "从主要短板看，现有竞品叙述普遍会暴露复杂、迁移成本高或能力分散的问题。"
            f"{competitor_examples}"
        )
        return "\n\n".join([paragraph_1, paragraph_2, paragraph_3])

    @staticmethod
    def _merge_bundle_text(bundles: list[EvidenceBundle], topic: str) -> str:
        return " ".join(bundle.summary for bundle in bundles if bundle.topic == topic)

    @staticmethod
    def _infer_competitor_focus(product_text: str, pricing_text: str) -> str:
        text = f"{product_text} {pricing_text}".lower()
        if any(token in text for token in ("api", "开放", "集成", "插件")):
            return "开放集成"
        if any(token in text for token in ("审批", "流程", "自动化", "workflow")):
            return "流程自动化"
        if any(token in text for token in ("ai", "智能", "copilot", "agent")):
            return "AI 提效"
        return "高频协作"

    @staticmethod
    def _infer_competitor_tradeoff(review_text: str, product_text: str) -> str:
        source = f"{review_text} {product_text}"
        if any(token in source for token in ("复杂", "门槛", "学习成本", "培训")):
            return "能力相对完整，但同时伴随较高的理解成本和落地门槛。"
        if any(token in source for token in ("生态", "集成", "开放")):
            return "生态与集成表达较强，容易在企业采购阶段获得加分。"
        if any(token in source for token in ("AI", "智能", "agent", "copilot")):
            return "AI 能力曝光度较高，更容易占据用户对新一代产品的心智。"
        return "基础能力覆盖较全，但差异化表达仍依赖具体场景包装。"

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
    def _dedupe(items: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in items if item))
