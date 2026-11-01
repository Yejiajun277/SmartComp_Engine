"""Unknown provider usage stays separate from known billed token subtotals."""
import unittest

from core.orchestrator import Orchestrator


class TokenUsageSummaryTests(unittest.TestCase):
    def test_legacy_valid_usage_and_known_zero_remain_compatible(self):
        summary = Orchestrator._build_token_summary([
            {'agent_id': 'A', 'prompt_tokens': 100, 'completion_tokens': 20},
            {'agent_id': 'A', 'prompt_tokens': 0, 'completion_tokens': 0,
             'usage_known': True, 'usage_reported': True}])
        self.assertEqual(summary['total_tokens'], 120)
        self.assertIn('known_subtotal', summary)
        self.assertEqual(summary['known_subtotal'], 120)
        self.assertEqual(summary['unknown_call_count'], 0)
        self.assertTrue(summary['usage_complete'])
        self.assertEqual(summary['per_agent']['A']['known_subtotal'], 120)
        self.assertTrue(summary['per_agent']['A']['usage_complete'])

    def test_explicit_unknown_overrides_placeholder_or_positive_counts(self):
        summary = Orchestrator._build_token_summary([
            {'agent_id': 'A', 'prompt_tokens': 7, 'completion_tokens': 3},
            {'agent_id': 'A', 'prompt_tokens': 0, 'completion_tokens': 0,
             'usage_known': False, 'usage_reported': False, 'usage_reservation_tokens': 6000},
            {'agent_id': 'B', 'prompt_tokens': 999, 'completion_tokens': 88,
             'usage_known': False, 'usage_reported': True, 'usage_reservation_tokens': 7000},
            {'agent_id': 'B', 'prompt_tokens': 1, 'completion_tokens': 1,
             'usage_known': True, 'usage_reported': False, 'usage_reservation_tokens': 8000}])
        self.assertEqual(summary['total_calls'], 4)
        self.assertEqual(summary['total_tokens'], 10)
        self.assertEqual(summary['known_subtotal'], 10)
        self.assertEqual(summary['unknown_call_count'], 3)
        self.assertFalse(summary['usage_complete'])
        self.assertEqual(summary['usage_reservation_tokens'], 21000)
        self.assertEqual(summary['per_agent']['A']['unknown_call_count'], 1)
        self.assertEqual(summary['per_agent']['B']['known_subtotal'], 0)
        self.assertEqual(summary['per_agent']['B']['usage_reservation_tokens'], 15000)

    def test_unknown_uses_max_request_reservation_without_counting_reasoning_twice(self):
        summary = Orchestrator._build_token_summary([
            {'agent_id': 'A', 'prompt_tokens': 20, 'completion_tokens': 5, 'reasoning_tokens': 4,
             'usage_known': True, 'usage_reported': True, 'usage_reservation_tokens': 99999},
            {'agent_id': 'A', 'prompt_tokens': 0, 'completion_tokens': 0, 'usage_known': False,
             'request_bytes': 100, 'max_completion_tokens': 50, 'max_tokens': 60,
             'usage_reservation_tokens': 3000},
            {'agent_id': 'A', 'prompt_tokens': 0, 'completion_tokens': 0, 'usage_reported': False,
             'request_bytes': 200, 'max_completion_tokens': 100, 'usage_reservation_tokens': 8000}])
        self.assertIn('known_subtotal', summary)
        self.assertEqual(summary['known_subtotal'], 25)
        self.assertEqual(summary['usage_reservation_tokens'], 100 + 60 + 4096 + 8000)
        self.assertEqual(summary['per_agent']['A']['usage_reservation_tokens'], summary['usage_reservation_tokens'])

    def test_invalid_or_missing_usage_is_unknown_and_search_is_not_an_llm_call(self):
        rows = [{'agent_id': 'A', 'prompt_tokens': True, 'completion_tokens': 1},
                {'agent_id': 'A', 'prompt_tokens': -1, 'completion_tokens': 1},
                {'agent_id': 'A', 'prompt_tokens': 2},
                {'type': 'search', 'prompt_tokens': 9000, 'completion_tokens': 9000}]
        summary = Orchestrator._build_token_summary(rows)
        self.assertEqual(summary['total_calls'], 3)
        self.assertEqual(summary['known_subtotal'], 0)
        self.assertEqual(summary['unknown_call_count'], 3)
        self.assertFalse(summary['usage_complete'])

    def test_legacy_zero_placeholders_are_unknown_but_positive_pair_is_known(self):
        rows = [{'agent_id': 'A', 'prompt_tokens': 0, 'completion_tokens': 0,
                 'finish_reason': finish} for finish in ('content_filter', '', 'stop')]
        rows.append({'agent_id': 'A', 'prompt_tokens': 100, 'completion_tokens': 25, 'total_tokens': 0})
        summary = Orchestrator._build_token_summary(rows)
        self.assertEqual(summary['known_subtotal'], 125)
        self.assertEqual(summary['unknown_call_count'], 3)
        self.assertFalse(summary['usage_complete'])
        self.assertIsNone(summary['usage_reservation_tokens'])
        self.assertIsNone(summary['per_agent']['A']['usage_reservation_tokens'])

    def test_missing_reservation_keeps_partial_bound_separate_from_available_upper_bound(self):
        summary = Orchestrator._build_token_summary([
            {'agent_id': 'A', 'prompt_tokens': 0, 'completion_tokens': 0,
             'usage_known': False, 'usage_reservation_tokens': 6000},
            {'agent_id': 'A', 'prompt_tokens': 0, 'completion_tokens': 0,
             'usage_reported': False, 'request_bytes': 0, 'max_completion_tokens': 8192,
             'usage_reservation_tokens': 0}])
        self.assertIsNone(summary['usage_reservation_tokens'])
        self.assertEqual(summary['usage_reservation_known_subtotal'], 6000)
        self.assertFalse(summary['usage_reservation_complete'])
        self.assertFalse(summary['per_agent']['A']['usage_reservation_complete'])
