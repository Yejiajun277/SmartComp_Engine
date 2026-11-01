"""The last report layer cannot replace qualified evidence with new claims."""
import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

from agents.quality_agent import QualityAgent
from agents.strategy_agent import StrategyAgent
from models.domain import (Citation, CompetitorData, FeatureComparison, FeatureItem,
                           MarketAnalysis, MarketShareItem, PricingAnalysis, PricingItem,
                           PricingTier, ProductAnalysis, StrategyReport, UserReputation, UserProfile)


class FinalReportScopeTests(unittest.IsolatedAsyncioTestCase):
    def inputs(self):
        cite = Citation(id="Target:q0:r0", title="Public specification", url="https://example.test/spec")
        target = CompetitorData("Target", product_features=[FeatureItem(
            "Filtering", "Only edition A has this filter; edition B does not.", [cite.id])],
            pricing_tiers=[PricingTier("Edition A, 2025, region R", "100 per unit",
                                      ["condition " + str(i) for i in range(8)], [cite.id])],
            strengths="A qualified description.", citations=[cite])
        product = ProductAnalysis(feature_matrix=[FeatureComparison("Filtering", {
            "Target": target.product_features[0].description, "Rival": "Unknown"})],
            summary="x" * 350 + " Only edition A, region R, measured in lab mode.")
        pricing = PricingAnalysis(summary="No common quote basis; no value ranking.")
        market = MarketAnalysis(summary="Unknown share; no public rating.")
        return target, product, pricing, market

    async def test_model_cannot_replace_section_summaries_or_target_scope(self):
        target, product, pricing, market = self.inputs()
        agent = StrategyAgent()
        result = {"product_analysis_summary": "Every edition has the filter",
                  "pricing_analysis_summary": "Target is the best value",
                  "market_analysis_summary": "Target has 47% share",
                  "target_product_intro": {"hero_summary": "Every edition has the filter",
                    "core_capabilities": [{"title": "Filtering", "summary": "All editions"}]}}
        with patch("config.ENABLE_LLM", True), \
                patch.object(agent, "_needs_target_intro_supplement", return_value=False), \
                patch.object(agent, "async_ask_llm_json_with_truncation_check",
                             AsyncMock(return_value=(result, False))):
            report = await agent.run("Target", 1, product, pricing, market, target)
        self.assertEqual(report.product_analysis_summary, product.summary)
        self.assertEqual(report.pricing_analysis_summary, pricing.summary)
        self.assertEqual(report.market_analysis_summary, market.summary)
        self.assertEqual(report.target_product_intro.core_capabilities[0].summary,
                         target.product_features[0].description)
        self.assertIn("condition 7", report.target_product_intro.monetization[0].summary)
        self.assertEqual(report.target_product_intro.core_capabilities[0].citations, ["Target:q0:r0"])

    async def test_rule_path_preserves_qualification_tail(self):
        target, product, pricing, market = self.inputs()
        with patch("config.ENABLE_LLM", False):
            report = await StrategyAgent().run("Target", 1, product, pricing, market, target)
        self.assertEqual(report.product_analysis_summary, product.summary)
        self.assertIn("condition 7", report.target_product_intro.monetization[0].summary)

    def test_strategy_context_includes_each_matrix_cell_and_all_entities(self):
        _, product, pricing, market = self.inputs()
        for index in range(7):
            pricing.pricing_comparison.append(PricingItem("Entity" + str(index), paid_tier="Scope" + str(index)))
            market.market_share_data.append(MarketShareItem("Entity" + str(index), "Unknown" + str(index)))
        market.user_reputation["Entity6"] = UserReputation(
            source_text="Review applies only to Region R edition A, not the entire range.")
        market.user_profiles["Entity6"] = UserProfile(target_audience="Specific reviewed segment only")
        text = StrategyAgent()._build_analysis_text("Target", product, pricing, market)
        self.assertIn("edition B does not", text)
        self.assertIn("Scope6", text)
        self.assertIn("Unknown6", text)
        self.assertIn(market.user_reputation["Entity6"].source_text, text)
        self.assertIn(market.user_profiles["Entity6"].target_audience, text)

    def test_render_uses_supplied_analysis_without_mutating_saved_report(self):
        _, product, pricing, market = self.inputs()
        report = StrategyReport("Target", product_analysis_summary="UNQUALIFIED_CLAIM")
        before = copy.deepcopy(report)
        markup = StrategyAgent().format_html_report(report, product, pricing, market)
        self.assertNotIn("UNQUALIFIED_CLAIM", markup)
        self.assertIn("Only edition A, region R", markup)
        self.assertEqual(report, before)

    def test_years_denials_and_unknown_values_do_not_become_share_bars(self):
        market = MarketAnalysis(market_share_data=[
            MarketShareItem("Unknown scope", "As of 2025: no share disclosed; 47% belongs to an unidentified entity."),
            MarketShareItem("Explicit percentage", "25%"),
            MarketShareItem("No evidence", "Unknown"),
            MarketShareItem("Invalid ratio", "101%"),
        ])
        markup = StrategyAgent().format_html_report(StrategyReport("Target"), market_analysis=market)
        self.assertIn("As of 2025: no share disclosed", markup)
        self.assertEqual(markup.count('data-market-share-value='), 1)
        self.assertIn('data-market-share-value="25.0"', markup)
        self.assertIn("width:25.0%", markup)

    def test_unknown_or_denied_trends_do_not_become_directional_claims(self):
        for trend in ("未知", "无公开证据表明增长", "增长尚不能确认"):
            with self.subTest(trend=trend):
                market = MarketAnalysis(market_share_data=[MarketShareItem("Rival", "未知", trend)])
                markup = StrategyAgent().format_html_report(StrategyReport("Target"), market_analysis=market)
                self.assertIn(trend, markup)
                for false_claim in ("↗ 上升", "→ 稳定", "↘ 下降"):
                    self.assertNotIn(false_claim, markup)

    def test_comparison_card_uses_authoritative_full_target_share_and_trend(self):
        target, product, _, _ = self.inputs()
        target.market_share = "LEGACY_COLLECTION_SHARE"
        scoped_share = "x" * 180 + " Applies only to edition A in region R."
        market = MarketAnalysis(market_share_data=[
            MarketShareItem("Target", scoped_share, "未知"),
            MarketShareItem("Rival", "Unknown", "未知"),
        ])
        markup = StrategyAgent().format_html_report(
            StrategyReport("Target", target_product_data=target), product_analysis=product,
            market_analysis=market)
        # One occurrence in the per-rival comparison, one in the market section.
        self.assertEqual(markup.count(scoped_share), 2)
        self.assertNotIn("↗ 上升", markup)
        self.assertNotIn("→ 稳定", markup)


class ReviewFailureDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_finish_keeps_known_transport_failure_in_review_record(self):
        agent = QualityAgent()
        async def adapter(*args, **kwargs):
            agent.llm_logs.append({"finish_reason": "", "success": False})
            return {}, "api_error(timeout)"
        with patch.object(agent, "async_ask_llm_json_with_reason", adapter):
            result, reason = await agent._request_quality_json("check")
        self.assertFalse(result)
        self.assertIn("api_error(timeout)", reason)
        for request in agent._last_quality_request_trace["requests"]:
            self.assertIn("api_error(timeout)", request["failure_reason"])

    def test_no_common_quote_basis_does_not_demand_a_fabricated_ranking(self):
        agent = QualityAgent()
        pricing = PricingAnalysis(pricing_comparison=[PricingItem("Rival", paid_tier="100, unknown region")],
                                  summary="No comparable quote basis")
        issues = agent._check_analysis_completeness("pricing", pricing, {"Rival": CompetitorData("Rival")})
        self.assertNotIn("value_ranking", [issue.field for issue in issues])
        pricing.comparable_basis = {"Rival": {"unit": "per unit"}}
        issues = agent._check_analysis_completeness("pricing", pricing, {"Rival": CompetitorData("Rival")})
        self.assertIn("value_ranking", [issue.field for issue in issues])


if __name__ == "__main__":
    unittest.main()
