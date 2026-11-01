"""Provider refusal is terminal, never an incomplete JSON retry or known zero cost."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from agents.quality_agent import QualityAgent
from core.llm_client import _mimo_response, get_last_usage
from models.domain import MarketAnalysis, PricingAnalysis, ProductAnalysis, StrategyReport
import tests.test_mimo_completion_contract as native_contract
from tests.test_target_collection_quality import entity


class ProviderRefusalTests(unittest.IsolatedAsyncioTestCase):
    setUp = native_contract.NativeCompletionContractTests.setUp
    answer = staticmethod(native_contract.NativeCompletionContractTests.answer)

    def refused(self, content='The request was rejected because it was considered high risk'):
        body = self.answer(content=content, finish='content_filter')
        body.pop('usage')
        return body

    async def test_sync_and_async_refusal_cannot_become_successful_json(self):
        for asynchronous in [False, True]:
            with self.subTest(asynchronous=asynchronous):
                self.responses = [(self.refused('{"issues": []}'), 200)]
                agent = QualityAgent()
                result, reason = (await agent.async_ask_llm_json_with_reason('same facts')
                                  if asynchronous else agent.ask_llm_json_with_reason('same facts'))
                self.assertEqual(result, {})
                self.assertEqual(reason, 'provider_content_filter')
                self.assertFalse(agent.llm_logs[-1]['success'])
                self.assertEqual(agent.llm_logs[-1]['parse_error'], 'provider_content_filter')

    async def test_refusal_stops_first_request_and_blocks_same_snapshot_without_fake_reuse(self):
        self.responses = [(self.refused(), 200), (self.answer(), 200)]
        agent = QualityAgent()
        result, reason = await agent._request_quality_json('same complete facts')
        self.assertFalse(result)
        self.assertEqual(reason, 'provider_content_filter')
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(len(agent._last_quality_request_trace['requests']), 1)
        result, reason = await agent._request_quality_json('same complete facts')
        self.assertFalse(result)
        self.assertEqual(reason, 'provider_content_filter')
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(agent._last_quality_request_trace['requests'], [])
        self.assertFalse(agent._last_quality_request_trace['cacheable'])
        # A changed context is not the provider-rejected fingerprint.
        result, reason = await agent._request_quality_json('different complete facts')
        self.assertEqual(result, {'issues': []})
        self.assertEqual(reason, '')
        self.assertEqual(len(self.payloads), 2)

    async def test_collection_stops_unstarted_entities_and_next_round_remains_terminal(self):
        self.responses = [(self.refused(), 200)] * 4
        agent = QualityAgent()
        facts = {'Apple': entity('Apple'), 'Rival': entity('Rival')}
        sources = {'Apple': 'Full Apple evidence', 'Rival': 'Full Rival evidence'}
        with patch('config.ENABLE_LLM', True):
            first = await agent.check_collection(facts, sources, attempt=1)
            second = await agent.check_collection(facts, sources, attempt=2)
        for check in [first, second]:
            self.assertFalse(check.passed)
            self.assertFalse(check.degraded)
            self.assertEqual(check.hallucination_status, 'failed')
            self.assertEqual(check.non_retryable_reason, 'provider_content_filter')
            self.assertTrue(all(not trace['completed'] for trace in check.entity_review_trace))
            self.assertTrue(all(trace['mode'] != 'reuse' for trace in check.entity_review_trace))
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(agent._collection_review_cache, {})

    async def test_analysis_and_strategy_preserve_terminal_refusal(self):
        analyses = [ProductAnalysis(), PricingAnalysis(), MarketAnalysis()]
        with patch('config.ENABLE_LLM', True):
            for kind, analysis in zip(['product', 'pricing', 'market'], analyses):
                with self.subTest(kind=kind):
                    self.responses = [(self.refused(), 200)]
                    check = await QualityAgent().check_analysis(kind, analysis, {'Rival': entity('Rival')})
                    self.assertFalse(check.passed)
                    self.assertEqual(check.non_retryable_reason, 'provider_content_filter')
            self.responses = [(self.refused(), 200)]
            check = await QualityAgent().check_strategy(StrategyReport('Target'), *analyses)
            self.assertFalse(check.passed)
            self.assertEqual(check.non_retryable_reason, 'provider_content_filter')

    async def test_missing_usage_is_unknown_with_reservation_but_real_zero_is_known(self):
        self.responses = [(self.refused(), 200)]
        agent = QualityAgent()
        await agent.async_ask_llm_json_with_reason('Complete saved evidence', max_tokens=16384, thinking='enabled')
        log = agent.llm_logs[-1]
        self.assertFalse(log['usage_known'])
        self.assertFalse(log['usage_reported'])
        # Int fields remain legacy-compatible placeholders, not a claim of known zero.
        self.assertEqual(log['prompt_tokens'], 0)
        self.assertEqual(log['completion_tokens'], 0)
        body_bytes = len(json.dumps(self.payloads[-1], ensure_ascii=False, separators=(',', ':')).encode())
        self.assertEqual(log['request_bytes'], body_bytes)
        self.assertEqual(log['usage_reservation_tokens'], body_bytes + 16384 + 4096)
        self.assertFalse(get_last_usage()['usage_known'])
        zero = self.answer()
        zero['usage'] = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        response = _mimo_response(zero, 1)
        self.assertTrue(response['usage_known'])
        self.assertTrue(response['usage_reported'])
        self.assertEqual(response['total_tokens'], 0)

    async def test_prior_unreported_transport_attempt_keeps_whole_call_unknown(self):
        error = {'error': {'type': 'server_error', 'code': 'offline', 'message': 'offline'}}
        for asynchronous in [False, True]:
            with self.subTest(asynchronous=asynchronous):
                self.responses = [(error, 503), (self.answer(), 200)]
                agent = QualityAgent()
                with patch('core.llm_client.time.sleep'), patch('core.llm_client.asyncio.sleep', AsyncMock()):
                    if asynchronous:
                        await agent.async_ask_llm_json_with_reason('facts', max_tokens=123)
                    else:
                        agent.ask_llm_json_with_reason('facts', max_tokens=123)
                log = agent.llm_logs[-1]
                self.assertFalse(log['usage_known'])
                self.assertTrue(log['usage_reported'])
                self.assertEqual(log['prompt_tokens'], 100)
                self.assertEqual(log['completion_tokens'], 25)
                self.assertEqual(log['usage_reservation_tokens'], 2 * (log['request_bytes'] + 123 + 4096))

    async def test_exhausted_timeout_keeps_payload_reservation_for_both_attempts(self):
        agent = QualityAgent()
        with patch('httpx.AsyncClient.post', AsyncMock(side_effect=httpx.TimeoutException('offline'))):
            await agent.async_ask_llm_json_with_reason('facts', max_tokens=123)
        log = agent.llm_logs[-1]
        self.assertFalse(log['usage_known'])
        self.assertFalse(log['usage_reported'])
        self.assertGreater(log['request_bytes'], 0)
        self.assertEqual(log['usage_reservation_tokens'], 2 * (log['request_bytes'] + 123 + 4096))


if __name__ == '__main__':
    unittest.main()
