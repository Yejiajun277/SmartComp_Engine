"""Product conclusions retain the exact entity/SKU/region of collected facts."""
import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from agents.product_agent import ProductAgent
from agents.strategy_agent import StrategyAgent
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier, ProductAnalysis, FeatureComparison, CompetitiveAdvantage, StrategyReport


class ProductScopeIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.target = CompetitorData("Orion", product_features=[
            FeatureItem("Sealed filter", "Orion Elite, EU 2025 only: H13 sealed filter. Other versions unknown.", ["o1"])
        ], citations=[Citation("o1", "Orion specification", "https://example.test/o", "Elite EU 2025 H13")])
        self.rival = CompetitorData("Nova A/B", product_features=[
            FeatureItem("Interaction", "Nova B, Taiwan: no display; LED illumination remains available.", ["n1"])
        ], pricing_tiers=[PricingTier("Nova A, Taiwan", "$100", ["Display and automatic detection supported"], ["n1"])],
            citations=[Citation("n1", "Nova comparison", "https://example.test/n", "A display; B no display")])
        self.dims = "1. **Filtration**: sealed filter\n2. **Interaction**: display, detection, and convenience"

    def payload(self):
        return {
            "feature_matrix": [
                {"feature": "Filtration", "values": {"Orion": "✅", "Nova A/B": "⚪"},
                 "evidence": {"Orion": ["product_features[0]"]}},
                {"feature": "Interaction", "values": {"Orion": "⚪", "Nova A/B": "❌"},
                 "evidence": {"Nova A/B": ["product_features[0]", "pricing_tiers[0].features[0]"]}},
            ],
            "competitive_advantages": [{"competitor": "Nova A/B", "our_advantage": "ALL Orion versions have H13",
                "their_advantage": "ALL Nova versions lack interaction", "our_evidence": ["product_features[0]"],
                "their_evidence": ["product_features[0]", "pricing_tiers[0].features[0]"]}],
            "differentiation_points": [{"facts": [{"entity": "Orion", "fact_ids": ["product_features[0]"]}]}],
            "summary": {"facts": [{"entity": "Orion", "fact_ids": ["product_features[0]"]},
                                   {"entity": "Nova A/B", "fact_ids": ["product_features[0]", "pricing_tiers[0].features[0]"]}]},
        }

    async def run_result(self, payload, *, target=None, competitors=None):
        self.requests = []
        async def transport(system, user, **kwargs):
            self.requests.append(user)
            return {"content": json.dumps(payload), "finish_reason": "stop"}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            return await ProductAgent().run("Orion", competitors or {"Nova A/B": self.rival},
                                            target or self.target, self.dims)

    async def test_matrix_preserves_sku_region_and_positive_other_version(self):
        result = await self.run_result(self.payload())
        first, second = result.feature_matrix
        self.assertIn(self.target.product_features[0].description, first.values["Orion"])
        self.assertIn(self.rival.product_features[0].description, second.values["Nova A/B"])
        self.assertIn("Nova A, Taiwan", second.values["Nova A/B"])
        self.assertIn("Display and automatic detection supported", second.values["Nova A/B"])
        self.assertNotEqual(second.values["Nova A/B"], "❌")
        self.assertEqual(first.citations, ["o1"])
        self.assertEqual(second.citations, ["n1"])

    async def test_all_main_claims_project_original_scope_instead_of_global_model_copy(self):
        result = await self.run_result(self.payload())
        main_claims = result.summary + " ".join(result.differentiation_points) + " ".join(
            a.our_advantage + a.their_advantage for a in result.competitive_advantages)
        self.assertIn(self.target.product_features[0].description, result.summary)
        self.assertIn(self.target.product_features[0].description, result.differentiation_points[0])
        self.assertIn(self.target.product_features[0].description, result.competitive_advantages[0].our_advantage)
        self.assertNotIn("ALL Orion", main_claims)
        self.assertNotIn("ALL Nova", main_claims)

    async def test_tier_feature_scope_and_stable_entity_local_ids_reach_model(self):
        await self.run_result(self.payload())
        for text in ("pricing_tiers[0].features[0]", "Nova A, Taiwan", "Display and automatic detection supported", "product_features[0]"):
            self.assertIn(text, self.requests[0])

    async def test_missing_or_cross_entity_binding_cannot_preserve_model_claim(self):
        payload = self.payload()
        payload["feature_matrix"][0]["evidence"] = {"Orion": ["pricing_tiers[0].features[0]"]}
        payload["feature_matrix"][1].pop("evidence")
        payload["summary"] = "ALL Orion versions have H13; ALL Nova versions unsupported"
        payload["differentiation_points"] = ["ALL Orion versions have H13"]
        result = await self.run_result(payload)
        self.assertEqual(result.feature_matrix[0].values["Orion"], "⚪")
        self.assertEqual(result.feature_matrix[1].values["Nova A/B"], "⚪")
        self.assertEqual(result.differentiation_points, [])
        self.assertNotIn("ALL Orion", result.summary)
        self.assertEqual(result.feature_matrix[0].citations, [])

    async def test_fact_citations_must_belong_to_actual_same_entity_catalog(self):
        self.target.product_features[0].citations = ["n1"]
        result = await self.run_result(self.payload())
        self.assertEqual(result.feature_matrix[0].values["Orion"], "⚪")
        self.assertNotIn("n1", result.competitive_advantages[0].our_advantage)
        self.assertEqual(result.feature_matrix[0].citations, [])

    async def test_saved_analysis_main_cells_and_claims_render_with_scope_and_escape(self):
        self.target.product_features[0].description += " <script>scope</script>"
        result = await self.run_result(self.payload())
        raw = json.loads(json.dumps(asdict(result)))
        saved = ProductAnalysis(**{**raw,
            "feature_matrix": [FeatureComparison(**r) for r in raw["feature_matrix"]],
            "competitive_advantages": [CompetitiveAdvantage(**r) for r in raw["competitive_advantages"]]})
        markup = StrategyAgent().format_html_report(StrategyReport("Orion", competitor_count=1), product_analysis=saved)
        matrix = markup[markup.index("功能对比矩阵（总览）"):]
        matrix = matrix[:matrix.index("</table>")]
        self.assertIn("Orion Elite, EU 2025 only", matrix)
        self.assertIn("Nova A, Taiwan", matrix)
        self.assertIn("Display and automatic detection supported", matrix)
        self.assertIn("&lt;script&gt;scope&lt;/script&gt;", matrix)
        self.assertNotIn("<script>scope</script>", markup)

    async def test_empty_collection_with_new_contract_remains_a_plain_text_gap(self):
        result = await self.run_result(self.payload(), target=CompetitorData("Orion"),
                                      competitors={"Nova A/B": CompetitorData("Nova A/B")})
        self.assertIsInstance(result.summary, str)
        self.assertIn("资料不足", result.summary)
        self.assertTrue(all(value == "⚪" for row in result.feature_matrix for value in row.values.values()))

    async def test_empty_collection_rejects_old_shape_free_claims_in_new_llm_response(self):
        payload = {"feature_matrix": [{"feature": "Filtration", "values": {"Orion": "ALL SKUs have H13", "Nova A/B": "unsupported"},
                                        "citations": ["invented"]}],
                   "competitive_advantages": [], "differentiation_points": ["ALL versions verified"],
                   "summary": "Orion is universally superior"}
        result = await self.run_result(payload, target=CompetitorData("Orion"),
                                      competitors={"Nova A/B": CompetitorData("Nova A/B")})
        self.assertTrue(all(value == "⚪" for row in result.feature_matrix for value in row.values.values()))
        self.assertEqual(result.citations, [])
        self.assertEqual(result.differentiation_points, [])
        self.assertIn("资料不足", result.summary)
        self.assertNotIn("universally", result.summary)

    async def test_malformed_entity_and_fact_selectors_preserve_other_valid_facts(self):
        payload = self.payload()
        payload["competitive_advantages"].append({"competitor": ["Nova A/B"], "our_evidence": ["product_features[0]"]})
        payload["feature_matrix"][0]["evidence"]["Orion"] = [None, {}, "invented", "product_features[0]"]
        payload["summary"]["facts"].extend([None, {"entity": [], "fact_ids": ["product_features[0]"]}])
        result = await self.run_result(payload)
        self.assertIn("Orion Elite, EU 2025 only", result.feature_matrix[0].values["Orion"])
        self.assertEqual(len(result.competitive_advantages), 1)
        self.assertNotIn("invented", json.dumps(asdict(result)))

    async def test_truncation_merge_and_missing_leaf_cannot_restore_free_model_claims(self):
        parent = self.payload()
        parent["summary"] = "ALL Orion versions have H13"
        recovered = self.payload()
        recovered["summary"]["facts"] = [{"entity": "Orion", "fact_ids": ["product_features[0]"]}]
        replies = iter([(parent, "length"), (recovered, "stop"), (None, "stop")])
        async def transport(system, user, **kwargs):
            content, finish = next(replies)
            return {"content": json.dumps(content) if content else "", "finish_reason": finish}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await ProductAgent().run("Orion", {"Nova A/B": self.rival, "Other": CompetitorData("Other")},
                                            self.target, self.dims)
        self.assertEqual([r.feature for r in result.feature_matrix], ["Filtration", "Interaction"])
        self.assertEqual(list(result.feature_matrix[0].values), ["Orion", "Nova A/B", "Other"])
        self.assertIn("Other", result.summary)
        self.assertIn("Orion Elite, EU 2025 only", result.summary)
        self.assertIn("Display and automatic detection supported", result.feature_matrix[1].values["Nova A/B"])
        self.assertNotIn("ALL Orion", json.dumps(asdict(result)))
        self.assertNotIn("product_features[", json.dumps(asdict(result)))
        self.assertNotIn("pricing_tiers[", json.dumps(asdict(result)))

    async def test_same_agent_does_not_reuse_previous_entity_fact_catalog(self):
        queue = iter([self.payload(), self.payload()])
        async def transport(system, user, **kwargs):
            return {"content": json.dumps(next(queue)), "finish_reason": "stop"}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            agent = ProductAgent()
            first = await agent.run("Orion", {"Nova A/B": self.rival}, self.target, self.dims)
            replacement = CompetitorData("Orion", product_features=[FeatureItem(
                "Different product", "US 2026 only: washable textile filter; no H13 claim.", ["new"])],
                citations=[Citation("new", "New source", "https://example.test/new", "washable")])
            second = await agent.run("Orion", {"Nova A/B": self.rival}, replacement, self.dims)
        self.assertIn("EU 2025", first.feature_matrix[0].values["Orion"])
        self.assertIn("US 2026", second.feature_matrix[0].values["Orion"])
        self.assertNotIn("EU 2025", json.dumps(asdict(second)))

    async def test_recovery_retains_citations_used_only_by_scoped_summary(self):
        leaf = {"feature_matrix": [], "competitive_advantages": [], "differentiation_points": [],
                "summary": {"facts": [{"entity": "Orion", "fact_ids": ["product_features[0]"]}]}}
        replies = iter([("{", "length"), (json.dumps(leaf), "stop"), ("", "stop")])
        async def transport(system, user, **kwargs):
            content, finish = next(replies)
            return {"content": content, "finish_reason": finish}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await ProductAgent().run("Orion", {"Nova A/B": self.rival, "Other": CompetitorData("Other")},
                                            self.target, self.dims)
        self.assertIn("Orion Elite, EU 2025 only", result.summary)
        self.assertIn("o1", result.citations)


if __name__ == "__main__":
    unittest.main()
