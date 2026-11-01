"""Dimensions must come from this category's model proposal or collected facts."""
import contextlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agents.dimension_agent import DimensionAgent
from agents.product_agent import ProductAgent
from core.orchestrator import Orchestrator
from models.domain import CompetitorData, CompetitorInfo, CompetitorList, FeatureItem
from workflow.nodes import AnalysisGraphNodes


def features(name, *labels):
    return CompetitorData(name=name, product_features=[FeatureItem(label, "Collected description") for label in labels])


def proposal(prefix="Vacuum"):
    return {
        "product_category": {"level1": "Consumer product", "level2": prefix},
        "product_sub_dimensions": [{"name": name, "description": "Compare collected evidence"}
                                   for name in ("Suction", "Battery", "Filtration", "Dust handling")],
        "pricing_sub_dimensions": [{"name": name, "description": "Compare published prices"}
                                   for name in ("Purchase price", "Accessories", "Maintenance", "Promotions")],
        "reasoning": "Category-specific model proposal",
    }


class DimensionGeneralizationTests(unittest.IsolatedAsyncioTestCase):
    async def generate(self, agent, product, competitors, **kwargs):
        try:
            return await agent.run(product, competitors, **kwargs)
        except (TypeError, AttributeError, ValueError) as exc:
            self.fail(f"Dimension generation must return a scoped config, not crash: {exc}")

    async def with_model(self, payloads, action):
        pending = iter(payloads)

        async def transport(*args, **kwargs):
            return {"content": json.dumps(next(pending)), "finish_reason": "stop", "usage": {},
                    "timestamp": "fixture", "model": "test", "prompt_tokens": 0,
                    "completion_tokens": 0, "total_tokens": 0, "duration_ms": 0}

        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            return await action()

    async def test_rule_fallback_uses_current_collected_names_across_unrelated_categories(self):
        cases = [
            ("Dyson", "Cordless vacuum", features("Dyson", "Suction", "Battery"),
             {"Rival": features("Rival", "Suction", "Filtration")}, ["Suction", "Battery", "Filtration"]),
            ("JI Hotel", "Hotel accommodation", features("JI Hotel", "Room hygiene", "Bed comfort"),
             {"Rival": features("Rival", "Breakfast", "Check-in")},
             ["Room hygiene", "Breakfast", "Bed comfort", "Check-in"]),
        ]
        agent = DimensionAgent()
        with patch("config.ENABLE_LLM", False):
            for product, category, target, data, expected in cases:
                with self.subTest(product=product):
                    result = await self.generate(
                        agent, product, CompetitorList(product, category),
                        competitors_data=data, target_product_data=target)
                    self.assertEqual([d.name for d in result.product_sub_dimensions], expected)
                    self.assertEqual(result.product_category.level2, category)
                    self.assertEqual(result.pricing_sub_dimensions, [])
                    self.assertIn("规则", result.reasoning)

    async def test_legacy_call_without_facts_keeps_category_and_exposes_a_gap(self):
        with patch("config.ENABLE_LLM", False):
            result = await DimensionAgent().run("Hotel", CompetitorList("Hotel", "Hotel accommodation"))
        self.assertEqual(result.product_sub_dimensions, [])
        self.assertEqual(result.pricing_sub_dimensions, [])
        self.assertEqual(result.product_category.level2, "Hotel accommodation")
        self.assertTrue(result.reasoning)

    async def test_no_data_does_not_turn_product_or_rival_descriptions_into_dimensions(self):
        competitors = CompetitorList("Future device", "", [CompetitorInfo("Rival", "Arbitrary sales slogan")])
        with patch("config.ENABLE_LLM", False):
            result = await self.generate(DimensionAgent(), "A claimed breakthrough", competitors,
                                         competitors_data={"Rival": features("Rival", "", "   ")})
        self.assertEqual(result.product_sub_dimensions, [])
        self.assertEqual(result.pricing_sub_dimensions, [])
        self.assertEqual(result.product_category.level2, "")

    async def test_fallback_deduplicates_current_names_and_limits_the_comparison_scope(self):
        with patch("config.ENABLE_LLM", False):
            result = await self.generate(
                DimensionAgent(), "Vacuum", CompetitorList("Vacuum", "Vacuum"),
                target_product_data=features("Vacuum", "Suction", " Battery ", "", "suction"),
                competitors_data={"Rival": features("Rival", "Filtration", "Dust handling", "Noise", "Weight", "Service")})
        self.assertEqual([d.name for d in result.product_sub_dimensions],
                         ["Suction", "Filtration", "Battery", "Dust handling", "Noise", "Weight"])

    async def test_long_target_feature_list_cannot_hide_all_rival_features(self):
        with patch("config.ENABLE_LLM", False):
            result = await self.generate(
                DimensionAgent(), "Vacuum", CompetitorList("Vacuum", "Vacuum"),
                target_product_data=features("Vacuum", "Suction", "Battery", "Weight", "Noise", "Handle", "Dustbin"),
                competitors_data={"Rival": features("Rival", "Autonomous cleaning", "Maintenance", "Service")})
        self.assertEqual([d.name for d in result.product_sub_dimensions],
                         ["Suction", "Autonomous cleaning", "Battery", "Maintenance", "Weight", "Service"])

    async def test_malformed_model_proposals_fall_back_instead_of_being_saved_as_success(self):
        malformed = [None, {}, {"product_category": []}, proposal()]
        malformed[-1]["product_sub_dimensions"] = [{"name": "Same", "description": "Repeated"}] * 4
        bad_item = proposal()
        bad_item["product_sub_dimensions"][0] = "not a dimension object"
        malformed.append(bad_item)
        bad_price = proposal()
        bad_price["pricing_sub_dimensions"] = []
        malformed.append(bad_price)
        blank = proposal()
        blank["product_sub_dimensions"][0]["name"] = " "
        malformed.append(blank)
        for payload in malformed:
            with self.subTest(payload=payload):
                async def action():
                    return await self.generate(
                        DimensionAgent(), "Hotel", CompetitorList("Hotel", "Hotel accommodation"),
                        target_product_data=features("Hotel", "Room hygiene", "Bed comfort"))
                result = await self.with_model([payload], action)
                self.assertEqual([d.name for d in result.product_sub_dimensions], ["Room hygiene", "Bed comfort"])
                self.assertEqual(result.pricing_sub_dimensions, [])
                self.assertIn("规则", result.reasoning)

    async def test_valid_model_proposal_survives_without_being_replaced_by_collected_labels(self):
        async def action():
            return await self.generate(
                DimensionAgent(), "Vacuum", CompetitorList("Vacuum", "Discovered category"),
                target_product_data=features("Vacuum", "Marketing feature"))
        result = await self.with_model([proposal()], action)
        self.assertEqual([d.name for d in result.product_sub_dimensions],
                         ["Suction", "Battery", "Filtration", "Dust handling"])
        self.assertEqual([d.name for d in result.pricing_sub_dimensions],
                         ["Purchase price", "Accessories", "Maintenance", "Promotions"])
        self.assertEqual(result.product_category.level2, "Vacuum")
        self.assertEqual(result.reasoning, "Category-specific model proposal")

    async def test_reused_agent_after_model_failure_cannot_keep_the_previous_category(self):
        agent = DimensionAgent()

        async def action():
            first = await self.generate(agent, "Vacuum", CompetitorList("Vacuum", "Vacuum"))
            second = await self.generate(
                agent, "Hotel", CompetitorList("Hotel", "Hotel accommodation"),
                target_product_data=features("Hotel", "Room hygiene", "Bed comfort"))
            return first, second

        first, second = await self.with_model([proposal(), {}], action)
        self.assertEqual(first.product_category.level2, "Vacuum")
        self.assertEqual([d.name for d in second.product_sub_dimensions], ["Room hygiene", "Bed comfort"])
        self.assertEqual(second.product_category.level2, "Hotel accommodation")

    async def test_graph_passes_collected_facts_and_keeps_missing_evidence_unknown(self):
        orch = SimpleNamespace(
            dimension_agent=DimensionAgent(), product_agent=ProductAgent(), timings={},
            _format_sub_dimensions=Orchestrator._format_sub_dimensions,
            _save_artifact_json=lambda *args: None,
        )
        state = {
            "product_description": "Cordless vacuum", "product_name": "Dyson",
            "competitor_list": CompetitorList("Dyson", "Cordless vacuum"),
            "target_product_data": features("Dyson", "Suction", "Battery"),
            "competitors_data": {"Rival": features("Rival", "Filtration")},
        }
        with patch("config.ENABLE_LLM", False):
            nodes = AnalysisGraphNodes(orch)
            state.update(await nodes.generate_dimensions(state))
            result = await nodes.run_product_analysis(state)
        rows = result["product_analysis"].feature_matrix
        self.assertEqual([row.feature for row in rows], ["Suction", "Filtration", "Battery"])
        self.assertTrue(all(row.values == {"Dyson": "⚪", "Rival": "⚪"} for row in rows))

    async def test_legacy_orchestration_supplies_facts_to_dimension_fallback(self):
        from tests.test_orchestrator_baseline import make_orchestrator

        orch = make_orchestrator()
        orch.dimension_agent = DimensionAgent()
        orch.product_agent = ProductAgent()
        target = features("Target", "Suction", "Battery")
        rivals = {"CompA": features("CompA", "Filtration"), "CompB": features("CompB", "Noise")}
        orch.collection_agent.collect_target_product = lambda *args, **kwargs: target

        async def collected(*args, **kwargs):
            return rivals

        orch.collection_agent.run = collected
        with patch("config.ENABLE_LLM", False), patch("config.SKIP_QA", True), contextlib.redirect_stdout(io.StringIO()):
            await orch._analyze_legacy("Vacuum", 2)
        self.assertEqual([row.feature for row in orch._last_product_analysis.feature_matrix],
                         ["Suction", "Filtration", "Noise", "Battery"])


if __name__ == "__main__":
    unittest.main()
