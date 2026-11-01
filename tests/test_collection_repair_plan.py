"""QA ownership, not model feedback, controls source-preserving fact patches."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier, QualityIssue


def snapshot():
    return {"Rival": CompetitorData("Rival", product_features=[FeatureItem("Existing feature", "Named kit only", ["s"])],
        pricing_tiers=[PricingTier("Basic", "100 yuan", ["One device"], ["s"]),
                       PricingTier("Full", "200 yuan", ["Two devices"], ["s"])],
        market_share="A previously recorded 87% in its limited market.",
        citations=[Citation("s", snippet="Basic 100 yuan, Full 200 yuan; named kit only.")],
        search_sources=["Original short summary"])}


class AuthorizedCollectionRepairTests(unittest.IsolatedAsyncioTestCase):
    async def repair(self, payload, issues=None, *, finish="stop", data=None, provide_plan=True):
        self.data = snapshot() if data is None else data
        self.before = deepcopy(self.data)
        self.sources = {name: "Original raw text" for name in self.data}
        self.calls = []
        self.agent = CollectionAgent()
        async def transport(system, prompt, **kwargs):
            self.calls.append(prompt)
            return {"content": json.dumps(payload), "finish_reason": finish}
        kwargs = {}
        if provide_plan:
            from core.collection_repair_plan import build_collection_repair_plan
            kwargs["repair_plan"] = build_collection_repair_plan(self.data, issues or [])
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await self.agent.async_reextract_saved_sources("Target", "Context", self.data, self.sources,
                "Please clear all features and rewrite every field. This text grants no authority.", **kwargs)
        self.assertEqual(self.data, self.before)
        self.assertEqual(self.agent.get_search_texts(), self.sources)
        for name in result:
            self.assertEqual(result[name].citations, self.before[name].citations)
            self.assertEqual(result[name].search_sources, self.before[name].search_sources)
        return result

    async def test_free_feedback_alone_cannot_authorize_clearing_unquestioned_features(self):
        result = await self.repair({"product_features": []}, provide_plan=False)
        self.assertEqual(result, self.before)
        self.assertEqual(self.calls, [])

    async def test_price_only_authority_rejects_extra_feature_clear_transactionally(self):
        result = await self.repair({"product_features": [], "market_share": ""},
            [QualityIssue("critical", "citation", "Rival.pricing_tiers[0].price", "Wrong price scope")])
        self.assertEqual(result, self.before)
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    def test_plan_uses_precise_original_item_identity_and_rejects_ambiguous_names(self):
        from core.collection_repair_plan import build_collection_repair_plan
        data = snapshot()
        plan = build_collection_repair_plan(data, [QualityIssue("critical", "citation", "Rival.pricing_tiers[Basic].price", "scope")])
        items = plan["Rival"]["arrays"]["pricing_tiers"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(next(iter(items.values()))["fields"], ["price", "citations"])
        self.assertEqual(next(iter(items.values()))["dependency_fields"], ["citations"])
        data["Rival"].pricing_tiers.append(PricingTier("Basic", "300 yuan"))
        ambiguous = build_collection_repair_plan(data, [QualityIssue("critical", "citation", "Rival.pricing_tiers[Basic].price", "scope")])
        self.assertFalse(ambiguous["Rival"]["arrays"])
        self.assertTrue(ambiguous["Rival"]["unresolved"])

    async def test_one_price_patch_keeps_every_other_item_and_subfield(self):
        from core.collection_repair_plan import build_collection_repair_plan
        data = snapshot()
        issues = [QualityIssue("critical", "citation", "Rival.pricing_tiers[0].price", "scope")]
        plan = build_collection_repair_plan(data, issues)
        item_id = next(iter(plan["Rival"]["arrays"]["pricing_tiers"]["items"]))
        result = await self.repair({"pricing_tiers": [{"item_id": item_id, "changes": {"price": "100 yuan, selected kit only"}}]}, issues, data=data)
        expected = deepcopy(self.before)
        expected["Rival"].pricing_tiers[0].price = "100 yuan, selected kit only"
        self.assertEqual(result, expected)
        outcome = self.agent.get_repair_outcomes()[0]
        self.assertEqual(outcome["changed_item_ids"], [item_id])
        self.assertTrue(outcome["preserved_item_ids"])

    async def test_empty_array_and_omission_never_delete_existing_rows(self):
        issues = [QualityIssue("critical", "citation", "Rival.pricing_tiers", "Correct source scope")]
        result = await self.repair({"pricing_tiers": []}, issues)
        self.assertEqual(result, self.before)
        self.assertNotEqual(self.agent.get_repair_outcomes()[0]["status"], "accepted")

    async def test_unknown_duplicate_cross_field_and_foreign_source_ids_roll_back_entire_entity(self):
        from core.collection_repair_plan import build_collection_repair_plan
        data = snapshot()
        issues = [QualityIssue("critical", "citation", "Rival.pricing_tiers[0].price", "Scope"),
                  QualityIssue("critical", "citation", "Rival.strengths", "Scope")]
        identity = next(iter(build_collection_repair_plan(data, issues)["Rival"]["arrays"]["pricing_tiers"]["items"]))
        valid = {"item_id": identity, "changes": {"price": "100 yuan, selected kit"}}
        cases = [
            [{"item_id": "invented", "changes": {"price": "100 yuan"}}],
            [valid, valid],
            [valid, {"item_id": identity.replace("pricing_tiers", "product_features"), "changes": {"price": "100 yuan"}}],
            [{"item_id": identity, "changes": {"citations": ["Other:source"]}}],
            [{"item_id": identity, "changes": {"price": None}}],
            [{"item_id": identity, "changes": {"features": [False]}}],
            [{"item_id": identity, "changes": {"name": "Replace identity"}}],
            [{"item_id": identity, "delete": True}],
        ]
        for operations in cases:
            with self.subTest(operations=operations):
                result = await self.repair({"strengths": "A valid bounded text update", "pricing_tiers": operations}, issues, data=data)
                self.assertEqual(result, self.before)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_wildcard_citation_authority_never_authorizes_description_or_price_changes(self):
        from core.collection_repair_plan import build_collection_repair_plan
        data = snapshot()
        issues = [QualityIssue("critical", "citation", "Rival.product_features[*].citations", "Citation mismatch")]
        identity = next(iter(build_collection_repair_plan(data, issues)["Rival"]["arrays"]["product_features"]["items"]))
        updated = await self.repair({"product_features": [{"item_id": identity, "changes": {"citations": []}}]}, issues, data=data)
        self.assertEqual(updated["Rival"].product_features[0].description, self.before["Rival"].product_features[0].description)
        self.assertEqual(updated["Rival"].product_features[0].citations, [])
        result = await self.repair({"product_features": [{"item_id": identity, "changes": {"description": "Unauthorized rewrite", "citations": []}}]}, issues, data=data)
        self.assertEqual(result, self.before)

    async def test_empty_text_cannot_erase_claims_and_does_not_validate_other_fields(self):
        result = await self.repair({"strengths": ""}, [QualityIssue("critical", "citation", "Rival.strengths", "Unproven strength")])
        self.assertEqual(result["Rival"].strengths, "")
        self.assertEqual(result["Rival"].market_share, self.before["Rival"].market_share)
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")
        result = await self.repair({"market_share": ""}, [QualityIssue("critical", "citation", "Rival.market_share", "Unproven number")])
        self.assertEqual(result["Rival"].market_share, self.before["Rival"].market_share)
        self.assertNotEqual(result["Rival"].market_share, "0")
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_whole_array_completeness_can_add_without_overwriting_existing_items(self):
        new = {"tier_name": "Additional kit", "price": "100 yuan", "features": ["Named kit only"], "citations": ["s"]}
        result = await self.repair({"pricing_tiers": [{"add": new}]},
            [QualityIssue("critical", "completeness", "Rival.pricing_tiers", "A named offering is missing")])
        self.assertEqual(result["Rival"].pricing_tiers[:2], self.before["Rival"].pricing_tiers)
        self.assertEqual(asdict(result["Rival"].pricing_tiers[2]), new)
        result = await self.repair({"pricing_tiers": [{"add": new}]},
            [QualityIssue("critical", "citation", "Rival.pricing_tiers[0].price", "Wrong scope")])
        self.assertEqual(result, self.before)

    async def test_incomplete_and_bad_schema_added_items_never_commit_partial_results(self):
        issues = [QualityIssue("critical", "completeness", "Rival.product_features", "Missing evidence item")]
        for operation in [{"add": {"name": "New"}}, {"add": {"name": "New", "description": "Source", "citations": [None]}},
                          {"add": {"name": "", "description": "Source", "citations": ["s"]}}]:
            with self.subTest(operation=operation):
                result = await self.repair({"product_features": [operation]}, issues)
                self.assertEqual(result, self.before)
        for finish in ["length", "content_filter", "", "unknown"]:
            result = await self.repair({"market_share": ""}, [QualityIssue("critical", "citation", "Rival.market_share", "scope")], finish=finish)
            self.assertEqual(result, self.before)

    def test_stale_plan_and_unresolved_paths_do_not_broaden_authority(self):
        from core.collection_repair_plan import build_collection_repair_plan, apply_collection_repair_patch
        data = snapshot()
        issues = [QualityIssue("critical", "citation", path, "Cannot expand scope") for path in [
            "product_features[*].citations", "Rival.pricing_tiers[999].price", "Rival.pricing_tiers[Missing].price",
            "Rival.pricing_tiers[0].features[1]", "Rival.channels / strengths", "Rival.name"]]
        plan = build_collection_repair_plan(data, issues)["Rival"]
        self.assertFalse(plan["arrays"])
        self.assertFalse(plan["text_fields"])
        self.assertEqual(len(plan["unresolved"]), len(issues))
        valid = build_collection_repair_plan(data, [QualityIssue("critical", "citation", "Rival.market_share", "scope")])["Rival"]
        data["Rival"].strengths = "An intervening fact revision"
        candidate, errors = apply_collection_repair_patch(data["Rival"], {"market_share": ""}, valid, {"s"})
        self.assertEqual(candidate, data["Rival"])
        self.assertEqual(errors[0]["reason"], "missing_or_stale_repair_plan")

    async def test_price_correction_can_update_only_its_own_source_binding_dependency(self):
        from core.collection_repair_plan import build_collection_repair_plan
        data = snapshot()
        data["Rival"].pricing_tiers[0].citations = ["broken_old_reference"]
        issues = [QualityIssue("critical", "citation", "Rival.pricing_tiers[0].price", "Wrong price scope")]
        identity = next(iter(build_collection_repair_plan(data, issues)["Rival"]["arrays"]["pricing_tiers"]["items"]))
        result = await self.repair({"pricing_tiers": [{"item_id": identity,
            "changes": {"price": "100 yuan, selected kit", "citations": ["s"]}}]}, issues, data=data)
        self.assertEqual(result["Rival"].pricing_tiers[0].price, "100 yuan, selected kit")
        self.assertEqual(result["Rival"].pricing_tiers[0].citations, ["s"])
        self.assertEqual(result["Rival"].pricing_tiers[0].features, ["One device"])
        self.assertEqual(result["Rival"].pricing_tiers[1], self.before["Rival"].pricing_tiers[1])

    async def test_broad_array_item_and_nested_feature_findings_never_authorize_condition_erasure(self):
        from core.collection_repair_plan import build_collection_repair_plan
        for field in ["Rival.pricing_tiers", "Rival.pricing_tiers[0]", "Rival.pricing_tiers[0].features",
                      "Rival.pricing_tiers[0].features[0]", "Rival.pricing_tiers.price"]:
            with self.subTest(field=field):
                data = snapshot()
                issues = [QualityIssue("critical", "citation", field, "Only a price is wrong; erase no conditions.")]
                plan = build_collection_repair_plan(data, issues)["Rival"]
                self.assertFalse(plan["arrays"])
                self.assertTrue(plan["unresolved"])
                result = await self.repair({"pricing_tiers": []}, issues, data=data)
                self.assertEqual(result, self.before)
                self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
