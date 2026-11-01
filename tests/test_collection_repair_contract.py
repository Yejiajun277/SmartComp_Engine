"""Saved-source repairs apply completed, typed field patches transactionally."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from tests.collection_repair_support import reviewed_plan, wire_patch
from agents.quality_agent import QualityAgent
from tests.test_collection_repair_source_visibility import snapshot, response, NoSearch, RAW_TAIL


class CollectionRepairContractTests(unittest.IsolatedAsyncioTestCase):
    async def repair(self, payload, finish="stop"):
        self.agent = CollectionAgent()
        self.agent.search_client = NoSearch()
        original = snapshot()
        # An omitted legacy claim must not be silently cleared by validation of
        # a different returned field. The eventual QA still sees this old fact.
        original["Rival"].market_share = "Old unsourced estimate 999.9% needs its own later QA."
        sources = {"Rival": "Complete raw source. " * 1500 + RAW_TAIL}
        self.before, self.source_before = deepcopy(original), deepcopy(sources)
        self.prompts = []

        async def transport(system, prompt, **kwargs):
            self.prompts.append(prompt)
            return {"content": json.dumps(wire_patch(original, payload)), "finish_reason": finish}

        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            updated = await self.agent.async_reextract_saved_sources(
                "Target", "Current scope", original, sources, "Rival.strengths: retain the source qualification.", repair_plan=reviewed_plan(original))
        self.assertEqual(original, self.before)
        self.assertEqual(sources, self.source_before)
        self.assertEqual(self.agent.get_search_texts(), self.source_before)
        self.assertEqual(self.agent.search_client.calls, 0)
        for name in original:
            self.assertEqual(updated[name].citations, original[name].citations)
            self.assertEqual(updated[name].search_sources, original[name].search_sources)
        return updated

    async def test_completed_text_patch_updates_only_returned_field_and_records_preserved_fields(self):
        updated = await self.repair({"strengths": "Only the named kit has the described benefit."})
        expected = deepcopy(self.before)
        expected["Rival"].strengths = "Only the named kit has the described benefit."
        self.assertEqual(updated, expected)
        outcome = self.agent.get_repair_outcomes()[0]
        self.assertEqual(outcome["status"], "accepted")
        self.assertEqual(outcome["applied_fields"], ["strengths"])
        self.assertIn("market_share", outcome["preserved_fields"])
        self.assertIn(RAW_TAIL, self.prompts[0])
        self.assertIn("未返回字段保持原值", self.prompts[0])
        self.assertNotIn("每个字段都必须输出", self.prompts[0])

    async def test_completed_structured_patch_binds_only_existing_visible_source_ids(self):
        updated = await self.repair({"product_features": [{"name": "Existing benefit",
            "description": "Named membership only, one stay at a time.",
            "citations": ["Rival:q29:r29"]}]})
        self.assertEqual(updated["Rival"].product_features[0].name, "Existing benefit")
        self.assertEqual(updated["Rival"].product_features[0].citations, ["Rival:q29:r29"])
        self.assertEqual(updated["Rival"].pricing_tiers, self.before["Rival"].pricing_tiers)
        self.assertEqual(updated["Rival"].market_share, self.before["Rival"].market_share)

    async def test_explicit_empty_field_is_a_patch_but_an_empty_object_is_not(self):
        updated = await self.repair({"strengths": ""})
        self.assertEqual(updated["Rival"].strengths, "")
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "accepted")
        updated = await self.repair({})
        self.assertEqual(updated, self.before)
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_empty_share_explicitly_withdraws_claim_without_blessing_other_facts_or_qa(self):
        updated = await self.repair({"market_share": ""})
        expected = deepcopy(self.before)
        expected["Rival"].market_share = ""
        self.assertEqual(updated, expected)
        self.assertNotEqual(updated["Rival"].market_share, "0")
        self.assertEqual(self.agent.get_repair_outcomes()[0]["applied_fields"], ["market_share"])
        # Repair acceptance is a typed transaction, not a quality certificate.
        # A remaining source mismatch must still be checked and reject the gate.
        quality = QualityAgent()

        async def review(prompt):
            return {"issues": [{"severity": "critical", "category": "citation",
                "field": "Rival.product_features[0].description",
                "description": "The unchanged fact still omits the saved source scope."}]}, ""

        with patch("config.ENABLE_LLM", True), patch.object(quality, "_request_quality_json", review):
            result = await quality.check_collection(updated, self.source_before)
        self.assertFalse(result.passed)
        self.assertTrue(any(i.severity == "critical" for i in result.issues))

    async def test_stale_stop_log_cannot_complete_an_adapter_response_without_its_own_metadata(self):
        agent = CollectionAgent()
        original = snapshot()
        before = deepcopy(original)
        agent.llm_logs.append({"finish_reason": "stop"})

        async def adapter(prompt, **kwargs):
            return {"market_share": ""}, "success"

        with patch("config.ENABLE_LLM", True), patch.object(agent, "async_ask_llm_json_with_reason", adapter):
            updated = await agent.async_reextract_saved_sources("Target", "Context", original,
                                                               {"Rival": "Saved original source."}, "fix", repair_plan=reviewed_plan(original))
        self.assertEqual(updated, before)
        self.assertEqual(agent.get_repair_outcomes()[0]["reason"], "incomplete_finish_reason(missing)")

    async def test_bad_type_or_missing_nested_field_rejects_entire_patch_with_exact_schema_path(self):
        for payload, field, actual in [
                ({"strengths": "Valid bounded fact", "pricing_tiers": "wrong"}, "pricing_tiers", "str"),
                ({"pricing_tiers": [{"price": None}]}, "pricing_tiers[0].price", "NoneType"),
                ({"product_features": [{"name": "Feature", "description": 7}]}, "product_features[0].description", "int"),
                ({"product_features": [{"name": "Feature", "description": "Bounded", "citations": [3]}]},
                 "product_features[0].citations[0]", "int"),
                ({"pricing_tiers": [{"tier_name": "Offer", "price": "Unknown", "citations": [False]}]},
                 "pricing_tiers[0].citations[0]", "bool")]:
            with self.subTest(field=field):
                updated = await self.repair(payload)
                self.assertEqual(updated, self.before)
                outcome = self.agent.get_repair_outcomes()[0]
                self.assertEqual(outcome["reason"], "incomplete_or_invalid_schema")
                self.assertIn({"field": field, "actual_type": actual, "reason": "invalid_type"}, outcome["schema_errors"])

    async def test_unknown_top_level_fields_cannot_modify_identity_or_source_snapshot(self):
        for field in ["name", "citations", "search_sources", "unrequested_field"]:
            with self.subTest(field=field):
                updated = await self.repair({"strengths": "A bounded fact", field: "replacement"})
                self.assertEqual(updated, self.before)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["schema_errors"][0]["reason"], "unauthorized_field")

    async def test_incomplete_response_cannot_apply_a_valid_patch(self):
        for finish in ["length", "content_filter", "", "unknown"]:
            for payload in [{"strengths": "A bounded fact"}, response()]:
                with self.subTest(finish=finish, fields=list(payload)):
                    updated = await self.repair(payload, finish)
                    self.assertEqual(updated, self.before)
                    self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    def test_automatic_supplement_still_requires_every_requested_field(self):
        self.assertFalse(CollectionAgent._valid_extraction({"strengths": "A bounded fact"},
                                                           ["strengths", "market_share"]))


if __name__ == "__main__":
    unittest.main()
