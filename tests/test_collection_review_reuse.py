"""Exact saved-snapshot QA reuse must retain findings and truthful provenance."""
from copy import deepcopy
from dataclasses import asdict
import asyncio
import json
import unittest
from unittest.mock import patch

from agents.quality_agent import QualityAgent
from tests.test_target_collection_quality import entity


def finding(severity="warning"):
    return {"severity": severity, "category": "hallucination", "field": "strengths",
            "description": "The named kit claim needs its original qualification.",
            "suggestion": "Retain the named kit boundary."}


class CollectionReviewReuseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = QualityAgent()
        self.data = {"Target": entity("Target")}
        self.sources = {"Target": "Complete saved raw source. " * 800 + " RAW_TAIL"}
        self.calls = []
        self.responses = []

        async def transport(system, message, **kwargs):
            self.calls.append((system, message, kwargs["max_tokens"]))
            payload, finish = self.responses.pop(0) if self.responses else ({"issues": []}, "stop")
            return {"content": payload if isinstance(payload, str) else json.dumps(payload), "finish_reason": finish,
                    "model": "fixture", "timestamp": "2026-11-01T12:00:00"}

        self.patches = [patch("config.ENABLE_LLM", True),
                        patch("agents.base_agent.async_llm_call", transport)]
        for context in self.patches:
            context.start()
            self.addCleanup(context.stop)

    async def review(self, attempt=1):
        return await self.agent.check_collection(self.data, self.sources, attempt=attempt)

    async def test_exact_reuse_preserves_all_findings_and_trace_without_a_new_call(self):
        self.responses = [({"issues": [finding(), finding("critical")]}, "stop")]
        first = await self.review()
        second = await self.review(2)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first.issues, second.issues)
        self.assertFalse(second.passed)
        trace = second.entity_review_trace[0]
        self.assertEqual(trace["mode"], "reuse")
        self.assertEqual(trace["source_attempt"], 1)
        self.assertEqual(trace["attempt"], 2)
        self.assertEqual(trace["request_count"], 0)
        self.assertEqual(trace["fingerprint"], first.entity_review_trace[0]["fingerprint"])
        self.assertEqual(trace["source_checked_at"], first.entity_review_trace[0]["checked_at"])
        self.assertTrue(trace["checked_at"])
        self.assertEqual(len(trace["fingerprint"]), 64)
        self.assertEqual(asdict(second)["entity_review_trace"], second.entity_review_trace)

    async def test_caller_mutations_cannot_poison_reused_issues_or_provenance(self):
        self.responses = [({"issues": [finding("critical")]}, "stop")]
        first = await self.review()
        first.issues[0].severity = "warning"
        first.issues[0].description = "Caller replaced a finding"
        first.entity_review_trace[0]["fingerprint"] = "changed"
        self.agent._passed_fields.add("Target.strengths")
        second = await self.review(2)
        second.issues.clear()
        third = await self.review(3)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(third.passed)
        self.assertTrue(any(i.severity == "critical" and i.description == finding()["description"]
                            for i in third.issues))

    async def test_each_complete_fact_source_and_prompt_change_invalidates_reuse(self):
        mutations = [
            lambda: setattr(self.data["Target"], "strengths", "Changed claim"),
            lambda: setattr(self.data["Target"].citations[0], "snippet", "Changed source tail"),
            lambda: setattr(self.data["Target"].citations[0], "url", "https://example.test/new"),
            lambda: self.data["Target"].search_sources.append("Changed source metadata"),
            lambda: self.sources.update(Target=self.sources["Target"] + " CHANGED_RAW_TAIL"),
            lambda: setattr(self.agent, "system_prompt", self.agent.system_prompt + " SYSTEM_TAIL"),
            lambda: setattr(self.agent, "_prompt_check_collection", self.agent._prompt_check_collection + " PROMPT_TAIL"),
        ]
        await self.review()
        for attempt, mutate in enumerate(mutations, 2):
            mutate()
            result = await self.review(attempt)
            self.assertEqual(len(self.calls), attempt)
            self.assertEqual(result.entity_review_trace[0]["mode"], "live")
        self.assertIn("RAW_TAIL", self.calls[0][1])

    async def test_model_provider_and_base_url_changes_invalidate_reuse(self):
        await self.review()
        for attempt, (name, value) in enumerate([
                ("MIMO_MODEL", "another-model"), ("LLM_PROVIDER", "another-provider"),
                ("MIMO_BASE_URL", "https://another.example.test/v1")], 2):
            with patch("config." + name, value):
                result = await self.review(attempt)
                self.assertEqual(len(self.calls), attempt)
                self.assertEqual(result.entity_review_trace[0]["mode"], "live")

    async def test_incomplete_or_bad_schema_never_passes_or_enters_cache(self):
        for payload, finish in [({"issues": []}, "length"), ({"issues": []}, "content_filter"),
                                ({"issues": []}, "unknown"), ({"issues": "bad"}, "stop"),
                                ("{", "stop"), ("", "stop")]:
            with self.subTest(finish=finish, payload=payload):
                self.agent = QualityAgent()
                self.calls.clear()
                self.responses = [(payload, finish)] * 4
                first, second = await self.review(), await self.review(2)
                self.assertFalse(first.passed)
                self.assertFalse(second.passed)
                self.assertEqual(second.hallucination_status, "failed")
                self.assertEqual(len(self.calls), 1 if finish == "content_filter" else 4)
                self.assertEqual(second.entity_review_trace[0]["mode"], "not_checked" if finish == "content_filter" else "live")
                self.assertFalse(second.entity_review_trace[0]["completed"])

    async def test_completed_clean_review_can_pass_again_without_a_new_request(self):
        first, second = await self.review(), await self.review(2)
        self.assertTrue(first.passed)
        self.assertTrue(second.passed)
        self.assertEqual(second.hallucination_status, "passed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(second.entity_review_trace[0]["mode"], "reuse")

    async def test_adapter_valid_shape_with_explicit_failure_cannot_pass_without_metadata(self):
        for failure in ("truncated_output", "content_filter", "api_error"):
            with self.subTest(failure=failure):
                self.agent = QualityAgent()
                calls = []

                async def adapter(prompt, **kwargs):
                    calls.append(kwargs["max_tokens"])
                    return {"issues": []}, failure

                with patch.object(self.agent, "async_ask_llm_json_with_reason", adapter):
                    result = await self.review()
                self.assertFalse(result.passed)
                self.assertEqual(result.hallucination_status, "failed")
                self.assertEqual(calls, [16384] if failure == "content_filter" else [16384, 16384])
                self.assertFalse(result.entity_review_trace[0]["completed"])
                self.assertEqual(result.entity_review_trace[0]["failure_reason"],
                                 "provider_content_filter" if failure == "content_filter" else failure)
                self.assertEqual(self.agent._collection_review_cache, {})

    async def test_completed_entity_reuse_does_not_hide_another_unfinished_entity(self):
        self.data["Rival"] = entity("Rival")
        self.sources["Rival"] = "Full rival source"
        self.responses = [({"issues": [finding()]}, "stop"), ({"issues": []}, "length"),
                          ({"issues": []}, "length"), ({"issues": []}, "length"),
                          ({"issues": []}, "length")]
        first, second = await self.review(), await self.review(2)
        self.assertFalse(first.passed)
        self.assertFalse(second.passed)
        self.assertEqual(len(self.calls), 5)
        self.assertEqual([t["mode"] for t in second.entity_review_trace], ["reuse", "live"])
        self.assertTrue(any(i.description == finding()["description"] for i in second.issues))
        self.assertTrue(any(i.field == "__hallucination_check__" for i in second.issues))

    async def test_missing_sources_are_explicit_and_never_cached(self):
        self.sources = {}
        for cite in self.data["Target"].citations:
            cite.snippet = ""
        result = await self.review()
        self.assertFalse(result.passed)
        self.assertEqual(len(self.calls), 0)
        self.assertEqual(result.entity_review_trace[0]["mode"], "not_checked")
        self.assertEqual(result.entity_review_trace[0]["failure_reason"], "missing_original_sources")

    async def test_two_request_budget_and_recovered_trace_are_exact(self):
        self.responses = [({"issues": []}, "length"), ({"issues": [finding()]}, "stop")]
        first = await self.review()
        second = await self.review(2)
        self.assertEqual([call[2] for call in self.calls], [16384, 16384])
        self.assertEqual(first.entity_review_trace[0]["request_count"], 2)
        self.assertEqual([r["finish_reason"] for r in first.entity_review_trace[0]["requests"]],
                         ["length", "stop"])
        self.assertEqual(second.entity_review_trace[0]["request_count"], 0)
        self.assertEqual(second.issues, first.issues)

    async def test_new_run_attempt_one_and_new_agent_cannot_reuse_previous_run(self):
        await self.review()
        await self.review(2)
        await self.review(1)
        self.assertEqual(len(self.calls), 2)
        self.agent = QualityAgent()
        await self.review(2)
        self.assertEqual(len(self.calls), 3)

    async def test_same_agent_concurrent_request_traces_cannot_include_another_review(self):
        a_started, b_completed = asyncio.Event(), asyncio.Event()
        a_calls = 0

        async def transport(system, message, **kwargs):
            nonlocal a_calls
            if message.startswith("A"):
                a_calls += 1
                if a_calls == 1:
                    a_started.set()
                    await b_completed.wait()
                    finish = "length"
                else:
                    finish = "stop"
            else:
                await a_started.wait()
                b_completed.set()
                finish = "stop"
            return {"content": '{"issues": []}', "finish_reason": finish}

        async def review(prompt):
            result, reason = await self.agent._request_quality_json(prompt)
            return result, reason, deepcopy(self.agent._last_quality_request_trace)

        with patch("agents.base_agent.async_llm_call", transport):
            a, b = await asyncio.gather(review("A"), review("B"))
        self.assertEqual([r["finish_reason"] for r in a[2]["requests"]], ["length", "stop"])
        self.assertEqual([r["finish_reason"] for r in b[2]["requests"]], ["stop"])
        self.assertNotIn(b[2]["requests"][0]["fingerprint"],
                         [r["fingerprint"] for r in a[2]["requests"]])

    async def test_fingerprint_runtime_matches_actual_client_model_endpoint_and_messages(self):
        from core.llm_client import async_llm_call
        observed = []

        async def post(client, url, **kwargs):
            # Exercise the real client through its last HTTP boundary; no
            # network, credential inspection or requests can escape this stub.
            observed.append((url, deepcopy(kwargs["json"])))

            class Response:
                status_code = 200

                def json(self):
                    return {"model": kwargs["json"]["model"], "choices": [{
                        "finish_reason": "stop", "message": {"content": '{"issues": []}'}}]}
            return Response()

        with patch("agents.base_agent.async_llm_call", async_llm_call), \
                patch("httpx.AsyncClient.post", post), \
                patch("config.MIMO_API_KEY", "offline-test-placeholder"), \
                patch("config.LLM_PROVIDER", "mimo"):
            for attempt, (model, base_url) in enumerate([
                    ("model-one", "https://first.example.test/v1"),
                    ("model-two", "https://first.example.test/v1"),
                    ("model-two", "https://second.example.test/v1")], 1):
                with patch("config.MIMO_MODEL", model), patch("config.MIMO_BASE_URL", base_url):
                    result = await self.review(attempt)
                    self.assertEqual(result.entity_review_trace[0]["mode"], "live")
                    self.assertEqual(len(observed), attempt)
                    url, payload = observed[-1]
                    self.assertEqual(url, base_url + "/chat/completions")
                    self.assertEqual(payload["model"], model)
                    self.assertEqual(payload["messages"][0]["content"], self.agent.system_prompt)
                    self.assertIn("RAW_TAIL", payload["messages"][1]["content"])
                    self.assertEqual(result.entity_review_trace[0]["fingerprint"],
                                     self.agent._collection_review_fingerprint(payload["messages"][1]["content"]))


if __name__ == "__main__":
    unittest.main()
