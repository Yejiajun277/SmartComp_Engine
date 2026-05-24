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
        max_rounds: int = 2,
    ) -> dict:
        issues: list[QAIssue] = []

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
