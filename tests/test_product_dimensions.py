"""Regression coverage for category-safe product analysis and truncated recovery."""
import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from agents.product_agent import ProductAgent
from agents.strategy_agent import StrategyAgent
from models.domain import Citation, CompetitorData, FeatureItem, PricingAnalysis, MarketAnalysis


DIMENSIONS = "1. **蛋白含量**：每份蛋白质含量\n2. **配料透明度**：成分及添加物"


def response(rows):
    return {"feature_matrix": rows, "competitive_advantages": [],
            "differentiation_points": [], "summary": "基于采集资料"}


def collected(name):
    texts = [f"{name} only China 2025 500g SKU: 20g protein.", f"{name} only EU 2026 1kg SKU: 24g protein.", f"{name} China 2025 ingredients disclosed."]
    return CompetitorData(name, product_features=[FeatureItem("Fact", t, [f"{name}:fact{i}"]) for i,t in enumerate(texts)],
        citations=[Citation(f"{name}:fact{i}", snippet=t) for i,t in enumerate(texts)])

def bound_row(feature, names, index=0):
    return {"feature":feature,"evidence":{n:[f"product_features[{index}]"] for n in names}}

def bound_response(rows=(), names=(), index=0, advantages=(), points=()):
    return {"feature_matrix":list(rows),"competitive_advantages":[
        {"competitor":n,"our_evidence":[f"product_features[{i}]"],"their_evidence":[f"product_features[{i}]"]} for n,i in advantages],
        "differentiation_points":[{"facts":[{"entity":n,"fact_ids":[f"product_features[{i}]"]}]} for n,i in points],
        "summary":{"facts":[{"entity":n,"fact_ids":[f"product_features[{index}]"]} for n in names]}}


