"""Regression coverage for category-safe product analysis and truncated recovery."""
import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from agents.product_agent import ProductAgent
from agents.strategy_agent import StrategyAgent
from models.domain import CompetitorData, FeatureItem, PricingAnalysis, MarketAnalysis


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
        self.request_budgets = []

        async def transport(system_prompt, user_message, **kwargs):
            content, truncated = next(queue)
            self.requests.append((system_prompt, user_message))
            self.request_budgets.append(kwargs["max_tokens"])
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
        self.assertIn("2家竞品（A、B）", result.summary)
        self.assertIn("未知4/6格", result.summary)

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
        self.assertEqual(self.request_budgets, [8192, 4096, 4096, 4096, 4096, 4096, 4096])
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

    async def test_recovered_summary_describes_full_scope_and_merged_unknown_cells(self):
        parent = response([])
        parent["summary"] = "过时全局结论：所有品牌都一样"
        one_rival = response([
            {"feature": "蛋白含量", "values": {"OPTIMUM NUTRITION": "✅", "A": "🔶"}},
            {"feature": "配料透明度", "values": {"OPTIMUM NUTRITION": "⚪", "A": "✅"}},
        ])
        one_rival["summary"] = "本次只比较1家竞品A，我方仅在已采集标准款范围可比较。"
        qualified_advantage = "仅对已采集标准款，来源描述了较高蛋白比例"
        one_rival["competitive_advantages"] = [{
            "competitor": "A", "our_advantage": qualified_advantage,
            "their_advantage": "暂无充分证据", "citations": ["A:q0:r0"]}]
        two_rivals = response([
            {"feature": "蛋白含量", "values": {"OPTIMUM NUTRITION": "✅", "B": "❌", "C": "⚪"}},
            {"feature": "配料透明度", "values": {"OPTIMUM NUTRITION": "⚪", "B": "⚪", "C": "✅"}},
        ])
        two_rivals["summary"] = "本次仅含两家竞品B和C；不能把某个SKU结论扩展到全品牌。"
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "ABC"},
            [(json.dumps(parent), True), (json.dumps(one_rival), False), (json.dumps(two_rivals), False)])
        self.assertIn("3家竞品（A、B、C）", result.summary)
        self.assertIn("OPTIMUM NUTRITION", result.summary)
        self.assertIn("2个维度", result.summary)
        self.assertIn("未知3/8格", result.summary)
        self.assertIn("1项", result.summary)
        self.assertIn("分片恢复", result.summary)
        self.assertNotIn("过时全局结论", result.summary)
        overall_summary = result.summary.split("\n局部比较", 1)[0]
        self.assertNotIn("本次只比较1家", overall_summary)
        self.assertNotIn("本次仅含两家", overall_summary)
        self.assertIn("局部比较（仅包含 A）：" + one_rival["summary"], result.summary)
        self.assertIn("局部比较（仅包含 B、C）：" + two_rivals["summary"], result.summary)
        self.assertEqual(result.competitive_advantages[0].our_advantage, qualified_advantage)
        self.assertEqual(result.competitive_advantages[0].citations, ["A:q0:r0"])

    async def test_recovered_differentiation_replaces_stale_parent_and_limits_duplicates(self):
        parent = response([])
        parent["differentiation_points"] = ["过时的全局差异", "过时的全局差异", "过时第二项"]
        child_a = response([])
        child_a["differentiation_points"] = ["仅采集款蛋白来源不同", "需补齐配料证据"]
        child_bc = response([])
        child_bc["differentiation_points"] = ["需补齐配料证据", "C仅标准款可比较", "最后一项"]
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "ABC"},
            [(json.dumps(parent), True), (json.dumps(child_a), False), (json.dumps(child_bc), False)])
        self.assertEqual(result.differentiation_points,
                         ["仅采集款蛋白来源不同", "需补齐配料证据", "C仅标准款可比较"])

    async def test_primary_budget_allows_complete_response_without_unnecessary_splitting(self):
        """A real parse succeeds only when the whole-request budget exceeds 4096."""
        calls = []
        async def transport(system_prompt, user_message, **kwargs):
            budget = kwargs["max_tokens"]
            calls.append(budget)
            if budget > 4096:
                content = json.dumps(response([{
                    "feature": "蛋白含量", "values": {
                        "OPTIMUM NUTRITION": "✅", "A": "🔶", "B": "❌", "C": "✅"}}]))
            else:
                content = '{"feature_matrix":['
            return {"content": content, "finish_reason": "stop" if budget > 4096 else "length",
                    "usage": {}, "timestamp": "", "model": "fixture",
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                    "duration_ms": 0}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await ProductAgent().run(
                "OPTIMUM NUTRITION", {name: CompetitorData(name) for name in "ABC"},
                sub_dimensions=DIMENSIONS)
        self.assertEqual(result.feature_matrix[0].values,
                         {"OPTIMUM NUTRITION": "✅", "A": "🔶", "B": "❌", "C": "✅"})
        self.assertEqual(calls, [8192])

    async def test_recovery_without_differences_does_not_salvage_stale_global_conclusion(self):
        parent = response([])
        parent["differentiation_points"] = ["过时全局结论"]
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "AB"},
            [(json.dumps(parent), True), (json.dumps(response([])), False),
             (json.dumps(response([])), False)])
        self.assertEqual(result.differentiation_points, [])

    async def test_local_summary_qualifiers_reach_strategy_input_and_json_export(self):
        child_a = response([{"feature": "蛋白含量", "values": {"A": "✅"}}])
        child_a["summary"] = "仅适用于2025年在中国销售的500g无糖SKU。"
        child_a["competitive_advantages"] = [{
            "competitor": "A", "our_advantage": "含糖量较低", "citations": ["A:q0:r0"]}]
        child_bc = response([])
        child_bc["summary"] = "仅限2024年欧洲1kg原味SKU，不适用于其他配方。"
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "ABC"},
            [("{", True), (json.dumps(child_a), False), (json.dumps(child_bc), False)])
        self.assertIn("3家竞品（A、B、C）", result.summary)
        self.assertIn("局部比较（仅包含 A）：" + child_a["summary"], result.summary)
        self.assertIn("局部比较（仅包含 B、C）：" + child_bc["summary"], result.summary)
        self.assertEqual(result.competitive_advantages[0].our_advantage, "含糖量较低")
        strategy_input = StrategyAgent()._build_analysis_text(
            "OPTIMUM NUTRITION", result, PricingAnalysis(), MarketAnalysis())
        exported = json.loads(json.dumps(asdict(result), ensure_ascii=False))
        for qualifier in (child_a["summary"], child_bc["summary"]):
            self.assertIn(qualifier, strategy_input)
            self.assertIn(qualifier, exported["summary"])

    async def test_nested_recovery_preserves_original_subset_notes_without_obsolete_parent(self):
        obsolete_ab = response([])
        obsolete_ab["summary"] = "过时AB批次限定"
        obsolete_ab["competitive_advantages"] = [{"competitor": "A", "our_advantage": "过时优势"}]
        child_a = response([])
        child_a["summary"] = "A仅中国2025年500g规格"
        child_a["competitive_advantages"] = [{"competitor": "A", "our_advantage": "新优势"}]
        child_b = response([])
        child_b["summary"] = "B仅日本2024年无糖规格"
        child_cd = response([])
        child_cd["summary"] = "C、D仅欧洲2024年系列"
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "ABCD"},
            [("{", True), (json.dumps(obsolete_ab), True), (json.dumps(child_a), False),
             (json.dumps(child_b), False), (json.dumps(child_cd), False)])
        self.assertIn("4家竞品（A、B、C、D）", result.summary)
        self.assertIn("局部比较（仅包含 A）：" + child_a["summary"], result.summary)
        self.assertIn("局部比较（仅包含 B）：" + child_b["summary"], result.summary)
        self.assertIn("局部比较（仅包含 C、D）：" + child_cd["summary"], result.summary)
        self.assertNotIn("过时AB批次限定", result.summary)
        self.assertNotIn("局部比较（仅包含 A、B）", result.summary)
        self.assertEqual(result.summary.count("分片恢复合并"), 1)

    async def test_parent_qualification_survives_for_unreplaced_parent_advantage(self):
        parent = response([])
        parent["summary"] = "原始批次仅涵盖2025年中国500g无糖规格"
        parent["competitive_advantages"] = [
            {"competitor": "A", "our_advantage": "过时A"},
            {"competitor": "B", "our_advantage": "含糖量较低", "citations": ["B:q0:r0"]},
        ]
        child_a = response([])
        child_a["summary"] = "A的恢复资料仅适用于2026年欧盟原味规格"
        child_a["competitive_advantages"] = [{"competitor": "A", "our_advantage": "新A"}]
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "AB"},
            [(json.dumps(parent), True), (json.dumps(child_a), False), ("", False)])
        self.assertEqual(result.competitive_advantages[1].our_advantage, "含糖量较低")
        self.assertIn(parent["summary"], result.summary)
        self.assertIn("局部比较（仅包含 A、B）", result.summary)
        self.assertIn("保留原批次判断：B", result.summary)
        self.assertIn("局部比较（仅包含 A）：" + child_a["summary"], result.summary)

    async def test_parent_qualification_survives_for_unreplaced_matrix_cell(self):
        parent = response([{"feature": "蛋白含量", "values": {"A": "✅"}}])
        parent["summary"] = "原矩阵仅适用于2024年美国销售的1kg SKU。"
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "AB"},
            [(json.dumps(parent), True), (json.dumps(response([])), False),
             (json.dumps(response([])), False)])
        self.assertEqual(result.feature_matrix[0].values["A"], "✅")
        self.assertEqual(result.competitive_advantages, [])
        self.assertIn(parent["summary"], result.summary)
        self.assertIn("保留原批次判断：A", result.summary)


if __name__ == "__main__":
    unittest.main()
