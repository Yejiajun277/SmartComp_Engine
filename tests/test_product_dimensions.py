"""Regression coverage for category-safe product analysis and truncated recovery."""
import json
import unittest
from unittest.mock import patch

from agents.product_agent import ProductAgent
from models.domain import CompetitorData, FeatureItem


DIMENSIONS = "1. **蛋白含量**：每份蛋白质含量\n2. **配料透明度**：成分及添加物"


def response(rows):
    return {"feature_matrix": rows, "competitive_advantages": [],
            "differentiation_points": [], "summary": "基于采集资料"}


class ProductDimensionTests(unittest.IsolatedAsyncioTestCase):
    async def run_with_transport(self, competitors, replies, dimensions=DIMENSIONS,
                                 target=None):
        """Replace only the network boundary; keep prompt/JSON/recovery logic real."""
        queue = iter(replies)
        self.requests = []

        async def transport(system_prompt, user_message, **kwargs):
            content, truncated = next(queue)
            self.requests.append((system_prompt, user_message))
            return {"content": content, "finish_reason": "length" if truncated else "stop",
                    "usage": {}, "timestamp": "", "model": "fixture",
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                    "duration_ms": 0}

        with patch("config.ENABLE_LLM", True), \
             patch("agents.base_agent.async_llm_call", transport):
            return await ProductAgent().run("OPTIMUM NUTRITION", competitors,
                                            target, dimensions)

    async def test_failed_model_preserves_requested_protein_dimensions_as_unknown(self):
        result = await self.run_with_transport(
            {"Gainer": CompetitorData("Gainer", strengths="contains repair ingredients")},
            [("", False)])
        self.assertEqual([row.feature for row in result.feature_matrix],
                         ["蛋白含量", "配料透明度"])
        for row in result.feature_matrix:
            self.assertEqual(row.values, {"OPTIMUM NUTRITION": "⚪", "Gainer": "⚪"})
            self.assertEqual(row.citations, [])
        self.assertIn("降级", result.summary)

    async def test_no_dimensions_uses_collected_features_without_ai_substring_claims(self):
        result = await self.run_with_transport(
            {"Gainer": CompetitorData("Gainer", product_features=[
                FeatureItem("蛋白来源", "contains milk; repair formula")])},
            [("", False)], dimensions="")
        self.assertEqual([row.feature for row in result.feature_matrix], ["蛋白来源"])
        self.assertEqual(result.feature_matrix[0].values,
                         {"OPTIMUM NUTRITION": "⚪", "Gainer": "⚪"})

    async def test_no_dimensions_or_features_produces_honest_empty_gap(self):
        result = await self.run_with_transport(
            {"Gainer": CompetitorData("Gainer", strengths="contains repair")},
            [("", False)], dimensions="")
        self.assertEqual(result.feature_matrix, [])
        self.assertIn("不足", result.summary)

    async def test_invalid_truncated_chunks_split_before_discarding_parse_failure(self):
        competitors = {name: CompetitorData(name) for name in "ABCD"}
        def leaf(name):
            return (json.dumps(response([{"feature": "蛋白含量", "values": {
                name: "✅", "OPTIMUM NUTRITION": "🔶"}}]), ensure_ascii=False), False)
        result = await self.run_with_transport(competitors, [
            ('{"feature_matrix":[', True), ('{"feature_matrix":[', True),
            leaf("A"), leaf("B"), ('{"feature_matrix":[', True), leaf("C"), leaf("D")])
        self.assertEqual(result.feature_matrix[0].values,
                         {"OPTIMUM NUTRITION": "🔶", "A": "✅", "B": "✅", "C": "✅", "D": "✅"})
        self.assertEqual(len(self.requests), 7)
        self.assertEqual([row.feature for row in result.feature_matrix], ["蛋白含量", "配料透明度"])

    async def test_partial_chunks_keep_all_cells_and_do_not_erase_known_target(self):
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "AB"}, [
                ("{", True),
                (json.dumps(response([{"feature": "蛋白含量", "values": {
                    "A": "✅", "OPTIMUM NUTRITION": "🔶"}}]), ensure_ascii=False), False),
                ("", False)])
        self.assertEqual(result.feature_matrix[0].values,
                         {"OPTIMUM NUTRITION": "🔶", "A": "✅", "B": "⚪"})
        self.assertEqual(result.feature_matrix[1].values,
                         {"OPTIMUM NUTRITION": "⚪", "A": "⚪", "B": "⚪"})
        self.assertIn("降级", result.summary)

    async def test_requested_names_normalize_explanatory_suffix_and_exclude_other_rows(self):
        result = await self.run_with_transport({"A": CompetitorData("A")}, [
            (json.dumps(response([
                {"feature": "蛋白含量（每份克数）", "values": {"A": "✅", "Stranger": "✅"}},
                {"feature": "AI助手", "values": {"A": "✅"}},
                {"feature": "非蛋白含量", "values": {"A": "❌"}},
            ]), ensure_ascii=False), False)])
        self.assertEqual([row.feature for row in result.feature_matrix], ["蛋白含量", "配料透明度"])
        self.assertEqual(result.feature_matrix[0].values,
                         {"OPTIMUM NUTRITION": "⚪", "A": "✅"})

    async def test_all_truncations_stop_at_single_competitor_with_unknown_coverage(self):
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "ABCD"}, [("{", True)] * 7)
        self.assertEqual(len(self.requests), 7)
        self.assertEqual([row.feature for row in result.feature_matrix], ["蛋白含量", "配料透明度"])
        self.assertEqual(result.feature_matrix[0].values,
                         {"OPTIMUM NUTRITION": "⚪", "A": "⚪", "B": "⚪", "C": "⚪", "D": "⚪"})

    async def test_recovered_advantages_replace_parent_entries_and_obsolete_citations(self):
        parent = response([])
        parent["competitive_advantages"] = [
            {"competitor": "A", "our_advantage": "obsolete A", "their_advantage": "old A",
             "citations": ["A:q0:r0"]},
            {"competitor": "B", "our_advantage": "obsolete B", "their_advantage": "old B",
             "citations": ["B:q0:r0"]},
        ]
        child_a = response([])
        child_a["competitive_advantages"] = [
            {"competitor": "A", "our_advantage": "recovered A", "their_advantage": "new A",
             "citations": ["A:q1:r0"]}]
        child_b = response([])
        child_b["competitive_advantages"] = [
            {"competitor": "B", "our_advantage": "recovered B", "their_advantage": "new B",
             "citations": ["B:q1:r0"]}]
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "AB"},
            [(json.dumps(parent), True), (json.dumps(child_a), False), (json.dumps(child_b), False)])
        self.assertEqual([(adv.competitor, adv.our_advantage, adv.their_advantage)
                          for adv in result.competitive_advantages],
                         [("A", "recovered A", "new A"), ("B", "recovered B", "new B")])
        self.assertEqual(result.citations, ["A:q1:r0", "B:q1:r0"])
        self.assertEqual([adv.citations for adv in result.competitive_advantages],
                         [["A:q1:r0"], ["B:q1:r0"]])

    async def test_parent_advantage_survives_when_recovery_has_no_replacement(self):
        parent = response([])
        parent["competitive_advantages"] = [
            {"competitor": "A", "our_advantage": "old A", "citations": ["A:q0:r0"]},
            {"competitor": "B", "our_advantage": "known B", "citations": ["B:q0:r0"]},
        ]
        child_a = response([])
        child_a["competitive_advantages"] = [
            {"competitor": "A", "our_advantage": "recovered A", "citations": ["A:q1:r0"]}]
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "AB"},
            [(json.dumps(parent), True), (json.dumps(child_a), False), ("", False)])
        self.assertEqual([(adv.competitor, adv.our_advantage)
                          for adv in result.competitive_advantages],
                         [("A", "recovered A"), ("B", "known B")])
        self.assertEqual(result.citations, ["A:q1:r0", "B:q0:r0"])


if __name__ == "__main__":
    unittest.main()
