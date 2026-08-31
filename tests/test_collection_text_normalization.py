# -*- coding: utf-8 -*-
"""Regression tests for malformed LLM values in collection text fields."""

import unittest
from unittest.mock import patch

import config
import models.domain as domain
from agents.collection_agent import CollectionAgent
from agents.quality_agent import QualityAgent
from models.domain import (
    Citation,
    CompetitorData,
    FeatureItem,
    PricingTier,
)
from tests.test_orchestrator_baseline import competitor_list, make_orchestrator
from workflow.nodes import AnalysisGraphNodes
from workflow.state import initial_analysis_state


class CollectionTextModelBoundaryTests(unittest.TestCase):
    def test_normalize_text_value_is_readable_deterministic_and_preserves_strings(self):
        self.assertTrue(
            hasattr(domain, "normalize_text_value"),
            "models.domain.normalize_text_value must define the collection text contract",
        )
        normalize = domain.normalize_text_value

        self.assertEqual(normalize("  Direct and partner channels.  "), "  Direct and partner channels.  ")
        self.assertEqual(normalize(None), "")
        self.assertEqual(normalize(["direct", "partner", None]), "direct、partner")
        self.assertEqual(
            normalize({"partner": ["retail", "delivery"], "direct": "website"}),
            "direct：website；partner：retail、delivery",
        )

    def test_competitor_data_normalizes_all_text_fields_on_construction_and_assignment(self):
        data = CompetitorData(
            name="Demo",
            market_share={"estimate": "20%", "source": "industry report"},
            user_reviews=None,
            strengths=["brand", "store network"],
            weaknesses={"cost": "high"},
            channels=["direct", "partner"],
        )

        self.assertEqual(data.market_share, "estimate：20%；source：industry report")
        self.assertEqual(data.user_reviews, "")
        self.assertEqual(data.strengths, "brand、store network")
        self.assertEqual(data.weaknesses, "cost：high")
        self.assertEqual(data.channels, "direct、partner")
        self.assertTrue(all(isinstance(getattr(data, field), str) for field in data.TEXT_FIELDS))

        data.channels = {"partner": ["retail", "delivery"], "direct": "website"}
        data.strengths = "  unchanged string  "

        self.assertEqual(data.channels, "direct：website；partner：retail、delivery")
        self.assertEqual(data.strengths, "  unchanged string  ")


class OfflineSearchClient:
    @staticmethod
    def _results(queries):
        return [
            {
                "query": query,
                "result": {
                    "choices": [
                        {"message": {"content": "Offline source evidence for collection tests."}}
                    ]
                },
                "references": [],
            }
            for query in queries
        ]

    def batch_search(self, queries):
        return self._results(queries)

    async def async_batch_search(self, queries):
        return self._results(queries)


def make_offline_collection_agent(payload, *, truncated=False, supplement_payload=None):
    agent = CollectionAgent.__new__(CollectionAgent)
    agent.search_client = OfflineSearchClient()
    agent._last_search_texts = {}
    agent._prompt_collect = (
        "{product_name}|{product_description}|{competitor_name}|{search_results}"
    )
    agent._log = lambda *_args, **_kwargs: None
    agent._validate_against_source = lambda *_args, **_kwargs: []
    agent.ask_llm_json_with_truncation_check = (
        lambda *_args, **_kwargs: (dict(payload), truncated)
    )
    agent.ask_llm_json = (
        lambda *_args, **_kwargs: dict(supplement_payload or payload)
    )
    agent._supplement_pricing = (
        lambda _entity, _product, pricing_tiers, _citations: (pricing_tiers, [])
    )

    async def async_initial(*_args, **_kwargs):
        return dict(payload), truncated

    async def async_supplement(*_args, **_kwargs):
        return dict(supplement_payload or payload)

    async def async_pricing(_entity, _product, pricing_tiers, _citations):
        return pricing_tiers, []

    agent.async_ask_llm_json_with_truncation_check = async_initial
    agent.async_ask_llm_json = async_supplement
    agent._async_supplement_pricing = async_pricing
    return agent


def malformed_collection_payload():
    return {
        "product_features": [
            {"name": "Ordering", "description": "Mobile ordering support"}
        ],
        "pricing_tiers": [],
        "market_share": ["20% estimate", "industry report"],
        "user_reviews": None,
        "strengths": ["brand", "store network"],
        "weaknesses": {"cost": "high"},
        "channels": ["direct", "partner"],
    }


