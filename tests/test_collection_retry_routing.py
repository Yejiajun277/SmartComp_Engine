"""Real collection findings must not disappear behind a missing-field repair."""
import unittest
from unittest.mock import patch

import config
from agents.quality_agent import QualityAgent
from models.domain import QualityCheckResult, QualityIssue
from tests.test_orchestrator_baseline import FakeQualityAgent, make_orchestrator, run_quietly
from tests.test_workflow_graph import run_graph_quietly


class MixedCollectionIssues(FakeQualityAgent):
    build_feedback = QualityAgent.build_feedback
    async_build_feedback = QualityAgent.async_build_feedback

    def __init__(self):
        super().__init__()
        self.missing_fields = {"Alpha": ["weaknesses"]}

    async def check_collection(self, competitors_data, original_search_texts,
                               competitor_list=None, attempt=1):
        if attempt > 1:
            return QualityCheckResult("collection", "CollectionAgent", passed=True,
                                      score=100, attempt=attempt, hallucination_status="passed")
        return QualityCheckResult("collection", "CollectionAgent", passed=False,
            score=78, attempt=attempt, hallucination_status="passed", issues=[
                QualityIssue("critical", "completeness", "Alpha.weaknesses", "Missing review"),
                QualityIssue("critical", "completeness", "product_features[*].citations", "Missing IDs"),
                QualityIssue("critical", "citation", "Alpha.pricing_tiers[4].price", "Invented unit"),
                QualityIssue("warning", "citation", "Beta.market_share", "Missing report year"),
            ])


class CollectionRetryRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_preserves_all_findings_when_missing_field_coexists_with_citation_error(self):
        orch = make_orchestrator()
        orch.quality_agent = MixedCollectionIssues()
        with patch.object(config, "SKIP_QA", False):
            await run_graph_quietly(orch, "Category-specific product", 2)
        self.assertEqual(len(orch.collection_agent.run_feedbacks), 2)
        retry_feedback = orch.collection_agent.run_feedbacks[-1]
        for field in ("Alpha.weaknesses", "product_features[*].citations",
                      "Alpha.pricing_tiers[4].price", "Beta.market_share"):
            self.assertIn(field, retry_feedback)

    async def test_legacy_preserves_all_findings_when_missing_field_coexists_with_citation_error(self):
        orch = make_orchestrator()
        orch.quality_agent = MixedCollectionIssues()
        with patch.object(config, "SKIP_QA", False):
            await run_quietly(orch, "Category-specific product", 2)
        self.assertEqual(len(orch.collection_agent.run_feedbacks), 2)
        retry_feedback = orch.collection_agent.run_feedbacks[-1]
        self.assertIn("product_features[*].citations", retry_feedback)
        self.assertIn("Alpha.pricing_tiers[4].price", retry_feedback)
        self.assertIn("Beta.market_share", retry_feedback)

    async def test_unfinished_review_does_not_regenerate_collected_facts(self):
        from tests.test_collection_gate_integrity import UnfinishedCollectionReview
        for graph in (True, False):
            with self.subTest(graph=graph):
                orch = make_orchestrator()
                orch.quality_agent = UnfinishedCollectionReview()
                with patch.object(config, "SKIP_QA", False):
                    await (run_graph_quietly(orch, "Product", 2) if graph
                           else run_quietly(orch, "Product", 2))
                self.assertEqual(orch.collection_agent.run_feedbacks, [""])


if __name__ == "__main__":
    unittest.main()
