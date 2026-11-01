"""Re-extraction may select source text, never invent relationships from QA prose."""
import json
import re
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from core.collection_repair_plan import build_collection_repair_plan
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier, QualityIssue


class CollectionRepairTextEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def repair(self, payload, *, feedback="Expected: these percentages use active users as denominator.",
                     source_mutator=None, response_override=None):
        self.agent = CollectionAgent()
        self.before = {"Orion": CompetitorData("Orion",
            product_features=[FeatureItem("Named model", "Only model X", ["Orion:s1"])],
            pricing_tiers=[PricingTier("Monthly", "$10", ["Named model only", "One user"], ["Orion:s1"])],
            market_share="A prior estimate needs correction.",
            strengths="An untouched, already supported statement.",
            citations=[Citation("Orion:s1", title="Community repost", competitor="Orion",
                snippet="Orion has 80 million active users. Shares: Orion 12%, Vega 8%."),
                Citation("Orion:s2", title="Audited bulletin", competitor="Orion",
                    snippet="In region R in 2025, Orion holds 12% of paid accounts; only model X is included.")])}
        if source_mutator:
            source_mutator(self.before["Orion"].citations)
        self.sources = {"Orion": "This unrelated raw search text does not license invented quotations."}
        issues = [QualityIssue("critical", "citation", "Orion.market_share", "Scope must be supported"),
                  QualityIssue("warning", "citation", "Orion.pricing_tiers[0].price", "Price")]
        self.plan = build_collection_repair_plan(self.before, issues)
        self.prompts = []
        self.request_options = []
        async def transport(system, prompt, **kwargs):
            self.prompts.append(prompt)
            self.request_options.append(kwargs)
            return response_override if response_override is not None else {
                "content": json.dumps(payload), "finish_reason": "stop"}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await self.agent.async_reextract_saved_sources("Target", "Research scope", self.before,
                self.sources, feedback, repair_plan=self.plan)
        self.assertEqual(self.agent.get_search_texts(), self.sources)
        self.assertEqual(result["Orion"].citations, self.before["Orion"].citations)
        self.assertEqual(result["Orion"].pricing_tiers[0].features, ["Named model only", "One user"])
        self.assertEqual(len(self.prompts), 1)
        return result

    async def test_freeform_relationship_from_qa_feedback_is_not_written(self):
        result = await self.repair({"market_share": "Orion has 12% of active users, Vega 8%."})
        self.assertEqual(result, self.before)
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_exact_source_selection_projects_source_attributes_without_new_scope(self):
        result = await self.repair({"market_share": [
            {"source_id": "Orion:s1", "exact_quote": "Shares: Orion 12%, Vega 8%."},
            {"source_id": "Orion:s2", "exact_quote": "In region R in 2025, Orion holds 12% of paid accounts; only model X is included."}]})
        self.assertEqual(result["Orion"].market_share,
            "据《Community repost》[Orion:s1]原文：Shares: Orion 12%, Vega 8%.\n"
            "据《Audited bulletin》[Orion:s2]原文：In region R in 2025, Orion holds 12% of paid accounts; only model X is included.")
        self.assertEqual(result["Orion"].strengths, self.before["Orion"].strengths)
        self.assertNotIn("active users", result["Orion"].market_share)
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "accepted")

    async def test_feedback_old_facts_and_other_sources_cannot_supply_quotations(self):
        bad = [
            {"source_id": "Orion:s1", "exact_quote": "Expected: these percentages use active users as denominator."},
            {"source_id": "Orion:s1", "exact_quote": "A prior estimate needs correction."},
            {"source_id": "Orion:s1", "exact_quote": "This unrelated raw search text does not license invented quotations."},
            {"source_id": "Vega:s1", "exact_quote": "Shares: Orion 12%, Vega 8%."},
            {"source_id": "Orion:s1", "exact_quote": "In region R in 2025, Orion holds 12% of paid accounts; only model X is included."},
        ]
        for proof in bad:
            with self.subTest(proof=proof):
                result = await self.repair({"market_share": [proof]})
                self.assertEqual(result, self.before)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_altered_disjoint_or_empty_proofs_reject_entire_entity_including_valid_array_patch(self):
        for proof in [[], [{"source_id": "Orion:s1", "exact_quote": ""}],
                [{"source_id": "Orion:s1", "exact_quote": "Orion has 80 million active users. Orion 12%"}],
                [{"source_id": "Orion:s1", "exact_quote": "Shares: Orion 13%, Vega 8%."}],
                [{"source_id": "Orion:s1", "exact_quote": "Shares: Orion 12%, Vega 8%.", "scope": "Active users"}],
                [{"source_id": "Orion:s1", "exact_quote": 12}]]:
            with self.subTest(proof=proof):
                # Build the real snapshot's stable ID without mocking transaction validation.
                await self.repair({"market_share": proof})
                identity = next(iter(self.plan["Orion"]["arrays"]["pricing_tiers"]["items"]))
                result = await self.repair({"market_share": proof,
                    "pricing_tiers": [{"item_id": identity, "changes": {"price": "$11"}}]})
                self.assertEqual(result, self.before)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_valid_quote_and_precise_array_update_preserve_other_items_and_conditions(self):
        await self.repair({"market_share": [{"source_id": "Orion:s1", "exact_quote": "Shares: Orion 12%, Vega 8%."}]})
        identity = next(iter(self.plan["Orion"]["arrays"]["pricing_tiers"]["items"]))
        result = await self.repair({"market_share": [{"source_id": "Orion:s1", "exact_quote": "Shares: Orion 12%, Vega 8%."}],
            "pricing_tiers": [{"item_id": identity, "changes": {"price": "$11"}}]})
        self.assertEqual(result["Orion"].pricing_tiers[0].price, "$11")
        self.assertEqual(result["Orion"].product_features, self.before["Orion"].product_features)
        self.assertEqual(result["Orion"].strengths, self.before["Orion"].strengths)

    async def test_omitted_text_field_keeps_old_claim_and_output_example_matches_new_wire(self):
        result = await self.repair({"pricing_tiers": []})
        self.assertEqual(result, self.before)
        example = json.loads(re.findall(r"```json\s*(.*?)\s*```", self.prompts[0], re.S)[-1])
        self.assertEqual(set(example), {"market_share", "pricing_tiers"})
        self.assertEqual(set(example["market_share"][0]), {"source_id", "exact_quote"})
        self.assertEqual(set(example["pricing_tiers"][0]), {"item_id", "changes"})

    async def test_ambiguous_or_explicit_foreign_catalog_ownership_cannot_authorize_quotes(self):
        for mutate in [lambda rows: rows.append(rows[0]),
                       lambda rows: setattr(rows[0], "competitor", "Vega")]:
            with self.subTest(mutate=mutate):
                result = await self.repair({"market_share": [{"source_id": "Orion:s1",
                    "exact_quote": "Shares: Orion 12%, Vega 8%."}]}, source_mutator=mutate)
                self.assertEqual(result, self.before)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_missing_source_excerpt_rejects_proof_without_crashing_or_writing(self):
        result = await self.repair({"market_share": [{"source_id": "Orion:s1",
            "exact_quote": "Shares: Orion 12%, Vega 8%."}]},
            source_mutator=lambda rows: setattr(rows[0], "snippet", None))
        self.assertEqual(result, self.before)
        self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")

    async def test_saved_source_selection_uses_one_disabled_thinking_request_and_final_content(self):
        payload = {"market_share": [{"source_id": "Orion:s1", "exact_quote": "Shares: Orion 12%, Vega 8%."}]}
        result = await self.repair(payload, response_override={"content": json.dumps(payload),
            "reasoning_content": '{"market_share":"An unsupported relationship"}', "finish_reason": "stop"})
        self.assertEqual(self.request_options[0].get("thinking"), "disabled")
        self.assertEqual(self.request_options[0]["max_tokens"], 8192)
        self.assertEqual(result["Orion"].market_share,
                         "据《Community repost》[Orion:s1]原文：Shares: Orion 12%, Vega 8%.")
        self.assertEqual(self.agent.llm_logs[-1]["thinking"], "disabled")

    async def test_reasoning_cannot_replace_missing_invalid_or_truncated_final_json(self):
        payload = {"market_share": [{"source_id": "Orion:s1", "exact_quote": "Shares: Orion 12%, Vega 8%."}]}
        for final, finish in [("", "stop"), ("not JSON", "stop"), (json.dumps(payload), "length")]:
            with self.subTest(final=final, finish=finish):
                result = await self.repair(payload, response_override={"content": final,
                    "reasoning_content": json.dumps(payload), "finish_reason": finish})
                self.assertEqual(result, self.before)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")
                self.assertEqual(self.request_options[0].get("thinking"), "disabled")


if __name__ == "__main__":
    unittest.main()