def call_without_exception(test_case, callback):
    try:
        return callback()
    except Exception as exc:  # pragma: no cover - failure detail for RED phase
        test_case.fail(f"collection path raised {type(exc).__name__}: {exc}")


async def await_without_exception(test_case, awaitable):
    try:
        return await awaitable
    except Exception as exc:  # pragma: no cover - failure detail for RED phase
        test_case.fail(f"collection path raised {type(exc).__name__}: {exc}")


class CollectionAgentIngressTests(unittest.IsolatedAsyncioTestCase):
    def test_sync_collection_normalizes_text_before_market_share_string_checks(self):
        agent = make_offline_collection_agent(malformed_collection_payload())

        with patch.object(config, "ENABLE_LLM", True):
            data = call_without_exception(
                self,
                lambda: agent._collect_entity(
                    "Target", "Target description", "Competitor", ["query"]
                ),
            )

        self.assertEqual(data.market_share, "20% estimate、industry report")
        self.assertEqual(data.channels, "direct、partner")
        self.assertTrue(all(isinstance(getattr(data, field), str) for field in data.TEXT_FIELDS))

    async def test_async_collection_normalizes_text_before_market_share_string_checks(self):
        agent = make_offline_collection_agent(malformed_collection_payload())

        with patch.object(config, "ENABLE_LLM", True):
            data = await await_without_exception(
                self,
                agent._async_collect_entity(
                    "Target", "Target description", "Competitor", ["query"]
                ),
            )

        self.assertEqual(data.market_share, "20% estimate、industry report")
        self.assertEqual(data.weaknesses, "cost：high")
        self.assertTrue(all(isinstance(getattr(data, field), str) for field in data.TEXT_FIELDS))

    def test_truncated_text_supplement_normalizes_initial_and_replacement_values(self):
        initial_channels = [f"channel-{index}" for index in range(21)]
        replacement_channels = [f"replacement-channel-{index}" for index in range(30)]
        agent = make_offline_collection_agent(
            {"channels": initial_channels},
            supplement_payload={"channels": replacement_channels},
        )

        result = call_without_exception(
            self,
            lambda: agent._supplement_text_fields(
                {"channels": initial_channels},
                "Target",
                "Target description",
                "Competitor",
                "offline source",
            ),
        )

        self.assertIsInstance(result["channels"], str)
        self.assertIn("replacement-channel-29", result["channels"])

    def test_sync_market_share_supplement_accepts_array_value(self):
        agent = make_offline_collection_agent({})

        market_share, citations = call_without_exception(
            self,
            lambda: agent._supplement_market_share(
                "Competitor", ["20% estimate", "industry report"], []
            ),
        )

        self.assertEqual(market_share, "20% estimate、industry report")
        self.assertEqual(citations, [])

    async def test_async_market_share_supplement_accepts_object_value(self):
        agent = make_offline_collection_agent({})

        market_share, citations = await await_without_exception(
            self,
            agent._async_supplement_market_share(
                "Competitor", {"estimate": "20%", "source": "industry report"}, []
            ),
        )

        self.assertEqual(market_share, "estimate：20%；source：industry report")
        self.assertEqual(citations, [])

    def test_sync_qa_supplement_normalizes_object_text_value(self):
        agent = make_offline_collection_agent(
            {},
            supplement_payload={
                "channels": {"partner": ["delivery", "retail"], "direct": "website"}
            },
        )
        data = CompetitorData(name="Competitor")

        with patch.object(config, "ENABLE_LLM", True):
            result = agent.supplement_missing_fields(
                "Target", {"Competitor": data}, {"Competitor": ["channels"]}
            )

        self.assertEqual(
            result["Competitor"].channels,
            "direct：website；partner：delivery、retail",
        )

    async def test_async_qa_supplement_normalizes_object_text_value(self):
        agent = make_offline_collection_agent(
            {},
            supplement_payload={
                "strengths": {"brand": "strong", "network": ["urban", "regional"]}
            },
        )
        data = CompetitorData(name="Competitor")

        with patch.object(config, "ENABLE_LLM", True):
            result = await agent.async_supplement_missing_fields(
                "Target", {"Competitor": data}, {"Competitor": ["strengths"]}
            )

        self.assertEqual(
            result["Competitor"].strengths,
            "brand：strong；network：urban、regional",
        )


