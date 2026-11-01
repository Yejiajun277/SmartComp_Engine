"""An incomplete entity review cannot suppress another entity's real repair."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from agents.quality_agent import QualityAgent
from core.artifact_store import to_jsonable
from core.collection_retry import repair_collection
from models.domain import QualityCheckResult, QualityIssue
from tests.test_orchestrator_baseline import FakeCollectionAgent, FakeQualityAgent, make_orchestrator, run_quietly
from tests.test_workflow_graph import run_graph_quietly


def mixed_result(attempt=1, include_fact=True):
    issues = [QualityIssue("critical", "schema", "__hallucination_check__",
                          'Review incomplete ({"CompB": "truncated_output"})')]
    if include_fact:
        issues.insert(0, QualityIssue("critical", "citation", "Target.product_features[0].description",
                                     "A laboratory claim lost its test conditions."))
    result = QualityCheckResult("collection", "CollectionAgent", False, 78,
                               issues=issues, attempt=attempt, hallucination_status="failed")
    result.entity_review_trace = [{"entity": name, "completed": name != "CompB"}
                                  for name in ("Target", "CompA", "CompB")]
    return result


class MixedQuality(FakeQualityAgent):
    build_feedback = QualityAgent.build_feedback
    async_build_feedback = QualityAgent.async_build_feedback

    def __init__(self, final_incomplete=False):
        super().__init__()
        self.final_incomplete = final_incomplete

    async def check_collection(self, data, sources, competitor_list=None, attempt=1):
        if attempt == 1:
            return mixed_result(attempt)
        if self.final_incomplete:
            return mixed_result(attempt, include_fact=False)
        return QualityCheckResult("collection", "CollectionAgent", True, 100,
                                  attempt=attempt, hallucination_status="passed")


class RecordingCollection(FakeCollectionAgent):
    def __init__(self, failure=False, corrupt_source=False):
        super().__init__()
        self.received = []
        self.failure = failure
        self.corrupt_source = corrupt_source

    async def async_reextract_saved_sources(self, product, description, data, sources, feedback="", *, repair_plan=None):
        self.received.append(deepcopy((data, sources, feedback)))
        self._repair_entities = list(data)
        if self.failure:
            self._search_texts = {"Target": "Partial candidate cache"}
            raise ConnectionError("Repair interrupted")
        for item in data.values():
            item.product_features[0].description = "Laboratory result under the named test conditions."
            if self.corrupt_source:
                item.citations[0].snippet = "Changed original source"
        return data


class MixedCollectionQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_flows_repair_only_completed_entity_and_recheck_without_washing_history(self):
        for graph in (True, False):
            with self.subTest(graph=graph):
                orch = make_orchestrator()
                orch.quality_agent = MixedQuality()
                orch.collection_agent = RecordingCollection()
                with patch("config.SKIP_QA", False):
                    await (run_graph_quietly(orch, "Target", 2) if graph else run_quietly(orch, "Target", 2))
                self.assertEqual(len(orch.collection_agent.received), 1)
                data, _, feedback = orch.collection_agent.received[0]
                self.assertEqual(set(data), {"Target"})
                self.assertIn("laboratory claim", feedback)
                checks = [c for c in orch.quality_agent.timeline.checks if c.phase == "collection"]
                self.assertEqual([c.passed for c in checks], [False, True])
                self.assertEqual(checks[0].hallucination_status, "failed")
                self.assertEqual(len(checks[0].issues), 2)
                self.assertIn("Laboratory result", orch._last_target_product_data.product_features[0].description)

    async def test_final_unfinished_review_still_fails_in_both_flows(self):
        for graph in (True, False):
            with self.subTest(graph=graph):
                orch = make_orchestrator()
                orch.collection_agent = RecordingCollection()
                orch.quality_agent = MixedQuality(final_incomplete=True)
                with patch("config.SKIP_QA", False):
                    await (run_graph_quietly(orch, "Target", 2) if graph else run_quietly(orch, "Target", 2))
                self.assertEqual(len(orch.collection_agent.received), 1)
                checks = [c for c in orch.quality_agent.timeline.checks if c.phase == "collection"]
                self.assertEqual(len(checks), 3)
                self.assertTrue(all(not c.passed and c.hallucination_status == "failed" for c in checks))

    async def helper(self, result, *, failure=False, corrupt_source=False):
        from tests.test_target_collection_quality import entity
        orch = make_orchestrator()
        orch.collection_agent = RecordingCollection(failure, corrupt_source)
        orch.quality_agent = QualityAgent()
        data = {name: entity(name) for name in ("Target", "CompA", "CompB")}
        before = deepcopy(data)
        sources = {name: "Complete original source " * 1000 for name in data}
        saved = {}
        orch._save_artifact_json = lambda name, value: saved.__setitem__(name, deepcopy(to_jsonable(value)))
        updated, updated_sources, _ = await repair_collection(orch, "Target", "Context", data, sources,
                                                               result, 1, {}, target_name="Target")
        self.assertEqual(data, before)
        self.assertEqual(updated_sources, sources)
        self.assertEqual(orch.collection_agent.get_search_texts(), sources)
        self.assertEqual(updated["CompA"], before["CompA"])
        self.assertEqual(updated["CompB"], before["CompB"])
        self.assertFalse(result.passed)
        return orch, before, updated, saved

    async def test_incomplete_only_and_issues_owned_by_unfinished_entities_do_not_modify_facts(self):
        for field in (None, "CompB.product_features", "product_features[*].citations"):
            with self.subTest(field=field):
                result = mixed_result(include_fact=False)
                if field:
                    result.issues.append(QualityIssue("critical", "citation", field, "Unconfirmed finding"))
                orch, before, updated, saved = await self.helper(result)
                self.assertEqual(updated, before)
                self.assertEqual(orch.collection_agent.received, [])
                self.assertEqual(saved["02_collection_retries/attempt_01_result.json"]["mode"], "recheck")

    async def test_failed_or_evidence_mutating_mixed_repair_rolls_back_and_preserves_audit(self):
        for failure, corrupt in ((True, False), (False, True)):
            with self.subTest(failure=failure, corrupt=corrupt):
                orch, before, updated, saved = await self.helper(mixed_result(), failure=failure, corrupt_source=corrupt)
                self.assertEqual(len(orch.collection_agent.received), 1)
                self.assertEqual(updated, before)
                audit = saved["02_collection_retries/attempt_01_result.json"]
                self.assertEqual(audit["status"], "failed")
                self.assertEqual(audit["source_fingerprint"], audit["result_source_fingerprint"])
                self.assertEqual(len(saved["02_collection_retries/attempt_01_before.json"]["qa_collection"]["issues"]), 2)

    async def test_legacy_snapshot_failure_map_excludes_unfinished_entity_without_trace(self):
        result = mixed_result()
        result.entity_review_trace = []
        result.issues[-1].description = '幻觉检测未能完成（{"CompB": "truncated_output"}），结果可信度未知'
        result.issues.append(QualityIssue("critical", "citation", "CompB.product_features", "Unconfirmed finding"))
        orch, _, _, _ = await self.helper(result)
        self.assertEqual(len(orch.collection_agent.received), 1)
        self.assertEqual(set(orch.collection_agent.received[0][0]), {"Target"})

    async def test_complete_machine_actual_failure_map_is_supported(self):
        result = mixed_result()
        result.entity_review_trace = []
        result.issues[-1].description = "Review incomplete."
        result.issues[-1].actual = '{"CompB": "json_parse_error"}'
        orch, _, _, _ = await self.helper(result)
        self.assertEqual(len(orch.collection_agent.received), 1)
        self.assertEqual(set(orch.collection_agent.received[0][0]), {"Target"})

    async def test_untrusted_examples_and_malformed_failure_maps_never_authorize_repairs(self):
        samples = [
            ('Example only: {"CompB": []}', ''),
            ('Example only: {"CompB": "truncated_output"}', ''),
            ('{"metadata": {"CompB": "truncated_output"}}', ''),
            ('Review incomplete.', 'prefix {"CompB": "truncated_output"} suffix'),
            ('Review incomplete.', '{"metadata": {"CompB": "truncated_output"}}'),
            ('幻觉检测未能完成（{"CompB": []}），结果可信度未知', ''),
            ('幻觉检测未能完成（{"CompB": "  "}），结果可信度未知', ''),
            ('幻觉检测未能完成（{"CompB": null}），结果可信度未知', ''),
            ('幻觉检测未能完成（{"CompB": "failure", "Unknown": "failure"}），结果可信度未知', ''),
            ('prefix 幻觉检测未能完成（{"CompB": "failure"}），结果可信度未知', ''),
            ('幻觉检测未能完成（{"CompB": "failure"}），结果可信度未知 trailing example', ''),
        ]
        for description, actual in samples:
            with self.subTest(description=description, actual=actual):
                result = mixed_result()
                result.entity_review_trace = []
                result.issues[-1].description = description
                result.issues[-1].actual = actual
                orch, before, updated, saved = await self.helper(result)
                self.assertEqual(updated, before)
                self.assertEqual(orch.collection_agent.received, [])
                self.assertEqual(saved["02_collection_retries/attempt_01_result.json"]["mode"], "recheck")

    async def test_opaque_failed_review_without_trace_cannot_authorize_fact_changes(self):
        result = mixed_result()
        result.entity_review_trace = []
        result.issues[-1].description = "A review could not finish; entity ownership is unknown."
        orch, before, updated, saved = await self.helper(result)
        self.assertEqual(updated, before)
        self.assertEqual(orch.collection_agent.received, [])
        self.assertEqual(saved["02_collection_retries/attempt_01_result.json"]["mode"], "recheck")


if __name__ == "__main__":
    unittest.main()
