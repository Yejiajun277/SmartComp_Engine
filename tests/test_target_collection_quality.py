"""Target facts must cross the same collection QA/repair gate as rivals."""
from copy import deepcopy
import asyncio
import unittest
from unittest.mock import patch

from agents.quality_agent import QualityAgent
from core.artifact_store import to_jsonable
from core.collection_retry import repair_collection
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier, QualityCheckResult, QualityIssue
from tests.test_orchestrator_baseline import (
    FakeCollectionAgent, FakeQualityAgent, competitor_list, make_orchestrator, run_quietly,
)
from tests.test_workflow_graph import run_graph_quietly
from workflow.nodes import AnalysisGraphNodes


BAD = "Two batteries included for every version."
FIXED = "Two batteries only in the named kit; standard unit excludes a spare."
TARGET_SOURCE = "Original kit footnote; standard unit excludes spare. " * 900 + " TARGET_SOURCE_TAIL"


def entity(name):
    cites = [Citation(f"{name}:q0:r{i}", f"Source {i}", f"https://example.test/{name}/{i}",
                      snippet="Named kit only; standard unit excludes a spare.") for i in range(2)]
    return CompetitorData(name,
        product_features=[FeatureItem("Kit", BAD, [cites[0].id]), FeatureItem("Core", "Source feature", [cites[1].id])],
        pricing_tiers=[PricingTier("Standard", "399 per unit, selected region", citations=[cites[0].id]),
                       PricingTier("Kit", "Price not provided for this kit", citations=[cites[1].id])],
        market_share="The source gives no measured share for this defined market.",
        user_reviews="The source contains a user's bounded account of this product.",
        strengths="The source describes a specific supported capability and scope.",
        weaknesses="A source states limitations under the named conditions only.",
        channels="The cited source identifies an official retail channel only.",
        citations=cites, search_sources=["Original public material."])


class ResettingTargetCollection(FakeCollectionAgent):
    def __init__(self, fail_repair=False):
        super().__init__()
        self.fail_repair = fail_repair
        self.repair_inputs = []

    def collect_target_product(self, product_description, product_name, feedback=""):
        self.target_calls.append((product_description, product_name, feedback))
        self._search_texts = {product_name: TARGET_SOURCE}
        return entity(product_name)

    async def run(self, product_description, competitors, feedback=""):
        self.run_feedbacks.append(feedback)
        self._search_texts = {c.name: "Rival's original saved source." for c in competitors.competitors}
        return {c.name: entity(c.name) for c in competitors.competitors}

    async def async_reextract_saved_sources(self, product_name, description, data, sources, feedback=""):
        self.repair_inputs.append(deepcopy((data, sources)))
        self._repair_entities = list(data)
        data[product_name].product_features[0].description = FIXED
        if self.fail_repair:
            self._search_texts[product_name] = "Interrupted replacement source."
            raise ConnectionError("Repair interrupted")
        return data


class TargetScopeQuality(FakeQualityAgent):
    def __init__(self):
        super().__init__()
        self.collection_inputs = []

    async def check_collection(self, competitors_data, original_search_texts, competitor_list=None, attempt=1):
        self.collection_inputs.append(deepcopy((competitors_data, original_search_texts)))
        target = competitors_data.get("Target")
        bad = target is not None and target.product_features[0].description == BAD
        return QualityCheckResult("collection", "CollectionAgent", passed=not bad,
            score=60 if bad else 100, attempt=attempt, hallucination_status="passed",
            issues=[QualityIssue("critical", "citation", "Target.product_features[0].description",
                                "A named kit's source was expanded to every version.")] if bad else [])


def capture(orch):
    saved = {}
    original = orch._save_artifact_json

    def save(name, value):
        saved.setdefault(name, []).append(deepcopy(to_jsonable(value)))
        original(name, value)
    orch._save_artifact_json = save
    return saved


class TargetCollectionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_scope_repair_preserves_sources_and_reaches_every_downstream_in_both_flows(self):
        for graph in (True, False):
            with self.subTest(graph=graph):
                orch = make_orchestrator(competitors=competitor_list(("CompA", "CompB", "CompC")))
                orch.collection_agent = ResettingTargetCollection()
                orch.quality_agent = TargetScopeQuality()
                saved = capture(orch)
                observed = []
                for label in ("dimension", "product", "pricing", "market", "strategy"):
                    agent = getattr(orch, label + "_agent")
                    original = agent.run

                    async def track(*args, _label=label, _original=original, **kwargs):
                        observed.append((_label, deepcopy(kwargs.get("target_product_data"))))
                        return await _original(*args, **kwargs)
                    agent.run = track
                with patch("config.SKIP_QA", False):
                    await (run_graph_quietly(orch, "Generic target", 3) if graph else run_quietly(orch, "Generic target", 3))
                inputs = orch.quality_agent.collection_inputs
                self.assertTrue(all("Target" in data for data, _ in inputs), "Target bypassed collection QA")
                self.assertEqual(len(inputs), 2, "Target scope finding must be repaired and rechecked")
                self.assertTrue(all(sources.get("Target") == TARGET_SOURCE for _, sources in inputs))
                self.assertEqual(set(orch._last_competitors_data), {"CompA", "CompB", "CompC"})
                self.assertEqual(orch._last_target_product_data.product_features[0].description, FIXED)
                self.assertEqual({label for label, _ in observed}, {"dimension", "product", "pricing", "market", "strategy"})
                self.assertTrue(all(target.product_features[0].description == FIXED for _, target in observed))
                self.assertEqual(saved["00_target_product_data.json"][-1]["product_features"][0]["description"], FIXED)
                self.assertEqual(saved["00_target_search_texts.json"][-1], {"Target": TARGET_SOURCE})
                self.assertEqual(set(saved["02_competitors_data.json"][-1]), {"CompA", "CompB", "CompC"})
                before = saved["02_collection_retries/attempt_01_before.json"][0]
                self.assertEqual(before["target_product_data"]["product_features"][0]["description"], BAD)
                self.assertEqual(set(before["competitors_data"]), {"CompA", "CompB", "CompC"})
                self.assertEqual(before["original_search_texts"]["Target"], TARGET_SOURCE)

    async def test_failed_target_repair_rolls_back_and_never_turns_critical_scope_into_a_pass(self):
        for graph in (True, False):
            with self.subTest(graph=graph):
                orch = make_orchestrator()
                orch.collection_agent = ResettingTargetCollection(fail_repair=True)
                orch.quality_agent = TargetScopeQuality()
                saved = capture(orch)
                with patch("config.SKIP_QA", False):
                    await (run_graph_quietly(orch, "Target", 2) if graph else run_quietly(orch, "Target", 2))
                checks = [c for c in orch.quality_agent.timeline.checks if c.phase == "collection"]
                self.assertTrue(all(not c.passed for c in checks), "Unrepaired target critical finding was bypassed")
                self.assertEqual(len(checks), 3)
                self.assertEqual(orch._last_target_product_data.product_features[0].description, BAD)
                self.assertEqual(saved["02_search_texts.json"][-1]["Target"], TARGET_SOURCE)
                self.assertEqual(orch.collection_agent.get_search_texts()["Target"], TARGET_SOURCE)
                self.assertEqual(saved["02_collection_retries/attempt_01_result.json"][-1]["status"], "failed")

    async def test_duplicate_discovery_identities_are_rejected_before_overwrite(self):
        for graph in (True, False):
            for names in (("Target", "CompA"), ("CompA", "CompA")):
                with self.subTest(graph=graph, names=names):
                    orch = make_orchestrator(competitors=competitor_list(names))
                    with self.assertRaisesRegex(ValueError, "[Dd]uplicate|重复"):
                        await (run_graph_quietly(orch, "Target", 2) if graph else run_quietly(orch, "Target", 2))

    async def test_old_node_state_without_target_remains_compatible(self):
        orch = make_orchestrator()
        nodes = AnalysisGraphNodes(orch)
        state = {"competitors_data": {"CompA": entity("CompA")},
                 "original_search_texts": {"CompA": "Saved source"}, "competitor_list": competitor_list(("CompA",))}
        with patch("config.SKIP_QA", False):
            result = await nodes.check_collection_quality(state)
        self.assertTrue(result["qa_collection"].passed)


class TargetCollectionIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_undisclosed_market_share_is_a_scoped_gap_not_a_required_invented_number(self):
        for value in ("", "未知"):
            with self.subTest(value=value):
                agent = QualityAgent()
                target = entity("Target")
                target.market_share = value

                async def review(prompt):
                    self.assertIn("Target", prompt)
                    return {"issues": []}, ""
                agent._request_quality_json = review
                with patch("config.ENABLE_LLM", True):
                    result = await agent.check_collection({"Target": target},
                        {"Target": "Complete public material gives kit conditions but no share for this individual product."})
                self.assertTrue(result.passed, "A completed source review may retain an undisclosed market-share gap")
                self.assertEqual(result.hallucination_status, "passed")
                self.assertEqual(target.market_share, value, "Do not impute zero, a group percentage, or a made-up value")
                self.assertTrue(any(i.field == "Target.market_share" and i.severity == "warning" for i in result.issues))

    def test_an_honest_share_gap_is_not_a_mandatory_supplement_request(self):
        target = entity("Target")
        target.market_share = ""
        result = QualityCheckResult("collection", "CollectionAgent", True, 98,
            hallucination_status="passed", issues=[QualityIssue("warning", "completeness", "Target.market_share", "Scoped evidence gap")])
        missing = QualityAgent().extract_missing_fields(result, {"Target": target})
        self.assertNotIn("market_share", missing.get("Target", []), "A known evidence gap must not become forced factual supplementation")

    async def test_wrong_market_share_still_fails_even_when_undisclosed_shares_are_allowed(self):
        agent = QualityAgent()
        target = entity("Target")
        target.market_share = "90% of all product sales"

        async def review(prompt):
            return {"issues": [{"severity": "critical", "category": "citation", "field": "Target.market_share",
                                "description": "Source is a group-level statistic for a different market."}]}, ""
        agent._request_quality_json = review
        with patch("config.ENABLE_LLM", True):
            result = await agent.check_collection({"Target": target}, {"Target": "Only a group-level statistic is published."})
        self.assertFalse(result.passed)
        self.assertTrue(any(i.field == "Target.market_share" and i.severity == "critical" for i in result.issues))

    async def test_current_source_warnings_are_not_dropped_by_an_earlier_passed_field_cache(self):
        agent = QualityAgent()
        agent._passed_fields.add("Target.strengths")

        async def review(prompt):
            return {"issues": [{"severity": "warning", "category": "citation", "field": "Target.strengths",
                                "description": "Keep this source's unresolved scope caveat."}]}, ""
        agent._request_quality_json = review
        with patch("config.ENABLE_LLM", True):
            result = await agent.check_collection({"Target": entity("Target")}, {"Target": TARGET_SOURCE})
        self.assertTrue(any(i.field == "Target.strengths" and i.severity == "warning" for i in result.issues))

    async def test_cancelled_same_source_repair_restores_cache_and_records_interruption(self):
        orch = make_orchestrator()
        saved = capture(orch)
        original = {"Target": entity("Target")}
        sources = {"Target": TARGET_SOURCE}

        async def cancel(*args):
            orch.collection_agent._search_texts = {"Target": "Partial source cache"}
            raise asyncio.CancelledError()
        orch.collection_agent.async_reextract_saved_sources = cancel
        qa = QualityCheckResult("collection", "CollectionAgent", False, 60, hallucination_status="passed",
            issues=[QualityIssue("critical", "citation", "Target.product_features", "Scope error")])
        with self.assertRaises(asyncio.CancelledError):
            await repair_collection(orch, "Target", "Context", original, sources, qa, 1, {})
        self.assertEqual(orch.collection_agent.get_search_texts(), sources)
        self.assertEqual(saved["02_collection_retries/attempt_01_result.json"][-1]["status"], "interrupted")

    async def test_entity_reviews_keep_full_evidence_and_any_unfinished_entity_fails_the_gate(self):
        agent = QualityAgent()
        calls = []
        warning = {"severity": "warning", "category": "citation", "field": "pricing_tiers",
                   "description": "The quotation retains an unresolved source limitation."}

        async def review(prompt):
            calls.append(prompt)
            return ({"issues": [warning]}, "") if len(calls) == 1 else ({}, "json_parse_error")
        agent._request_quality_json = review
        source_a, source_b = TARGET_SOURCE, "Full rival evidence. " * 900 + " RIVAL_SOURCE_TAIL"
        with patch("config.ENABLE_LLM", True):
            result = await agent.check_collection({"Target": entity("Target"), "CompA": entity("CompA")},
                                                  {"Target": source_a, "CompA": source_b})
        self.assertFalse(result.passed, "An unfinished entity review cannot be hidden behind another entity's pass")
        self.assertEqual(result.hallucination_status, "failed")
        self.assertEqual(len(calls), 2)
        self.assertIn(source_a, calls[0])
        self.assertIn(source_b, calls[1])
        self.assertNotIn("RIVAL_SOURCE_TAIL", calls[0])
        self.assertNotIn("TARGET_SOURCE_TAIL", calls[1])
        self.assertTrue(any(i.description == warning["description"] and i.field.startswith("Target.") for i in result.issues))
        self.assertTrue(any("CompA" in i.description for i in result.issues if i.field == "__hallucination_check__"))

    async def test_target_without_any_original_context_or_snippet_cannot_receive_an_empty_pass(self):
        agent = QualityAgent()
        target = entity("Target")
        for citation in target.citations:
            citation.snippet = ""

        async def review(prompt):
            return {"issues": []}, ""
        agent._request_quality_json = review
        with patch("config.ENABLE_LLM", True):
            result = await agent.check_collection({"Target": target, "CompA": entity("CompA")},
                                                  {"CompA": "Rival evidence cannot stand in for target sources."})
        self.assertFalse(result.passed)
        self.assertEqual(result.hallucination_status, "failed")
        self.assertTrue(any("Target" in i.description for i in result.issues if i.severity == "critical"))

    async def test_full_citation_snippets_are_reviewed_even_without_the_raw_cache(self):
        agent = QualityAgent()
        target = entity("Target")
        target.citations[-1].snippet = "Complete saved quotation " * 900 + " SNIPPET_TAIL"
        calls = []

        async def review(prompt):
            calls.append(prompt)
            return {"issues": []}, ""
        agent._request_quality_json = review
        with patch("config.ENABLE_LLM", True):
            result = await agent.check_collection({"Target": target}, {})
        self.assertEqual(result.hallucination_status, "passed")
        self.assertEqual(len(calls), 1)
        self.assertIn("SNIPPET_TAIL", calls[0])

    async def test_target_cannot_borrow_a_rivals_valid_citation_id(self):
        target, rival = entity("Target"), entity("CompA")
        target.product_features[0].citations = [rival.citations[0].id]
        with patch("config.ENABLE_LLM", False):
            result = await QualityAgent().check_collection({"Target": target, "CompA": rival}, {})
        self.assertFalse(result.passed, "Another entity's source ID must not satisfy target evidence")
        self.assertTrue(any(i.severity == "critical" and i.category == "citation" and "Target" in i.field
                            for i in result.issues))

    async def test_saved_source_repair_cannot_drop_target_or_rewrite_original_citations(self):
        for failure in ("drop_target", "rewrite_source"):
            with self.subTest(failure=failure):
                orch = make_orchestrator()
                original = {"Target": entity("Target"), "CompA": entity("CompA")}
                sources = {"Target": TARGET_SOURCE, "CompA": "Original rival source"}
                before = deepcopy(original)
                saved = capture(orch)

                async def corrupt(*args):
                    data = deepcopy(args[2])
                    if failure == "drop_target":
                        data.pop("Target")
                    else:
                        data["Target"].citations[0].snippet = "A different original fact."
                    return data
                orch.collection_agent.async_reextract_saved_sources = corrupt
                qa = QualityCheckResult("collection", "CollectionAgent", False, 60,
                    hallucination_status="passed", issues=[QualityIssue("critical", "citation", "Target.product_features", "Scope error")])
                updated, new_sources, _ = await repair_collection(orch, "Target", "Context", original, sources, qa, 1, {})
                self.assertEqual(updated, before, "Invalid target/evidence transaction must roll back")
                self.assertEqual(original, before)
                self.assertEqual(new_sources, sources)
                self.assertEqual(saved["02_collection_retries/attempt_01_result.json"][-1]["status"], "failed")

    async def test_reextract_only_exact_affected_entities_and_keep_global_warning_fallback(self):
        for warning_field, expected in ((None, {"Target"}), ("CompA.channels", {"Target", "CompA"}),
                                        ("product_features[*].citations", {"Target", "CompA", "CompB"})):
            with self.subTest(warning_field=warning_field):
                orch = make_orchestrator()
                orch.quality_agent = QualityAgent()
                received = []

                async def reextract(product, description, data, sources, feedback):
                    received.append((set(data), feedback))
                    orch.collection_agent._repair_entities = list(data)
                    return deepcopy(data)
                orch.collection_agent.async_reextract_saved_sources = reextract
                issues = [QualityIssue("critical", "citation", "Target.product_features", "Target scope error")]
                if warning_field:
                    issues.append(QualityIssue("warning", "citation", warning_field, "Keep this additional warning"))
                qa = QualityCheckResult("collection", "CollectionAgent", False, 60,
                                        hallucination_status="passed", issues=issues)
                data = {name: entity(name) for name in ("Target", "CompA", "CompB")}
                await repair_collection(orch, "Target", "Context", data,
                                        {name: "Full source." for name in data}, qa, 1, {})
                self.assertEqual(received[0][0], expected)
                if warning_field:
                    self.assertIn(warning_field, received[0][1])

    def test_collection_prompt_retains_generic_source_scope_and_attribution(self):
        agent = QualityAgent()
        text = agent._prompt_check_collection
        for term in ("目标", "脚注", "套装", "比较对象", "门店", "AI生成", "广告", "用户评论",
                     "excerpt_truncated", "Citation.snippet"):
            self.assertIn(term, text)


if __name__ == "__main__":
    unittest.main()
