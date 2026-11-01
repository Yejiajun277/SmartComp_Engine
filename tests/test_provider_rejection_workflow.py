"""A completed provider refusal is terminal, never a repair/degraded success."""
import contextlib
from copy import deepcopy
import io
import unittest
from unittest.mock import patch

from core.artifact_store import to_jsonable
from models.domain import QualityCheckResult
from tests.test_orchestrator_baseline import FakeQualityAgent, make_orchestrator
from workflow.graph import (route_analysis_quality, route_collection_quality,
                            route_strategy_quality, run_analysis_graph)

REASON = 'provider_content_filter'
PHASES = ('collection', 'product', 'pricing', 'market', 'strategy')


def refusal(phase, *, passed=False):
    result = QualityCheckResult(phase, 'QualityAgent', passed, 0,
        hallucination_status='failed', entity_review_trace=[{'entity': 'CompA', 'completed': False,
        'mode': 'live', 'request_count': 1, 'requests': [{'finish_reason': 'content_filter'}]}])
    result.non_retryable_reason = REASON
    return result


class RefusingQuality(FakeQualityAgent):
    def __init__(self, phase):
        super().__init__()
        self.phase = phase
        self.calls = []

    def result(self, phase, attempt):
        self.calls.append(phase)
        if phase == self.phase and self.calls.count(phase) == 1:
            return refusal(phase)
        return QualityCheckResult(phase, 'QualityAgent', True, 100,
                                  attempt=attempt, hallucination_status='passed')

    async def check_collection(self, *args, attempt=1, **kwargs):
        return self.result('collection', attempt)

    async def check_analysis(self, phase, *args, attempt=1, **kwargs):
        return self.result(phase, attempt)

    async def check_strategy(self, *args, attempt=1, **kwargs):
        return self.result('strategy', attempt)


def fixture(phase):
    orch = make_orchestrator()
    orch.quality_agent = RefusingQuality(phase)
    orch.payloads = {}
    original_save = orch._save_artifact_json
    def save(name, value):
        original_save(name, value)
        orch.payloads[name] = deepcopy(to_jsonable(value))
    orch._save_artifact_json = save
    return orch


class ProviderRejectionWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def test_routes_prioritize_nonretryable_even_over_pass_or_other_retry(self):
        self.assertEqual(route_collection_quality({'qa_collection': refusal('collection', passed=True)}), 'non_retryable')
        self.assertEqual(route_strategy_quality({'qa_strategy': refusal('strategy', passed=True)}), 'non_retryable')
        self.assertEqual(route_analysis_quality({'qa_product': QualityCheckResult('product', 'ProductAgent', False, 0),
            'qa_market': refusal('market')}), 'non_retryable')

    def assert_terminal(self, orch, phase):
        self.assertEqual(orch.quality_agent.calls.count(phase), 1)
        self.assertEqual(orch.quality_agent.feedback_requests, [])
        self.assertEqual(orch.collection_agent.reextract_feedbacks, [])
        self.assertEqual(orch.finalized[-1]['status'], 'failed')
        if phase != 'strategy':
            self.assertNotIn('07_strategy_report.json', orch.saved_artifacts)
        else:
            # Graph persists the generated draft before its QA; preserve that
            # evidence, but never call the successful report finalizer again.
            self.assertLessEqual(orch.saved_artifacts.count('07_strategy_report.json'), 1)
        self.assertEqual(orch.payloads['failed_state.json']['non_retryable_reason'], REASON)
        checks = orch.payloads['qa_timeline.json']['checks']
        rejected = [row for row in checks if row['phase'] == phase]
        self.assertEqual(len(rejected), 1)
        self.assertFalse(rejected[0]['passed'])
        self.assertFalse(rejected[0]['degraded'])
        self.assertEqual(rejected[0]['hallucination_status'], 'failed')
        self.assertEqual(rejected[0]['non_retryable_reason'], REASON)
        self.assertEqual(rejected[0]['entity_review_trace'][0]['requests'][0]['finish_reason'], 'content_filter')
        if phase == 'collection':
            self.assertFalse(orch.dimension_agent.calls)
            self.assertFalse(orch.product_agent.feedbacks)
            self.assertIn('02_competitors_data.json', orch.saved_artifacts)
        if phase != 'strategy':
            self.assertFalse(orch.strategy_agent.feedbacks)
        else:
            self.assertEqual(len(orch.strategy_agent.feedbacks), 1)
        for agent in (orch.product_agent, orch.pricing_agent, orch.market_agent):
            self.assertLessEqual(len(agent.feedbacks), 1)

    async def test_graph_each_quality_phase_fails_without_repair_or_later_work(self):
        for phase in PHASES:
            with self.subTest(phase=phase), patch('config.SKIP_QA', False), contextlib.redirect_stdout(io.StringIO()):
                orch = fixture(phase)
                state = await run_analysis_graph(orch, 'Target', 2)
                self.assertEqual(state['status'], 'failed')
                self.assertEqual(state['error'], REASON)
                self.assertEqual(state['failure']['phase'], phase)
                self.assert_terminal(orch, phase)

    async def test_legacy_each_quality_phase_raises_preserving_failed_artifacts(self):
        for phase in PHASES:
            with self.subTest(phase=phase), patch('config.SKIP_QA', False), contextlib.redirect_stdout(io.StringIO()):
                orch = fixture(phase)
                with self.assertRaisesRegex(RuntimeError, REASON) as caught:
                    await orch._analyze_legacy('Target', 2)
                self.assertEqual(caught.exception.failure['phase'], phase)
                self.assertEqual(caught.exception.failure['non_retryable_reason'], REASON)
                self.assert_terminal(orch, phase)

    async def test_facade_never_returns_rejected_graph_as_completed_report(self):
        with patch('config.SKIP_QA', False), contextlib.redirect_stdout(io.StringIO()):
            orch = fixture('collection')
            with self.assertRaisesRegex(RuntimeError, REASON):
                await orch._analyze_langgraph('Target', 2)
            self.assertEqual(orch._last_status, 'failed')
            self.assert_terminal(orch, 'collection')
