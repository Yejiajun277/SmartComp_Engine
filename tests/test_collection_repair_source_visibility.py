"""Saved-source repairs see the same complete evidence as collection QA."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from tests.collection_repair_support import reviewed_plan, wire_patch
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier


SOURCE_TAIL = "REGIONAL_SHARE_TAIL: 17.3% only in the named region."
LATE_TAIL = "MEMBERSHIP_TERMS_TAIL: named membership only, one stay at a time."
RAW_TAIL = "RAW_SEARCH_TAIL: original query conditions remain unchanged."


def snapshot():
    citations = [Citation(f"Rival:q{i}:r{i}", f"Saved source {i}", f"https://example.test/{i}",
        snippet=("Saved material. " * 130 + (SOURCE_TAIL if i == 0 else LATE_TAIL if i == 29 else f"Record end {i}.")),
        query=f"Original query {i}", competitor="Rival") for i in range(30)]
    item = CompetitorData("Rival",
        product_features=[FeatureItem("Existing membership benefit", "Original scope needs qualification.", [citations[0].id])],
        pricing_tiers=[PricingTier("Existing offer", "Price undisclosed", citations=[citations[0].id])],
        market_share="Original estimate needs scope repair.",
        user_reviews="Existing attributed review.", strengths="Existing bounded strength.",
        weaknesses="Existing limitation.", channels="Existing channel.",
        citations=citations, search_sources=["Original short discovery summary."])
    return {"Rival": item}


def response():
    return {"product_features": [{"name": "Existing membership benefit", "description": LATE_TAIL,
                                  "citations": ["Rival:q29:r29"]}],
            "pricing_tiers": [{"tier_name": "Existing offer", "price": "Price undisclosed", "features": [],
                               "citations": ["Rival:q0:r0"]}],
            "market_share": "17.3% only in the named region.",
            "user_reviews": "Existing attributed review.", "strengths": "Existing bounded strength.",
            "weaknesses": "Existing limitation.", "channels": "Existing channel."}


class NoSearch:
    def __init__(self):
        self.calls = 0

    def batch_search(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Saved-source repair must not search")

    async def async_batch_search(self, *args, **kwargs):
        return self.batch_search(*args, **kwargs)


class CollectionRepairSourceVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def repair(self, data=None, sources=None, payload=None, finish="stop"):
        self.agent = CollectionAgent()
        self.agent.search_client = NoSearch()
        self.calls = []
        data = snapshot() if data is None else data
        sources = ({"Rival": "Full original search text. " * 1200 + RAW_TAIL,
                    "Other": "OTHER_ENTITY_CONTEXT_MUST_NOT_ENTER_THIS_PROMPT"} if sources is None else sources)
        payload = response() if payload is None else payload
        self.before_data, self.before_sources = deepcopy(data), deepcopy(sources)

        async def transport(system, prompt, **kwargs):
            self.calls.append(prompt)
            return {"content": json.dumps(wire_patch(data, payload)), "finish_reason": finish}

        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            updated = await self.agent.async_reextract_saved_sources("Target", "Current category context", data, sources,
                "Rival.market_share: retain regional scope; Rival.product_features[0]: qualify the existing benefit.",
                repair_plan=reviewed_plan(data))
        self.assertEqual(data, self.before_data)
        self.assertEqual(sources, self.before_sources)
        self.assertEqual(self.agent.get_search_texts(), self.before_sources)
        self.assertEqual(self.agent.search_client.calls, 0)
        return updated

    async def test_full_saved_snippets_after_700_and_late_catalog_ids_are_available(self):
        updated = await self.repair()
        prompt = self.calls[0]
        self.assertIn(SOURCE_TAIL, prompt, "QA's full snippet must remain visible to repair")
        self.assertIn(LATE_TAIL, prompt, "The final source cannot disappear at the 16k directory limit")
        self.assertIn("Rival:q29:r29", prompt)
        self.assertEqual(updated["Rival"].product_features[0].citations, ["Rival:q29:r29"])
        self.assertEqual(updated["Rival"].pricing_tiers[0].citations, ["Rival:q0:r0"])
        self.assertEqual(updated["Rival"].market_share, "17.3% only in the named region.")
        self.assertEqual(updated["Rival"].citations, self.before_data["Rival"].citations)
        self.assertEqual(updated["Rival"].search_sources, self.before_data["Rival"].search_sources)

    async def test_full_original_search_text_is_not_discarded_when_catalog_exists(self):
        await self.repair()
        self.assertIn(self.before_sources["Rival"], self.calls[0])
        self.assertNotIn(self.before_sources["Other"], self.calls[0])

    async def test_repair_snapshot_is_explicitly_non_evidence_and_forbids_unrelated_expansion(self):
        await self.repair()
        prompt = self.calls[0]
        self.assertIn("待修复提取快照（背景，不是来源证据）", prompt)
        self.assertIn("Original estimate needs scope repair.", prompt)
        self.assertIn("不新增无关功能", prompt)
        self.assertIn("未指出问题的字段和条目保持原样", prompt)

    async def test_no_catalog_still_preserves_complete_raw_text_without_inventing_ids(self):
        data = snapshot()
        data["Rival"].citations = []
        sources = {"Rival": "Raw search text. " * 1600 + RAW_TAIL}
        updated = await self.repair(data=data, sources=sources, payload={"market_share": "Bounded raw-source statement."})
        self.assertIn(RAW_TAIL, self.calls[0])
        self.assertEqual(updated["Rival"].product_features[0].citations, data["Rival"].product_features[0].citations)
        self.assertEqual(updated["Rival"].pricing_tiers[0].citations, data["Rival"].pricing_tiers[0].citations)

    def test_main_collection_context_keeps_its_existing_bounds(self):
        data = snapshot()["Rival"]
        text, ids = CollectionAgent._source_context(data.citations, "fallback" * 5000)
        self.assertLessEqual(len(text), 16000)
        rows = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
        self.assertTrue(rows)
        self.assertTrue(all(len(row["excerpt"]) <= 700 for row in rows))
        self.assertEqual(ids, {row["id"] for row in rows})
        self.assertNotIn(SOURCE_TAIL, text)
        self.assertNotIn(LATE_TAIL, text)

    async def test_missing_evidence_or_incomplete_bad_truncated_output_keeps_old_facts(self):
        malformed = response()
        malformed["pricing_tiers"] = "not an array"
        for payload, finish in (({}, "stop"), ({"market_share": 17.3}, "stop"),
                                (malformed, "stop"), (response(), "length")):
            with self.subTest(payload=payload, finish=finish):
                updated = await self.repair(payload=payload, finish=finish)
                self.assertEqual(updated, self.before_data)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")
        data = snapshot()
        data["Rival"].citations = []
        updated = await self.repair(data=data, sources={})
        self.assertEqual(updated, self.before_data)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.agent.get_repair_outcomes()[0]["reason"], "missing_saved_sources")


if __name__ == "__main__":
    unittest.main()
