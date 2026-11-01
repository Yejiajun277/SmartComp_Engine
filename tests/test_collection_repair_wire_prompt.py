"""Live f11d9bf6 rejected control wrappers; clarify output without relaxing writes."""
from copy import deepcopy
import json
import re
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from core.collection_repair_plan import build_collection_repair_plan
from models.domain import QualityIssue
from tests.test_collection_repair_plan import snapshot


class CollectionRepairWirePromptTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, responses, *, mutate_before_second=False, finishes=None,
                       change_authority_before_second=False):
        self.agent, self.prompts = CollectionAgent(), []
        self.budgets, self.outcomes = [], []
        data = snapshot()
        self.before = deepcopy(data)
        sources = {"Rival": "Original complete source"}
        issues = [QualityIssue("critical", "citation", "Rival.market_share", "Scope"),
                  QualityIssue("critical", "citation", "Rival.pricing_tiers[0].price", "Scope")]
        queue = iter(responses)
        finish_queue = iter(finishes or ["stop"] * len(responses))
        async def transport(system, prompt, **kwargs):
            self.prompts.append(prompt)
            self.budgets.append(kwargs["max_tokens"])
            return {"content": json.dumps(next(queue)), "finish_reason": next(finish_queue)}
        self.results = []
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            for index in range(len(responses)):
                if index and mutate_before_second:
                    data["Rival"].strengths = "An intervening snapshot revision"
                if index and change_authority_before_second:
                    issues.append(QualityIssue("critical", "citation", "Rival.channels", "New authority"))
                plan = build_collection_repair_plan(data, issues)
                result = await self.agent.async_reextract_saved_sources("Target", "Context", data, sources,
                    "All real QA findings remain here", repair_plan=plan)
                self.results.append(result)
                self.outcomes.append(self.agent.get_repair_outcomes())
        self.assertEqual(self.agent.get_search_texts(), sources)

    async def test_control_wrapper_remains_rejected_and_prompt_has_valid_direct_field_example(self):
        # Actual Apple/YouTube complete outputs and Spotify's captured prefix all
        # used these root keys; their public fact values are irrelevant to shape.
        for bad in [{"text_fields": {"market_share": "Claim"}, "arrays": {}},
                    {"text_fields": {}, "arrays": {"pricing_tiers": []}},
                    {"text_fields": {"strengths": "Claim"}, "arrays": {}}]:
            with self.subTest(root_keys=list(bad)):
                await self.exercise([bad])
                self.assertEqual(self.results[0], self.before)
                self.assertEqual(self.agent.get_repair_outcomes()[0]["status"], "failed")
                prompt = self.prompts[0]
                self.assertIn("控制资料，不是输出格式", prompt)
                examples = re.findall(r"```json\s*(.*?)\s*```", prompt, re.S)
                self.assertTrue(examples, "A whole output object is required, not only an inner operation fragment")
                example = json.loads(examples[-1])
                self.assertEqual(set(example), {"market_share", "pricing_tiers"})
                self.assertEqual(set(example["pricing_tiers"][0]), {"item_id", "changes"})
                self.assertIn("price", example["pricing_tiers"][0]["changes"])
                self.assertNotIn("text_fields", example)
                self.assertNotIn("arrays", example)
                self.assertIn("占位", prompt)

    async def test_same_snapshot_next_attempt_receives_actual_validation_errors(self):
        bad = {"text_fields": {"market_share": "Claim"}, "arrays": {}}
        await self.exercise([bad, bad])
        self.assertNotIn("前次补丁校验错误", self.prompts[0])
        self.assertIn("前次补丁校验错误", self.prompts[1])
        self.assertIn('"field": "text_fields"', self.prompts[1])
        self.assertIn('"reason": "unauthorized_field"', self.prompts[1])
        self.assertIn("All real QA findings remain here", self.prompts[1])
        self.assertEqual(self.results[1], self.before)

    async def test_previous_schema_diagnostics_do_not_cross_snapshot_boundaries(self):
        bad = {"text_fields": {}, "arrays": {}}
        await self.exercise([bad, bad], mutate_before_second=True)
        self.assertNotIn("前次补丁校验错误", self.prompts[1])

    async def test_only_real_length_on_same_snapshot_and_plan_raises_the_existing_next_request(self):
        proof = {"market_share": [{"source_id": "s", "exact_quote": "Basic 100 yuan"}]}
        await self.exercise([proof, proof], finishes=["length", "stop"])
        self.assertEqual(self.budgets, [8192, 16384])
        self.assertEqual(self.results[0], self.before)
        self.assertEqual(self.results[1]["Rival"].market_share, "据[s]原文：Basic 100 yuan")
        self.assertEqual(self.outcomes[0][0]["finish_reason"], "length")
        self.assertEqual(self.outcomes[0][0]["request_max_tokens"], 8192)
        self.assertEqual(self.outcomes[1][0]["finish_reason"], "stop")
        self.assertEqual(self.outcomes[1][0]["request_max_tokens"], 16384)
        self.assertEqual(len(self.prompts), 2)

    async def test_schema_errors_or_content_refusal_never_raise_request_budget(self):
        bad = {"text_fields": {}, "arrays": {}}
        for finish in ["stop", "content_filter", "", "unknown"]:
            with self.subTest(finish=finish):
                await self.exercise([bad, bad], finishes=[finish, "stop"])
                self.assertEqual(self.budgets, [8192, 8192])

    async def test_length_history_does_not_cross_snapshot_or_authority_boundaries(self):
        for options in [{"mutate_before_second": True}, {"change_authority_before_second": True}]:
            with self.subTest(options=options):
                await self.exercise([{"market_share": ""}, {"market_share": ""}], finishes=["length", "stop"], **options)
                self.assertEqual(self.budgets, [8192, 8192])

    async def test_repeated_length_never_grows_above_the_single_recovery_budget(self):
        await self.exercise([{"market_share": ""}] * 3, finishes=["length"] * 3)
        self.assertEqual(self.budgets, [8192, 16384, 16384])
        self.assertTrue(all(result == self.before for result in self.results))
        self.assertEqual(len(self.prompts), 3)  # Exactly the explicitly requested existing attempts.


if __name__ == "__main__":
    unittest.main()
