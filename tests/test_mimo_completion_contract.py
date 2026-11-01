"""Native MiMo completion budgets and reasoning are distinct from final answers."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest
from unittest.mock import AsyncMock, patch

from agents.quality_agent import QualityAgent
from core.llm_client import async_llm_call, llm_call
from models.domain import QualityCheckResult, QualityIssue


class NativeCompletionContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.payloads = []
        self.responses = []

        def response(url, kwargs):
            self.assertEqual(url, "https://offline.example.test/v1/chat/completions")
            self.payloads.append(deepcopy(kwargs["json"]))
            body, status = self.responses.pop(0) if self.responses else (self.answer(), 200)

            class Response:
                status_code = status

                def json(self):
                    return deepcopy(body)
            return Response()

        def sync_post(session, url, **kwargs):
            return response(url, kwargs)

        async def async_post(client, url, **kwargs):
            return response(url, kwargs)

        for context in [patch("config.ENABLE_LLM", True), patch("config.LLM_PROVIDER", "mimo"),
                        patch("config.MIMO_API_KEY", "offline-placeholder"),
                        patch("config.MIMO_MODEL", "mimo-v2.6-pro"),
                        patch("config.MIMO_BASE_URL", "https://offline.example.test/v1"),
                        patch("requests.Session.post", sync_post), patch("httpx.AsyncClient.post", async_post)]:
            context.start()
            self.addCleanup(context.stop)

    @staticmethod
    def answer(*, content='{"issues": []}', finish="stop", reasoning=17, channel="reasoning_content"):
        return {"choices": [{"message": {"content": content, channel: '{"issues": []} PRIVATE_REASONING'},
                             "finish_reason": finish}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125,
                          "completion_tokens_details": {"reasoning_tokens": reasoning}},
                "model": "mimo-v2.6-pro"}

    def assert_native(self, payload, *, thinking=None, temperature=0.3, budget=4096):
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["max_completion_tokens"], budget)
        if thinking is None:
            self.assertNotIn("thinking", payload)
            self.assertEqual(payload["temperature"], temperature)
        else:
            self.assertEqual(payload["thinking"], {"type": thinking})
            if thinking == "enabled":
                self.assertNotIn("temperature", payload)
                self.assertNotIn("top_p", payload)
            else:
                self.assertEqual(payload["temperature"], temperature)

    def test_sync_standard_budget_keeps_upper_max_tokens_compatibility(self):
        result = llm_call("system", "user", max_tokens=777, temperature=0.2, json_mode=True)
        self.assert_native(self.payloads[-1], budget=777, temperature=0.2)
        self.assertEqual(self.payloads[-1]["response_format"], {"type": "json_object"})
        self.assertEqual(result["reasoning_tokens"], 17)
        self.assertEqual(result["content_chars"], len('{"issues": []}'))
        self.assertNotIn("PRIVATE_REASONING", json.dumps(result))

    async def test_async_standard_budget_matches_sync(self):
        await async_llm_call("system", "user", max_tokens=777, temperature=0.2, json_mode=True)
        llm_call("system", "user", max_tokens=777, temperature=0.2, json_mode=True)
        self.assertEqual(self.payloads[0], self.payloads[1])
        self.assert_native(self.payloads[0], budget=777, temperature=0.2)

    async def test_explicit_enabled_omits_sampling_and_disabled_keeps_requested_temperature(self):
        for thinking in ["enabled", "disabled"]:
            with self.subTest(thinking=thinking):
                result = await async_llm_call("system", "user", max_tokens=16384,
                                              temperature=0, thinking=thinking)
                self.assert_native(self.payloads[-1], budget=16384, thinking=thinking, temperature=0)
                self.assertEqual(result["thinking"], thinking)
                llm_call("system", "user", max_tokens=16384, temperature=0, thinking=thinking)
                self.assert_native(self.payloads[-1], budget=16384, thinking=thinking, temperature=0)

    async def test_reasoning_only_never_becomes_business_json_and_usage_is_retained(self):
        for channel in ["reasoning_content", "reasoning"]:
            for asynchronous in [False, True]:
                with self.subTest(channel=channel, asynchronous=asynchronous):
                    body = self.answer(content="", channel=channel)
                    body["choices"][0]["message"][channel] = '{"issues": []}'
                    self.responses = [(body, 200)]
                    agent = QualityAgent()
                    if asynchronous:
                        result, reason = await agent.async_ask_llm_json_with_reason("check")
                    else:
                        result, reason = agent.ask_llm_json_with_reason("check")
                    self.assertEqual(result, {})
                    self.assertIn("empty_response", reason)
                    self.assertFalse(agent.llm_logs[-1]["success"])
                    self.assertEqual(agent.llm_logs[-1]["reasoning_tokens"], 17)
                    self.assertEqual(agent.llm_logs[-1]["content_chars"], 0)
                    self.assertEqual(agent.llm_logs[-1]["finish_reason"], "stop")

    async def test_missing_reasoning_usage_is_backward_compatible(self):
        body = self.answer()
        body["usage"].pop("completion_tokens_details")
        self.responses = [(body, 200)]
        agent = QualityAgent()
        result, _ = await agent.async_ask_llm_json_with_reason("check")
        self.assertEqual(result, {"issues": []})
        self.assertEqual(agent.llm_logs[-1]["reasoning_tokens"], 0)

    async def test_qa_two_logical_checks_are_explicit_enabled_and_16384_each(self):
        self.responses = [(self.answer(finish="length"), 200), (self.answer(), 200)]
        agent = QualityAgent()
        result, reason = await agent._request_quality_json("complete saved facts")
        self.assertEqual(result, {"issues": []})
        self.assertEqual(reason, "")
        self.assertEqual(len(self.payloads), 2)
        for payload in self.payloads:
            self.assert_native(payload, thinking="enabled", budget=16384)
        for entry in agent.llm_logs:
            self.assertEqual(entry["thinking"], "enabled")
            self.assertEqual(entry["reasoning_tokens"], 17)
            self.assertEqual(entry["content_chars"], len('{"issues": []}'))

    async def test_content_filter_is_failed_without_switching_thinking_or_extra_attempts(self):
        self.responses = [(self.answer(finish="content_filter"), 200)] * 2
        agent = QualityAgent()
        result, reason = await agent._request_quality_json("complete saved facts")
        self.assertEqual(result, {})
        self.assertIn("content_filter", reason)
        self.assertEqual(len(self.payloads), 1)
        self.assertFalse(agent._last_quality_request_trace["cacheable"])
        self.assertTrue(all(p["thinking"] == {"type": "enabled"} for p in self.payloads))

    async def test_two_logical_checks_bound_transport_errors_to_four_http_attempts(self):
        body = {"error": {"message": "Offline unavailable", "type": "server_error", "code": "offline"}}
        self.responses = [(body, 503)] * 4
        with patch("core.llm_client.asyncio.sleep", AsyncMock()):
            result, reason = await QualityAgent()._request_quality_json("complete saved facts")
        self.assertFalse(result)
        self.assertIn("api_error", reason)
        self.assertEqual(len(self.payloads), 4)

    def test_review_fingerprint_binds_thinking_and_budget_but_not_omitted_sampling(self):
        agent = QualityAgent()
        original = agent._collection_review_fingerprint("facts")
        with patch.object(agent, "_QUALITY_THINKING", "disabled"):
            self.assertNotEqual(original, agent._collection_review_fingerprint("facts"))
        with patch.object(agent, "_QUALITY_BUDGETS", (8192, 16384)):
            self.assertNotEqual(original, agent._collection_review_fingerprint("facts"))
        with patch("config.LLM_TEMPERATURE", 0.9):
            self.assertEqual(original, agent._collection_review_fingerprint("facts"))

    async def test_feedback_serializes_all_issues_and_fields_without_any_model_call(self):
        issues = [QualityIssue("critical" if i < 4 else "warning", "citation", f"field[{i}]",
                    "Scope must remain explicit", expected="Exact scope", actual="Observed scope",
                    suggestion="Keep the source boundary") for i in range(5)]
        agent = QualityAgent()
        for phase in ["product", "pricing", "market", "strategy"]:
            with self.subTest(phase=phase), patch.object(agent, "ask_llm", side_effect=AssertionError("No model")), \
                    patch.object(agent, "async_ask_llm", AsyncMock(side_effect=AssertionError("No model"))):
                result = QualityCheckResult(phase, "Agent", False, 20, issues=issues, attempt=2,
                                            hallucination_status="found")
                sync = agent.build_feedback(result)
                asynchronous = await agent.async_build_feedback(result)
                self.assertEqual(sync, asynchronous)
                self.assertEqual(json.loads(sync)["issues"], [asdict(issue) for issue in issues])

    async def test_collection_review_requests_snapshot_numeric_paths_and_explicit_attributes(self):
        from tests.test_target_collection_quality import entity
        agent = QualityAgent()
        captured = []

        async def review(prompt):
            captured.append(prompt)
            return {"issues": []}, ""

        with patch.object(agent, "_request_quality_json", review):
            await agent.check_collection({"Target": entity("Target")}, {"Target": "Complete saved evidence"})
        self.assertIn("Target.pricing_tiers[0].price", captured[0])
        self.assertIn("Target.product_features[0].description", captured[0])
        self.assertIn("Target.pricing_tiers[*].citations", captured[0])
        self.assertIn("不要用条目别名", captured[0])
        self.assertIn("不授权删除或改写已有条目", captured[0])


if __name__ == "__main__":
    unittest.main()
