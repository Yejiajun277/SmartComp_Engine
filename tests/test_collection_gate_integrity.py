"""A completed data collection is not a completed semantic review."""
import unittest
from unittest.mock import patch

import config
from models.domain import QualityCheckResult, QualityIssue
from tests.test_orchestrator_baseline import FakeQualityAgent, make_orchestrator, run_quietly
from tests.test_workflow_graph import run_graph_quietly


class UnfinishedCollectionReview(FakeQualityAgent):
    async def check_collection(self, competitors_data, original_search_texts,
                               competitor_list=None, attempt=1):
        return QualityCheckResult(
            "collection", "CollectionAgent", passed=False, score=97, attempt=attempt,
            hallucination_status="failed", issues=[QualityIssue(
                "warning", "hallucination", "__hallucination_check__",
                "The model review was truncated; factual correctness is unknown.")])


class CollectionGateIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_never_turns_unfinished_review_into_pass_after_retry(self):
        orch = make_orchestrator()
        orch.quality_agent = UnfinishedCollectionReview()
        with patch.object(config, "SKIP_QA", False):
            state = await run_graph_quietly(orch, "Category-specific product", 2)
        checks = [c for c in state["report"].qa_timeline.checks if c.phase == "collection"]
        self.assertEqual([c.attempt for c in checks], [1, 2, 3])
        self.assertTrue(all(not c.passed for c in checks))
        self.assertEqual(state["status"], "completed_degraded")

    async def test_legacy_never_turns_unfinished_review_into_pass_after_retry(self):
        orch = make_orchestrator()
        orch.quality_agent = UnfinishedCollectionReview()
        with patch.object(config, "SKIP_QA", False):
            report = await run_quietly(orch, "Category-specific product", 2)
        checks = [c for c in report.qa_timeline.checks if c.phase == "collection"]
        self.assertEqual([c.attempt for c in checks], [1, 2, 3])
        self.assertTrue(all(not c.passed for c in checks))


if __name__ == "__main__":
    unittest.main()
