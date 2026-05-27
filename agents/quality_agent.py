# -*- coding: utf-8 -*-
"""
agents/quality_agent.py - 质检 Agent
"""

from __future__ import annotations

import re
from typing import Any

from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from models.domain import (
    EvidenceBundle,
    MarketAnalysis,
    PricingAnalysis,
    ProductAnalysis,
    QAIssue,
    ResearchCoverage,
)


class QualityAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("quality_agent")
        super().__init__(
            agent_id="QualityAgent",
            system_prompt=prompts["system_prompt"],
        )

    async def run(
        self,
        product_analysis: ProductAnalysis | None,
        pricing_analysis: PricingAnalysis | None,
        market_analysis: MarketAnalysis | None,
        coverage: ResearchCoverage | None,
        qa_round: int,
        product_name: str = "",
        competitor_count: int = 0,
        competitor_names: list[str] | None = None,
        evidence_bundles: dict[str, list[EvidenceBundle]] | None = None,
        max_rounds: int = 2,
    ) -> dict:
        issues: list[QAIssue] = []
        allowed_competitors = set(competitor_names or [])
        citation_ids = self._known_citation_ids(evidence_bundles or {})

        if competitor_count < 3:
            issues.append(
                QAIssue(
                    issue_type="insufficient_competitors",
                    severity="high",
                    target_agent="DiscoveryAgent",
                    reason=f"竞品数量不足，当前仅 {competitor_count} 个，报告容易退化成单点对比。",
                    required_fix="补充到至少 3 个核心竞品后再生成正式报告。",
                    related_ids=["competitor_list"],
                )
            )

        if product_analysis is None or not product_analysis.feature_tree:
            issues.append(
                QAIssue(
                    issue_type="missing_feature_tree",
                    severity="high",
                    target_agent="ProductAgent",
                    reason="缺少 FeatureTree。",
                    required_fix="补全功能树并给每个核心结论挂 citation。",
                    related_ids=["product:feature_tree"],
                )
            )

        if product_analysis is not None:
            if len(product_analysis.feature_matrix) < 8:
                issues.append(
                    QAIssue(
                        issue_type="thin_feature_matrix",
                        severity="high",
                        target_agent="ProductAgent",
                        reason=f"功能矩阵维度不足，当前仅 {len(product_analysis.feature_matrix)} 个。",
                        required_fix="动态提炼 8-15 个行业相关功能维度，恢复旧报告的信息密度。",
                        related_ids=["product:feature_matrix"],
                    )
                )
            issues.extend(
                self._unknown_product_outputs(
                    product_analysis,
                    allowed_competitors,
                    product_name,
                )
            )
            if product_name and not any(
                product_name in item.values or any(product_name in key for key in item.values)
                for item in product_analysis.feature_matrix
            ):
                issues.append(
                    QAIssue(
                        issue_type="missing_own_product_matrix",
                        severity="high",
                        target_agent="ProductAgent",
                        reason=f"功能矩阵缺少我方产品 {product_name}。",
                        required_fix="feature_matrix.values 必须包含我方产品和所有竞品。",
                        related_ids=["product:feature_matrix"],
                    )
                )

        if pricing_analysis is None or not pricing_analysis.pricing_models:
            issues.append(
                QAIssue(
                    issue_type="missing_pricing_model",
                    severity="high",
                    target_agent="PricingAgent",
                    reason="缺少 PricingModel。",
                    required_fix="补全定价模型并给每个核心结论挂 citation。",
                    related_ids=["pricing:pricing_model"],
                )
            )
        elif allowed_competitors:
            issues.extend(
                self._unknown_competitor_items(
                    "pricing",
                    "PricingAgent",
                    pricing_analysis.pricing_comparison + pricing_analysis.pricing_models,
                    allowed_competitors,
                )
            )

        if market_analysis is None or not market_analysis.user_personas:
            issues.append(
                QAIssue(
                    issue_type="missing_user_persona",
                    severity="high",
                    target_agent="MarketAgent",
                    reason="缺少 UserPersona。",
                    required_fix="补全用户画像并给每个核心结论挂 citation。",
                    related_ids=["market:user_persona"],
                )
            )
        elif allowed_competitors:
            issues.extend(
                self._unknown_competitor_items(
                    "market",
                    "MarketAgent",
                    market_analysis.market_share_data,
                    allowed_competitors,
                )
            )
            unknown_reputation = set(market_analysis.user_reputation) - allowed_competitors
            for name in sorted(unknown_reputation):
                issues.append(
                    QAIssue(
                        issue_type="unknown_competitor_output",
                        severity="high",
                        target_agent="MarketAgent",
                        reason=f"市场分析输出了不在竞品列表中的对象：{name}。",
                        required_fix="分析结果只能包含竞品列表中的竞品；我方产品不得混入竞品市场行。",
                        related_ids=[f"market:{name}"],
                    )
                )

        for dimension, analysis, agent_name in (
            ("product", product_analysis, "ProductAgent"),
            ("pricing", pricing_analysis, "PricingAgent"),
            ("market", market_analysis, "MarketAgent"),
        ):
            if analysis is None:
                continue
            for item in analysis.conclusions:
                if not item.citations:
                    issues.append(
                        QAIssue(
                            issue_type="missing_citation",
                            severity="high",
                            target_agent=agent_name,
                            reason=f"{dimension} 维度存在未挂 citation 的核心结论。",
                            required_fix="为每条核心结论补充至少 1 个 citation。",
                            related_ids=[item.id],
                        )
                    )
                elif citation_ids and any(citation_id not in citation_ids for citation_id in item.citations):
                    issues.append(
                        QAIssue(
                            issue_type="unknown_citation",
                            severity="high",
                            target_agent=agent_name,
                            reason=f"{dimension} 维度存在无法回溯到 evidence_bundles 的 citation。",
                            required_fix="删除无效 citation，或重新采集对应证据。",
                            related_ids=[item.id],
                        )
                    )

        issues.extend(self._citation_scope_issues(product_analysis, pricing_analysis, market_analysis))

        if coverage:
            for gap in coverage.coverage_gaps:
                issues.append(
                    QAIssue(
                        issue_type="coverage_gap",
                        severity="medium",
                        target_agent="CollectionAgent",
                        reason=f"{gap.competitor} 在 {gap.topic} 缺少完整证据。",
                        required_fix="重新采集该主题证据，或显式保留缺口说明。",
                        related_ids=[f"{gap.competitor}:{gap.topic}"],
                    )
                )

        action = "pass"
        if issues:
            if qa_round >= max_rounds:
                action = "pass"
            elif any(issue.target_agent == "CollectionAgent" for issue in issues):
                action = "redo_collection"
            else:
                action = "redo_analysis"

        self._log(f"质检完成，发现问题 {len(issues)} 个，动作={action}")
        return {
            "issues": issues,
            "next_action": action,
        }

    @staticmethod
    def _known_citation_ids(evidence_bundles: dict[str, list[EvidenceBundle]]) -> set[str]:
        return {
            citation.id
            for bundles in evidence_bundles.values()
            for bundle in bundles
            for citation in bundle.citations
            if citation.id
        }

    @staticmethod
    def _unknown_product_outputs(
        product_analysis: ProductAnalysis,
        allowed_competitors: set[str],
        product_name: str,
    ) -> list[QAIssue]:
        if not allowed_competitors:
            return []
        allowed_matrix_keys = allowed_competitors | ({product_name} if product_name else set())
        issues: list[QAIssue] = []
        for feature in product_analysis.feature_matrix:
            unknown_keys = set(feature.values) - allowed_matrix_keys
            unknown_citation_keys = set(feature.competitor_citations) - allowed_competitors
            for name in sorted(unknown_keys | unknown_citation_keys):
                issues.append(
                    QAIssue(
                        issue_type="unknown_competitor_output",
                        severity="high",
                        target_agent="ProductAgent",
                        reason=f"功能矩阵输出了不在竞品列表中的对象：{name}。",
                        required_fix="feature_matrix 只能包含我方产品列和竞品列表中的竞品列。",
                        related_ids=[f"product:{feature.feature}:{name}"],
                    )
                )
        for item in product_analysis.competitive_advantages:
            if item.competitor not in allowed_competitors:
                issues.append(
                    QAIssue(
                        issue_type="unknown_competitor_output",
                        severity="high",
                        target_agent="ProductAgent",
                        reason=f"竞品优劣分析输出了不在竞品列表中的对象：{item.competitor}。",
                        required_fix="逐竞品分析只能包含竞品列表中的竞品。",
                        related_ids=[f"product:{item.competitor}"],
                    )
                )
        return issues

    @staticmethod
    def _unknown_competitor_items(
        dimension: str,
        target_agent: str,
        items: list[Any],
        allowed_competitors: set[str],
    ) -> list[QAIssue]:
        issues: list[QAIssue] = []
        for item in items:
            competitor = getattr(item, "competitor", "")
            if competitor and competitor not in allowed_competitors:
                issues.append(
                    QAIssue(
                        issue_type="unknown_competitor_output",
                        severity="high",
                        target_agent=target_agent,
                        reason=f"{dimension} 分析输出了不在竞品列表中的对象：{competitor}。",
                        required_fix="分析结果只能包含竞品列表中的竞品。",
                        related_ids=[f"{dimension}:{competitor}"],
                    )
                )
        return issues

    @staticmethod
    def _citation_scope_issues(
        product_analysis: ProductAnalysis | None,
        pricing_analysis: PricingAnalysis | None,
        market_analysis: MarketAnalysis | None,
    ) -> list[QAIssue]:
        issues: list[QAIssue] = []
        if product_analysis is not None:
            for feature in product_analysis.feature_matrix:
                for competitor, citations in feature.competitor_citations.items():
                    if any(not QualityAgent._citation_matches_competitor(citation_id, competitor) for citation_id in citations):
                        issues.append(
                            QAIssue(
                                issue_type="citation_mismatch",
                                severity="high",
                                target_agent="ProductAgent",
                                reason=f"{competitor} 的功能矩阵 citation 未指向该竞品。",
                                required_fix="功能矩阵每个竞品单元格只能挂该竞品的 product_features 证据。",
                                related_ids=[f"{competitor}:product_features"],
                            )
                        )
        if pricing_analysis is not None:
            for item in pricing_analysis.pricing_comparison + pricing_analysis.pricing_models:
                if any(not QualityAgent._citation_matches_competitor(citation_id, item.competitor) for citation_id in item.citations):
                    issues.append(
                        QAIssue(
                            issue_type="citation_mismatch",
                            severity="high",
                            target_agent="PricingAgent",
                            reason=f"{item.competitor} 的定价 citation 未指向该竞品。",
                            required_fix="定价项只能挂该竞品的 pricing_info 证据。",
                            related_ids=[f"{item.competitor}:pricing_info"],
                        )
                    )
        if market_analysis is not None:
            for item in market_analysis.market_share_data:
                if any(not QualityAgent._citation_matches_competitor(citation_id, item.competitor) for citation_id in item.citations):
                    issues.append(
                        QAIssue(
                            issue_type="citation_mismatch",
                            severity="high",
                            target_agent="MarketAgent",
                            reason=f"{item.competitor} 的市场 citation 未指向该竞品。",
                            required_fix="市场项只能挂该竞品的 market_share/channels/user_reviews 证据。",
                            related_ids=[f"{item.competitor}:market_share"],
                        )
                    )
        return issues

    @staticmethod
    def _citation_matches_competitor(citation_id: str, competitor: str) -> bool:
        if not citation_id or not competitor:
            return False
        prefix = citation_id.split(":", 1)[0]
        return prefix == competitor
