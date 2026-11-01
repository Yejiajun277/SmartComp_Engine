"""Repair failed collection facts without replacing their evidence snapshot."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from tests.collection_repair_support import reviewed_plan, wire_patch
from core.artifact_store import to_jsonable
from core.collection_retry import collection_retry_mode, repair_collection
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier, QualityCheckResult, QualityIssue
from tests.test_collection_citation_binding import payload, SourceSearch
from tests.test_collection_retry_routing import MixedCollectionIssues
from tests.test_orchestrator_baseline import FakeCollectionAgent, make_orchestrator, run_quietly
from tests.test_workflow_graph import run_graph_quietly


def snapshot():
    citation = Citation("Rival:q0:r0", "Original", "https://example.test/original",
                        snippet="399 yuan/night only for selected city/date; product has a feature.")
    return {"Rival": CompetitorData("Rival", product_features=[FeatureItem("Old", "Old fact", [citation.id])],
        pricing_tiers=[PricingTier("Offer", "399 selected city/date", citations=[citation.id])],
        market_share="Old scope must be corrected.", citations=[citation], search_sources=["Original discovery."])}


class FailedSearch(SourceSearch):
    def batch_search(self, queries):
        self.queries.extend(queries)
        return [{"query": q, "result": None, "references": [], "error": "plan usage limit"} for q in queries]


class CollectionSavedSourceRepairTests(unittest.IsolatedAsyncioTestCase):
    def transport(self, response, finish="stop"):
        self.requests = []

        def sync_transport(system, prompt, **kwargs):
            self.requests.append(prompt)
            return {"content": json.dumps(response), "finish_reason": finish}

        async def async_transport(*args, **kwargs):
            return sync_transport(*args, **kwargs)

        return sync_transport, async_transport

    async def test_complex_scope_error_routes_to_saved_source_extraction(self):
        qa = QualityCheckResult("collection", "CollectionAgent", passed=False, score=88,
            hallucination_status="found", issues=[QualityIssue("critical", "citation", "Rival.market_share", "scope")])
        self.assertEqual(collection_retry_mode(qa, {}), "reextract")

    async def test_saved_source_reextract_is_typed_zero_search_and_keeps_full_feedback(self):
        agent = CollectionAgent()
        agent.search_client = FailedSearch()
        original = snapshot()
        before = deepcopy(original)
        sources = {"Rival": "Original source snapshot " * 1200}
        response = payload()
        response["market_share"] = ""  # Explicitly remove an unsupported scope claim.
        for field in ("product_features", "pricing_tiers"):
            response[field][0]["citations"] = ["Rival:q0:r0"]
        response["pricing_tiers"][0]["features"] = list(original["Rival"].pricing_tiers[0].features)
        response = wire_patch(original, response)
        sync_call, async_call = self.transport(response)
        feedback = "ALL_ISSUES_BEGIN " + "scope condition; " * 1200 + " ALL_ISSUES_END"
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", async_call):
            updated = await agent.async_reextract_saved_sources("Target", "Product context", original, sources, feedback, repair_plan=reviewed_plan(original))
        self.assertEqual(agent.search_client.queries, [])
        self.assertIn("ALL_ISSUES_END", self.requests[0])
        self.assertIn("Rival:q0:r0", self.requests[0])
        self.assertIn("only for selected city/date", self.requests[0])
        self.assertIsInstance(updated["Rival"].product_features[0], FeatureItem)
        self.assertIsInstance(updated["Rival"].pricing_tiers[0], PricingTier)
        self.assertEqual(updated["Rival"].pricing_tiers[0].citations, ["Rival:q0:r0"])
        self.assertEqual(updated["Rival"].market_share, "")
        self.assertEqual(updated["Rival"].citations, before["Rival"].citations)
        self.assertEqual(updated["Rival"].search_sources, before["Rival"].search_sources)
        self.assertEqual(original, before)
        self.assertEqual(agent.get_search_texts(), sources)
        self.assertEqual(agent.get_repair_outcomes()[0]["status"], "accepted")

    async def test_incomplete_bad_shape_or_truncated_reextract_preserves_snapshot(self):
        bad_shape = payload()
        bad_shape["pricing_tiers"] = "not an array"
        for response, finish in (({}, "stop"), ({"market_share": None}, "stop"),
                                  (bad_shape, "stop"), (payload(), "length")):
            with self.subTest(response=response, finish=finish):
                agent = CollectionAgent()
                agent.search_client = FailedSearch()
                original = snapshot()
                before = deepcopy(original)
                sources = {"Rival": "Existing real source."}
                _, async_call = self.transport(response, finish)
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", async_call):
                    updated = await agent.async_reextract_saved_sources("Target", "Context", original, sources, "fix scope", repair_plan=reviewed_plan(original))
                self.assertEqual(updated, before)
                self.assertEqual(original, before)
                self.assertEqual(agent.get_search_texts(), sources)
                self.assertEqual(agent.search_client.queries, [])
                self.assertEqual(agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_raw_invalid_text_schema_cannot_be_normalized_into_a_successful_repair(self):
        for invalid in (None, {"estimate": "399"}, ["selected city"]):
            for repair in ("saved", "sync_supplement", "async_supplement"):
                with self.subTest(invalid=invalid, repair=repair):
                    agent = CollectionAgent()
                    agent.search_client = SourceSearch()
                    original = snapshot()
                    before = deepcopy(original)
                    response = payload()
                    response["market_share"] = invalid
                    sync_call, async_call = self.transport(response)
                    with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", sync_call), \
                         patch("agents.base_agent.async_llm_call", async_call):
                        if repair == "saved":
                            updated = await agent.async_reextract_saved_sources(
                                "Target", "Context", original, {"Rival": "Original source."}, "fix", repair_plan=reviewed_plan(original))
                        elif repair == "sync_supplement":
                            updated = agent.supplement_missing_fields("Target", original, {"Rival": ["market_share"]})
                        else:
                            updated = await agent.async_supplement_missing_fields("Target", original, {"Rival": ["market_share"]})
                    self.assertEqual(updated, before)
                    self.assertEqual(agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_targeted_supplement_does_not_validate_or_clear_unrequested_fields(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = CollectionAgent()
                agent.search_client = SourceSearch()
                original = snapshot()
                original["Rival"].market_share = "Original report states 87% in its limited market."
                original["Rival"].citations[0].snippet += " Original report states 87% in its limited market."
                agent._last_search_texts = {"Rival": "Bounded search context omits that old statistic."}
                sync_call, async_call = self.transport({"weaknesses": "Source describes a limited service condition."})
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", sync_call), \
                     patch("agents.base_agent.async_llm_call", async_call):
                    updated = (await agent.async_supplement_missing_fields("Target", original, {"Rival": ["weaknesses"]})
                               if asynchronous else agent.supplement_missing_fields("Target", original, {"Rival": ["weaknesses"]}))
                self.assertEqual(updated["Rival"].market_share, original["Rival"].market_share)
                self.assertEqual(agent.get_repair_outcomes()[0]["status"], "accepted")

    async def test_malformed_nested_price_feature_cannot_commit(self):
        response = payload()
        response["pricing_tiers"][0]["features"] = [{"unexpected": "object"}]
        agent = CollectionAgent()
        original = snapshot()
        _, async_call = self.transport(response)
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", async_call):
            updated = await agent.async_reextract_saved_sources("Target", "Context", original,
                                                               {"Rival": "Original source."}, "fix", repair_plan=reviewed_plan(original))
        self.assertEqual(updated, original)
        self.assertEqual(agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_missing_saved_evidence_does_not_call_model_or_search(self):
        agent = CollectionAgent()
        agent.search_client = FailedSearch()
        original = {"Rival": CompetitorData("Rival", strengths="Unreviewed old claim.")}
        _, async_call = self.transport(payload())
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", async_call):
            updated = await agent.async_reextract_saved_sources("Target", "Context", original, {}, "fix", repair_plan=reviewed_plan(original))
        self.assertEqual(updated, original)
        self.assertEqual(self.requests, [])
        self.assertEqual(agent.search_client.queries, [])

    async def test_failed_search_or_failed_extraction_does_not_clear_supplemented_fields(self):
        for asynchronous in (False, True):
            for search_class in (FailedSearch, SourceSearch):
                with self.subTest(asynchronous=asynchronous, search_class=search_class):
                    agent = CollectionAgent()
                    agent.search_client = search_class()
                    agent._last_search_texts = {"Rival": "Original source snapshot."}
                    original = snapshot()
                    before = deepcopy(original)
                    sync_call, async_call = self.transport({})
                    with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", sync_call), \
                         patch("agents.base_agent.async_llm_call", async_call):
                        fields = {"Rival": ["market_share", "product_features", "pricing_tiers"]}
                        updated = (await agent.async_supplement_missing_fields("Target", original, fields)
                                   if asynchronous else agent.supplement_missing_fields("Target", original, fields))
                    self.assertEqual(updated, before)
                    self.assertEqual(original, before)
                    self.assertEqual(agent.get_search_texts(), {"Rival": "Original source snapshot."})
                    self.assertTrue(all(outcome["status"] == "failed" for outcome in agent.get_repair_outcomes()))
                    if search_class is SourceSearch:
                        self.assertTrue(agent.get_repair_outcomes()[0]["acquired_citations"])

    async def test_all_failed_main_searches_do_not_replace_source_cache(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = CollectionAgent()
                agent.search_client = FailedSearch()
                agent._last_search_texts = {"Rival": "Original source snapshot."}
                args = ("Target", "Context", "Rival", ["query"])
                with patch("config.ENABLE_LLM", True):
                    if asynchronous:
                        await agent._async_collect_entity(*args)
                    else:
                        agent._collect_entity(*args)
                self.assertEqual(agent.get_search_texts(), {"Rival": "Original source snapshot."})


class RepairObserverCollection(FakeCollectionAgent):
    def __init__(self):
        super().__init__()
        self.reextract_feedbacks = []
        self.before_repair = None
        self._search_texts = {name: ("Full original evidence " * 1200 + " FULL_SOURCE_TAIL")
                              for name in ("CompA", "CompB")}

    async def async_reextract_saved_sources(self, product_name, product_description, data, sources, feedback, *, repair_plan=None):
        self.before_repair()
        self.reextract_feedbacks.append(feedback)
        return deepcopy(data)

    def get_repair_outcomes(self):
        return [{"entity": "CompA", "status": "failed", "reason": "json_parse_error"}]


class CollectionRetryArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_and_legacy_archive_full_snapshot_before_zero_search_repair(self):
        for graph in (True, False):
            with self.subTest(graph=graph):
                orch = make_orchestrator()
                orch.quality_agent = MixedCollectionIssues()
                orch.collection_agent = RepairObserverCollection()
                saved = {}
                orch._save_artifact_json = lambda name, value: saved.__setitem__(name, deepcopy(to_jsonable(value)))

                def check_before():
                    self.assertIn("02_collection_retries/attempt_01_before.json", saved)
                    before = saved["02_collection_retries/attempt_01_before.json"]
                    self.assertTrue(before["competitors_data"])
                    self.assertEqual(before["original_search_texts"], orch.collection_agent.get_search_texts())
                    self.assertTrue(all(text.endswith("FULL_SOURCE_TAIL") and len(text) > 20000
                                        for text in before["original_search_texts"].values()))
                    self.assertEqual(len(before["qa_collection"]["issues"]), 4)

                orch.collection_agent.before_repair = check_before
                with patch("config.SKIP_QA", False):
                    await (run_graph_quietly(orch, "Product context", 2) if graph
                           else run_quietly(orch, "Product context", 2))
                self.assertEqual(orch.collection_agent.run_feedbacks, [""])
                self.assertEqual(len(orch.collection_agent.reextract_feedbacks), 1)
                result = saved["02_collection_retries/attempt_01_result.json"]
                self.assertEqual(result["mode"], "reextract")
                self.assertEqual(result["evidence_mode"], "saved_sources")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(len(result["source_fingerprint"]), 64)
                self.assertEqual(result["source_fingerprint"], result["result_source_fingerprint"])
                self.assertIn("Alpha.pricing_tiers[4].price", orch.collection_agent.reextract_feedbacks[0])

    async def test_exception_preserves_saved_facts_and_restores_agent_source_cache(self):
        orch = make_orchestrator()
        agent = CollectionAgent()
        orch.collection_agent = agent
        agent._last_search_texts = {"Rival": "Original source."}
        original = snapshot()
        sources = deepcopy(agent.get_search_texts())
        saved = {}
        orch._save_artifact_json = lambda name, value: saved.__setitem__(name, deepcopy(to_jsonable(value)))

        async def interrupted(*args, **kwargs):
            agent._last_search_texts["Rival"] = "Partial candidate source cache."
            raise ConnectionError("Interrupted extraction")

        agent.async_reextract_saved_sources = interrupted
        qa = QualityCheckResult("collection", "CollectionAgent", passed=False, score=88,
            hallucination_status="found", issues=[QualityIssue("critical", "citation", "Rival.market_share", "scope")])
        updated, updated_sources, _ = await repair_collection(orch, "Target", "Context", original, sources, qa, 1, {})
        self.assertEqual(updated, original)
        self.assertEqual(updated_sources, sources)
        self.assertEqual(agent.get_search_texts(), sources)
        result = saved["02_collection_retries/attempt_01_result.json"]
        self.assertEqual(result["status"], "failed")
        self.assertIn("ConnectionError", result["reason"])
        self.assertFalse(qa.passed)


if __name__ == "__main__":
    unittest.main()
