# -*- coding: utf-8 -*-
"""
agents/quality_agent.py - 质检 Agent
"""

from __future__ import annotations

from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from models.domain import (
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
        max_rounds: int = 2,
    ) -> dict:
        issues: list[QAIssue] = []

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