def valid_competitor_data():
    return CompetitorData(
        name="Competitor",
        product_features=[
            FeatureItem(name="Ordering", description="Mobile ordering"),
            FeatureItem(name="Loyalty", description="Loyalty program"),
        ],
        pricing_tiers=[
            PricingTier(tier_name="Standard", price="10"),
            PricingTier(tier_name="Premium", price="20"),
        ],
        market_share="20% market share reported by an industry source.",
        user_reviews="Customers report a consistent ordering experience.",
        strengths="Strong brand awareness and a broad store network.",
        weaknesses="Higher operating costs in competitive urban markets.",
        channels="Direct stores and delivery platform partnerships.",
        citations=[
            Citation(id="c1", title="Source one", url="https://example.com/1"),
            Citation(id="c2", title="Source two", url="https://example.com/2"),
        ],
    )


class QualityAgentTextDefenseTests(unittest.IsolatedAsyncioTestCase):
    def make_quality_agent(self):
        agent = QualityAgent()
        agent._log = lambda *_args, **_kwargs: None
        return agent

    def test_collection_completeness_reports_channels_array_as_schema_issue(self):
        agent = self.make_quality_agent()
        data = valid_competitor_data()
        object.__setattr__(data, "channels", ["direct", "partner"])

        issues = call_without_exception(
            self,
            lambda: agent._check_collection_completeness({"Competitor": data}),
        )

        schema_issues = [issue for issue in issues if issue.category == "schema"]
        self.assertEqual(len(schema_issues), 1)
        self.assertEqual(schema_issues[0].field, "Competitor.channels")
        self.assertEqual(schema_issues[0].severity, "critical")
        self.assertEqual(schema_issues[0].expected, "str")
        self.assertIn("list", schema_issues[0].actual)
        self.assertIn("direct、partner", schema_issues[0].actual)

    async def test_full_collection_qa_returns_result_and_routes_all_malformed_fields_to_supplement(self):
        agent = self.make_quality_agent()
        data = valid_competitor_data()
        malformed = {
            "market_share": {"estimate": "20%"},
            "user_reviews": None,
            "strengths": ["brand", "network"],
            "weaknesses": {"cost": "high"},
            "channels": ["direct", "partner"],
        }
        for field_name, value in malformed.items():
            object.__setattr__(data, field_name, value)

        with patch.object(config, "ENABLE_LLM", False):
            result = await await_without_exception(
                self,
                agent.check_collection(
                    {"Competitor": data},
                    {},
                    competitor_list=competitor_list(("Competitor",)),
                ),
            )

        schema_issues = [issue for issue in result.issues if issue.category == "schema"]
        self.assertFalse(result.passed)
        self.assertEqual(
            {issue.field for issue in schema_issues},
            {f"Competitor.{field}" for field in CompetitorData.TEXT_FIELDS},
        )
        self.assertTrue(all(issue.expected and issue.actual for issue in schema_issues))
        self.assertEqual(
            set(agent.extract_missing_fields(result, {"Competitor": data})["Competitor"]),
            set(CompetitorData.TEXT_FIELDS),
        )

    async def test_workflow_node_records_formal_qa_result_for_legacy_channels_array(self):
        agent = self.make_quality_agent()
        data = valid_competitor_data()
        object.__setattr__(data, "channels", ["direct", "partner"])
        orchestrator = make_orchestrator()
        orchestrator.quality_agent = agent
        nodes = AnalysisGraphNodes(orchestrator, node_retries=0)
        state = initial_analysis_state("Target product", 1)
        state.update({
            "product_name": "Target",
            "competitors_data": {"Competitor": data},
            "original_search_texts": {},
            "competitor_list": competitor_list(("Competitor",)),
            "collection_retry_count": 0,
        })

        with (
            patch.object(config, "ENABLE_LLM", False),
            patch.object(config, "SKIP_QA", False),
        ):
            update = await await_without_exception(
                self,
                nodes.check_collection_quality(state),
            )

        self.assertFalse(update["qa_collection"].passed)
        self.assertEqual(len(update["qa_checks"]), 1)
        self.assertEqual(len(agent.timeline.checks), 1)
        self.assertTrue(
            any(
                issue.category == "schema" and issue.field == "Competitor.channels"
                for issue in update["qa_collection"].issues
            )
        )

        retry_state = dict(state)
        retry_state.update(update)
        retry_update = await nodes.prepare_collection_retry(retry_state)

        self.assertTrue(retry_update["collection_supplemented"])
        self.assertEqual(retry_update["collection_retry_count"], 1)
        self.assertEqual(retry_update["collection_pending_fields"], 1)
        self.assertEqual(
            orchestrator.collection_agent.supplement_calls[0][1],
            {"Competitor": ["channels"]},
        )


if __name__ == "__main__":
    unittest.main()