class ProductDimensionTests(unittest.IsolatedAsyncioTestCase):
    async def run_bound(self, names, replies):
        return await self.run_with_transport({n:collected(n) for n in names},
            [(json.dumps(x,ensure_ascii=False) if isinstance(x,dict) else x,t) for x,t in replies],
            target=collected("OPTIMUM NUTRITION"))

    async def test_full_product_scope_and_source_qualifiers_reach_analysis(self):
        data = CompetitorData("CompA", product_features=[
            FeatureItem(f"Feature {n}", "Original details " * 30 + f"MODEL_SCOPE_{n}", [f"c{n}"])
            for n in range(12)],
            strengths="Original strength " * 20 + "ONLY_ONE_MODEL",
            weaknesses="Original weakness " * 20 + "OTHER_MODELS_UNKNOWN",
            citations=[Citation("c11", "Source", "https://example.test/source",
                                "Source text " * 30 + "SOURCE_SCOPE_END")])
        await self.run_with_transport({"CompA": data}, [(json.dumps(response([])), False)], target=data)
        prompt = self.requests[0][1]
        for retained in ("MODEL_SCOPE_0", "MODEL_SCOPE_11", "ONLY_ONE_MODEL",
                         "OTHER_MODELS_UNKNOWN", "SOURCE_SCOPE_END", "c11"):
            self.assertIn(retained, prompt)

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
        leaves=[(bound_response([bound_row("蛋白含量",["OPTIMUM NUTRITION",n])]),False) for n in "ABCD"]
        result=await self.run_bound("ABCD",[("{",True),("{",True),*leaves[:2],("{",True),*leaves[2:]])
        for n in ["OPTIMUM NUTRITION",*"ABCD"]:
            self.assertIn(n+" only China 2025",result.feature_matrix[0].values[n])
        self.assertEqual(len(self.requests),7)
        self.assertEqual([r.feature for r in result.feature_matrix],["蛋白含量","配料透明度"])

    async def test_partial_chunks_keep_all_cells_and_do_not_erase_known_target(self):
        result=await self.run_bound("AB",[("{",True),(bound_response([bound_row("蛋白含量",["OPTIMUM NUTRITION","A"])]),False),("",False)])
        for n in ["OPTIMUM NUTRITION","A"]:
            self.assertIn(n+" only China 2025",result.feature_matrix[0].values[n])
        self.assertEqual(result.feature_matrix[0].values["B"],"⚪")
        self.assertTrue(all(v=="⚪" for v in result.feature_matrix[1].values.values()))
        for s in ["降级","2家竞品（A、B）","未知4/6格"]: self.assertIn(s,result.summary)

    async def test_requested_names_normalize_explanatory_suffix_and_exclude_other_rows(self):
        result=await self.run_bound("A",[(bound_response([bound_row("蛋白含量（每份克数）",["A","Stranger"]),bound_row("AI助手",["A"]),bound_row("非蛋白含量",["A"])]),False)])
        self.assertEqual([r.feature for r in result.feature_matrix],["蛋白含量","配料透明度"])
        self.assertEqual(set(result.feature_matrix[0].values),{"OPTIMUM NUTRITION","A"})
        self.assertIn("A only China 2025",result.feature_matrix[0].values["A"])
        self.assertEqual(result.feature_matrix[0].values["OPTIMUM NUTRITION"],"⚪")

    async def test_all_truncations_stop_at_single_competitor_with_unknown_coverage(self):
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "ABCD"}, [("{", True)] * 7)
        self.assertEqual(len(self.requests), 7)
        self.assertEqual(self.request_budgets, [8192, 4096, 4096, 4096, 4096, 4096, 4096])
        self.assertEqual([row.feature for row in result.feature_matrix], ["蛋白含量", "配料透明度"])
        self.assertEqual(result.feature_matrix[0].values,
                         {"OPTIMUM NUTRITION": "⚪", "A": "⚪", "B": "⚪", "C": "⚪", "D": "⚪"})

    async def test_recovered_advantages_replace_parent_entries_and_obsolete_citations(self):
        result=await self.run_bound("AB",[(bound_response(advantages=[("A",0),("B",0)]),True),(bound_response(advantages=[("A",1)]),False),(bound_response(advantages=[("B",1)]),False)])
        self.assertEqual([a.competitor for a in result.competitive_advantages],["A","B"])
        for a in result.competitive_advantages:
            self.assertIn("EU 2026",a.our_advantage)
            self.assertIn("EU 2026",a.their_advantage)
        self.assertEqual(set(result.citations),{"OPTIMUM NUTRITION:fact1","A:fact1","B:fact1"})

    async def test_parent_advantage_survives_when_recovery_has_no_replacement(self):
        result=await self.run_bound("AB",[(bound_response(advantages=[("A",0),("B",0)]),True),(bound_response(advantages=[("A",1)]),False),("",False)])
        self.assertEqual([a.competitor for a in result.competitive_advantages],["A","B"])
        self.assertIn("EU 2026",result.competitive_advantages[0].their_advantage)
        self.assertIn("China 2025",result.competitive_advantages[1].their_advantage)
        self.assertIn("B:fact0",result.citations)

    async def test_recovered_summary_describes_full_scope_and_merged_unknown_cells(self):
        parent=response([]); parent["summary"]="过时全局结论"
        one=bound_response([bound_row("蛋白含量",["OPTIMUM NUTRITION","A"]),bound_row("配料透明度",["A"],2)],["A"],advantages=[("A",0)])
        two=bound_response([bound_row("蛋白含量",["OPTIMUM NUTRITION","B"]),bound_row("配料透明度",["C"],2)],["B","C"])
        result=await self.run_bound("ABC",[(parent,True),(one,False),(two,False)])
        for s in ["3家竞品（A、B、C）","2个维度","未知3/8格","1项","局部比较（仅包含 A）","局部比较（仅包含 B、C）"]: self.assertIn(s,result.summary)
        self.assertNotIn("过时全局结论",result.summary)
        self.assertIn("A only China 2025",result.competitive_advantages[0].their_advantage)

    async def test_recovered_differentiation_replaces_stale_parent_and_limits_duplicates(self):
        parent=response([]); parent["differentiation_points"]=["过时全局差异"]
        one=bound_response(points=[("OPTIMUM NUTRITION",0),("A",0)])
        two=bound_response(points=[("OPTIMUM NUTRITION",0),("C",0),("B",0)])
        result=await self.run_bound("ABC",[(parent,True),(one,False),(two,False)])
        self.assertEqual(len(result.differentiation_points),3)
        for point,n in zip(result.differentiation_points,["OPTIMUM NUTRITION","A","C"]): self.assertIn(n+" only China 2025",point)
        self.assertNotIn("过时全局差异"," ".join(result.differentiation_points))

    async def test_primary_budget_allows_complete_response_without_unnecessary_splitting(self):
        calls=[]
        async def transport(system,prompt,**kwargs):
            budget=kwargs["max_tokens"];calls.append(budget)
            return {"content":json.dumps(bound_response([bound_row("蛋白含量",["OPTIMUM NUTRITION",*"ABC"])])) if budget>4096 else "{","finish_reason":"stop" if budget>4096 else "length"}
        with patch("config.ENABLE_LLM",True),patch("agents.base_agent.async_llm_call",transport):
            result=await ProductAgent().run("OPTIMUM NUTRITION",{n:collected(n) for n in "ABC"},collected("OPTIMUM NUTRITION"),DIMENSIONS)
        self.assertEqual(calls,[8192])
        for n in ["OPTIMUM NUTRITION",*"ABC"]: self.assertIn(n+" only China 2025",result.feature_matrix[0].values[n])

    async def test_recovery_without_differences_does_not_salvage_stale_global_conclusion(self):
        parent = response([])
        parent["differentiation_points"] = ["过时全局结论"]
        result = await self.run_with_transport(
            {name: CompetitorData(name) for name in "AB"},
            [(json.dumps(parent), True), (json.dumps(response([])), False),
             (json.dumps(response([])), False)])
        self.assertEqual(result.differentiation_points, [])

    async def test_local_summary_qualifiers_reach_strategy_input_and_json_export(self):
        one=bound_response([bound_row("蛋白含量",["A"])],["A"],advantages=[("A",0)])
        two=bound_response(names=["B","C"],index=1)
        result=await self.run_bound("ABC",[("{",True),(one,False),(two,False)])
        strategy=StrategyAgent()._build_analysis_text("OPTIMUM NUTRITION",result,PricingAnalysis(),MarketAnalysis())
        exported=json.loads(json.dumps(asdict(result),ensure_ascii=False))
        for s in ["A only China 2025 500g SKU","B only EU 2026 1kg SKU","C only EU 2026 1kg SKU"]:
            self.assertIn(s,strategy)
            self.assertIn(s,exported["summary"])

    async def test_nested_recovery_preserves_original_subset_notes_without_obsolete_parent(self):
        result=await self.run_bound("ABCD",[("{",True),(bound_response(names=["A"],advantages=[("A",0)]),True),
            (bound_response(names=["A"],index=1,advantages=[("A",1)]),False),(bound_response(names=["B"],index=1),False),(bound_response(names=["C","D"],index=1),False)])
        for n in "ABCD": self.assertIn(n+" only EU 2026",result.summary)
        self.assertNotIn("A only China 2025",result.summary)
        self.assertNotIn("局部比较（仅包含 A、B）",result.summary)
        self.assertEqual(result.summary.count("分片恢复合并"),1)

    async def test_parent_qualification_survives_for_unreplaced_parent_advantage(self):
        result=await self.run_bound("AB",[(bound_response(names=["A","B"],advantages=[("A",0),("B",0)]),True),
            (bound_response(names=["A"],index=1,advantages=[("A",1)]),False),("",False)])
        self.assertIn("B only China 2025",result.competitive_advantages[1].their_advantage)
        for s in ["B only China 2025","保留原批次判断：B","A only EU 2026"]: self.assertIn(s,result.summary)

    async def test_parent_qualification_survives_for_unreplaced_matrix_cell(self):
        result=await self.run_bound("AB",[(bound_response([bound_row("蛋白含量",["A"])],["A"]),True),(bound_response(),False),(bound_response(),False)])
        self.assertIn("A only China 2025",result.feature_matrix[0].values["A"])
        self.assertEqual(result.competitive_advantages,[])
        self.assertIn("A only China 2025",result.summary)
        self.assertIn("保留原批次判断：A",result.summary)


if __name__ == "__main__":
    unittest.main()
