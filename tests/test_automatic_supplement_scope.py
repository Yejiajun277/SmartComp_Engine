"""Automatic supplements request one field and reject partial or untyped output."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from models.domain import Citation, PricingTier
from tests.test_collection_citation_binding import SourceSearch, payload


class AutomaticSupplementScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_collection_retains_its_real_source_context_for_quality_review(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = CollectionAgent()
                agent.search_client = SourceSearch()

                def call(*args, **kwargs):
                    return {'content': json.dumps(payload('Target:q0:r0', 'Target:q0:r0')),
                            'finish_reason': 'stop'}

                async def async_call(*args, **kwargs):
                    return call(*args, **kwargs)

                with patch('config.ENABLE_LLM', True), patch('agents.base_agent.llm_call', call), \
                     patch('agents.base_agent.async_llm_call', async_call):
                    if asynchronous:
                        await agent.async_collect_target_product('Current category context', 'Target')
                    else:
                        agent.collect_target_product('Current category context', 'Target')
                self.assertIn('Target', agent.get_search_texts())
                self.assertIn('SOURCE_EVIDENCE_MARKER', agent.get_search_texts()['Target'])
                self.assertIn('Target:q0:r0', agent.get_search_texts()['Target'])

    async def supplement(self, field, response, *, asynchronous, finish='stop'):
        agent = CollectionAgent()
        agent.search_client = SourceSearch()
        agent.restore_source_snapshot({'Rival': 'Original source retained.'})
        self.requests = []

        def call(system, prompt, **kwargs):
            self.requests.append(prompt)
            return {'content': json.dumps(response), 'finish_reason': finish}

        async def async_call(*args, **kwargs):
            return call(*args, **kwargs)

        existing = [Citation('Rival:q0:r0', 'Original', 'https://example.test/original')]
        value = '' if field == 'market_share' else [PricingTier('Unknown offer', '')]
        before = deepcopy(value)
        method = ('_async_' if asynchronous else '_') + (
            'supplement_market_share' if field == 'market_share' else 'supplement_pricing')
        args = ('Rival', value, existing) if field == 'market_share' else ('Rival', 'Target', value, existing)
        with patch('config.ENABLE_LLM', True), patch('agents.base_agent.llm_call', call), \
             patch('agents.base_agent.async_llm_call', async_call):
            result = await getattr(agent, method)(*args) if asynchronous else getattr(agent, method)(*args)
        return agent, before, result

    @staticmethod
    def payload(field):
        if field == 'market_share':
            return {field: 'The source has no market-share statistic for this model.'}
        return {field: [{'tier_name': 'Selected offer', 'price': '399 yuan/night',
                         'features': ['Only selected city and date'],
                         'citations': ['Rival:sup_price_0:r1']}]}

    async def test_missing_field_request_does_not_reextract_the_entire_entity(self):
        # Live reproduction: a market supplement requested the entire competitor
        # schema at 2048 tokens, exhausting the budget on unrelated fields.
        for asynchronous in (False, True):
            for field in ('market_share', 'pricing_tiers'):
                with self.subTest(asynchronous=asynchronous, field=field):
                    agent, _, (value, sources) = await self.supplement(
                        field, self.payload(field), asynchronous=asynchronous)
                    self.assertEqual(len(self.requests), 1)
                    self.assertIn('"' + field + '"', self.requests[0])
                    for unrelated in {'product_features', 'strengths', 'weaknesses', 'user_reviews',
                                      'channels', 'market_share', 'pricing_tiers'} - {field}:
                        self.assertNotIn('"' + unrelated + '"', self.requests[0])
                    self.assertIn('SOURCE_EVIDENCE_MARKER', self.requests[0])
                    self.assertEqual(len(agent.search_client.queries), 2)
                    self.assertTrue(sources)
                    if field == 'market_share':
                        self.assertEqual(value, self.payload(field)[field])
                    else:
                        self.assertEqual(value[-1].citations, ['Rival:sup_price_0:r1'])
                        self.assertEqual(value[-1].features, ['Only selected city and date'])

    async def test_even_parseable_truncated_supplements_do_not_change_facts(self):
        for asynchronous in (False, True):
            for field in ('market_share', 'pricing_tiers'):
                with self.subTest(asynchronous=asynchronous, field=field):
                    agent, before, (value, sources) = await self.supplement(
                        field, self.payload(field), asynchronous=asynchronous, finish='length')
                    self.assertEqual(value, before)
                    self.assertTrue(sources)
                    self.assertIn('Original source retained.', agent.get_search_texts()['Rival'])

    async def test_bad_field_shapes_cannot_be_normalized_into_accepted_facts(self):
        cases = [
            ('market_share', {'market_share': {'estimate': '10%'}}),
            ('market_share', {'market_share': ['10%']}),
            ('pricing_tiers', {'pricing_tiers': [{'tier_name': 'Offer', 'price': '399',
                                                 'features': {'condition': 'selected date'}}]}),
        ]
        for asynchronous in (False, True):
            for field, payload in cases:
                with self.subTest(asynchronous=asynchronous, field=field, payload=payload):
                    _, before, (value, _) = await self.supplement(field, payload, asynchronous=asynchronous)
                    self.assertEqual(value, before)

    async def test_explicit_unknown_is_allowed_without_manufacturing_a_quote_or_share(self):
        for asynchronous in (False, True):
            for field, missing in [('market_share', ''), ('pricing_tiers', [])]:
                with self.subTest(asynchronous=asynchronous, field=field):
                    _, before, (value, _) = await self.supplement(field, {field: missing}, asynchronous=asynchronous)
                    self.assertEqual(value, before)


if __name__ == '__main__':
    unittest.main()
