# -*- coding: utf-8 -*-
"""Regression tests for external-service failures in the report pipeline."""

from __future__ import annotations

import json
import os
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import config
from agents.base_agent import BaseAgent
from agents.discovery_agent import DiscoveryAgent
from core.search_client import SearchClient


class _JsonCompletionHandler(BaseHTTPRequestHandler):
    payloads: list[dict] = []
    reject_response_format = False

    def do_POST(self):  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.payloads.append(payload)
        if self.__class__.reject_response_format and "response_format" in payload:
            body = json.dumps(
                {
                    "error": {
                        "message": "Unsupported parameter: response_format",
                        "type": "invalid_request_error",
                        "code": "unsupported_parameter",
                    }
                }
            ).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": '{"ok": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 3,
                    "total_tokens": 6,
                },
                "model": "test-model",
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class _JsonAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_id="JsonAgent", system_prompt="Return JSON only.")

    async def run(self, *args, **kwargs):
        raise NotImplementedError


class LlmClientResilienceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _JsonCompletionHandler.payloads = []
        _JsonCompletionHandler.reject_response_format = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _JsonCompletionHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    async def test_async_json_call_bypasses_a_broken_environment_proxy(self):
        broken_proxy = "http://127.0.0.1:1"
        proxy_env = {
            "HTTP_PROXY": broken_proxy,
            "HTTPS_PROXY": broken_proxy,
            "ALL_PROXY": broken_proxy,
            "NO_PROXY": "",
            "http_proxy": broken_proxy,
            "https_proxy": broken_proxy,
            "all_proxy": broken_proxy,
            "no_proxy": "",
        }
        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(config, "MIMO_API_KEY", "test-key"),
            patch.object(config, "MIMO_BASE_URL", self.base_url),
            patch.object(config, "MIMO_MODEL", "test-model"),
            patch.object(config, "MIMO_USE_SYSTEM_PROXY", False),
            patch.dict(os.environ, proxy_env, clear=False),
        ):
            result = await _JsonAgent().async_ask_llm_json("Return ok=true.")

        self.assertEqual(result, {"ok": True})

    def test_sync_json_call_bypasses_a_broken_environment_proxy(self):
        broken_proxy = "http://127.0.0.1:1"
        proxy_env = {
            "HTTP_PROXY": broken_proxy,
            "HTTPS_PROXY": broken_proxy,
            "ALL_PROXY": broken_proxy,
            "NO_PROXY": "",
            "http_proxy": broken_proxy,
            "https_proxy": broken_proxy,
            "all_proxy": broken_proxy,
            "no_proxy": "",
        }
        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(config, "MIMO_API_KEY", "test-key"),
            patch.object(config, "MIMO_BASE_URL", self.base_url),
            patch.object(config, "MIMO_MODEL", "test-model"),
            patch.object(config, "MIMO_USE_SYSTEM_PROXY", False),
            patch.dict(os.environ, proxy_env, clear=False),
        ):
            result = _JsonAgent().ask_llm_json("Return ok=true.")

        self.assertEqual(result, {"ok": True})

    async def test_async_json_call_requests_json_object_output(self):
        no_proxy_env = {
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "all_proxy": "",
        }
        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(config, "MIMO_API_KEY", "test-key"),
            patch.object(config, "MIMO_BASE_URL", self.base_url),
            patch.object(config, "MIMO_MODEL", "test-model"),
            patch.object(config, "MIMO_USE_SYSTEM_PROXY", False),
            patch.dict(os.environ, no_proxy_env, clear=False),
        ):
            result = await _JsonAgent().async_ask_llm_json("Return ok=true.")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            _JsonCompletionHandler.payloads[-1].get("response_format"),
            {"type": "json_object"},
        )

    async def test_async_json_call_falls_back_when_response_format_is_unsupported(self):
        _JsonCompletionHandler.reject_response_format = True
        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(config, "MIMO_API_KEY", "test-key"),
            patch.object(config, "MIMO_BASE_URL", self.base_url),
            patch.object(config, "MIMO_MODEL", "test-model"),
            patch.object(config, "MIMO_USE_SYSTEM_PROXY", False),
        ):
            result = await _JsonAgent().async_ask_llm_json("Return ok=true.")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(_JsonCompletionHandler.payloads), 2)
        self.assertIn("response_format", _JsonCompletionHandler.payloads[0])
        self.assertNotIn("response_format", _JsonCompletionHandler.payloads[1])

    def test_sync_json_call_falls_back_when_response_format_is_unsupported(self):
        _JsonCompletionHandler.reject_response_format = True
        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(config, "MIMO_API_KEY", "test-key"),
            patch.object(config, "MIMO_BASE_URL", self.base_url),
            patch.object(config, "MIMO_MODEL", "test-model"),
            patch.object(config, "MIMO_USE_SYSTEM_PROXY", False),
        ):
            result = _JsonAgent().ask_llm_json("Return ok=true.")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(_JsonCompletionHandler.payloads), 2)
        self.assertIn("response_format", _JsonCompletionHandler.payloads[0])
        self.assertNotIn("response_format", _JsonCompletionHandler.payloads[1])


class _AllSearchesFailDiscoveryAgent(DiscoveryAgent):
    async def _generate_keywords(self, _product_description):
        return ["target competitors"]

    async def _search(self, keywords):
        return [
            {
                "query": keywords[0],
                "result": None,
                "references": [],
                "error": "ModuleNotFoundError: No module named 'tavily'",
            }
        ]


class _EmptySuccessfulSearchDiscoveryAgent(DiscoveryAgent):
    async def _generate_keywords(self, _product_description):
        return ["target competitors"]

    async def _search(self, keywords):
        return [
            {
                "query": keywords[0],
                "result": {"choices": [], "references": []},
                "references": [],
            }
        ]


class SearchResilienceTests(unittest.IsolatedAsyncioTestCase):
    def test_transient_search_failure_is_retried_once(self):
        class FlakyTavilyClient:
            calls = 0

            def __init__(self, api_key):
                self.api_key = api_key

            def search(self, **_kwargs):
                self.__class__.calls += 1
                if self.__class__.calls == 1:
                    raise ConnectionError("temporary SSL disconnect")
                return {
                    "answer": "Recovered search result",
                    "results": [
                        {
                            "title": "Recovered",
                            "content": "Useful competitor evidence",
                            "url": "https://example.test/recovered",
                        }
                    ],
                }

        FlakyTavilyClient.calls = 0
        fake_module = types.SimpleNamespace(TavilyClient=FlakyTavilyClient)
        client = SearchClient(api_key="configured-key")

        with patch.dict(sys.modules, {"tavily": fake_module}):
            try:
                result = client.search("target competitors")
            except ConnectionError as exc:
                self.fail(f"transient search error was not retried: {exc}")

        self.assertEqual(FlakyTavilyClient.calls, 2)
        self.assertEqual(len(result["references"]), 1)
        self.assertTrue(client.search_logs[-1]["success"])

    def test_permanent_search_failure_is_not_retried(self):
        class InvalidKeyTavilyClient:
            calls = 0

            def __init__(self, api_key):
                self.api_key = api_key

            def search(self, **_kwargs):
                self.__class__.calls += 1
                raise ValueError("invalid API key")

        InvalidKeyTavilyClient.calls = 0
        fake_module = types.SimpleNamespace(TavilyClient=InvalidKeyTavilyClient)
        client = SearchClient(api_key="bad-key")

        with patch.dict(sys.modules, {"tavily": fake_module}):
            with self.assertRaisesRegex(ValueError, "invalid API key"):
                client.search("target competitors")

        self.assertEqual(InvalidKeyTavilyClient.calls, 1)
        self.assertEqual(len(client.search_logs), 1)
        self.assertFalse(client.search_logs[-1]["success"])

    def test_terminal_transient_search_failure_is_logged_after_two_attempts(self):
        class OfflineTavilyClient:
            calls = 0

            def __init__(self, api_key):
                self.api_key = api_key

            def search(self, **_kwargs):
                self.__class__.calls += 1
                raise ConnectionError("temporary network outage")

        OfflineTavilyClient.calls = 0
        fake_module = types.SimpleNamespace(TavilyClient=OfflineTavilyClient)
        client = SearchClient(api_key="configured-key")

        with patch.dict(sys.modules, {"tavily": fake_module}):
            with self.assertRaisesRegex(ConnectionError, "network outage"):
                client.search("target competitors")

        self.assertEqual(OfflineTavilyClient.calls, 2)
        self.assertEqual(len(client.search_logs), 1)
        self.assertFalse(client.search_logs[-1]["success"])

    def test_missing_key_is_recorded_in_search_logs(self):
        client = SearchClient(api_key="")

        with self.assertRaisesRegex(RuntimeError, "TAVILY_API_KEY"):
            client.search("target competitors")

        self.assertEqual(len(client.search_logs), 1)
        self.assertFalse(client.search_logs[0]["success"])
        self.assertIn("TAVILY_API_KEY", client.search_logs[0]["error"])

    def test_http_status_classification_only_retries_transient_failures(self):
        class StatusError(Exception):
            def __init__(self, status_code):
                self.status_code = status_code

        for status_code in (408, 425, 500, 503):
            with self.subTest(status_code=status_code):
                self.assertTrue(
                    SearchClient._is_transient_error(StatusError(status_code))
                )
        for status_code in (400, 401, 403, 404, 429):
            with self.subTest(status_code=status_code):
                self.assertFalse(
                    SearchClient._is_transient_error(StatusError(status_code))
                )

    def test_dependency_import_failure_is_recorded_in_search_logs(self):
        client = SearchClient(api_key="configured-key")

        with patch.dict(sys.modules, {"tavily": None}):
            with self.assertRaises(ModuleNotFoundError):
                client.search("target competitors")

        self.assertEqual(len(client.search_logs), 1)
        self.assertFalse(client.search_logs[0]["success"])
        self.assertIn("tavily", client.search_logs[0]["error"])

    async def test_discovery_stops_when_every_search_fails(self):
        agent = _AllSearchesFailDiscoveryAgent()

        with patch.object(config, "ENABLE_LLM", True):
            with self.assertRaisesRegex(RuntimeError, "联网搜索.*失败"):
                await agent.run("Target", max_competitors=3)

    async def test_rule_mode_keeps_the_existing_search_fallback(self):
        agent = _AllSearchesFailDiscoveryAgent()

        with patch.object(config, "ENABLE_LLM", False):
            result = await agent.run("Target", max_competitors=3)

        self.assertEqual(
            [item.name for item in result.competitors],
            ["竞品A", "竞品B", "竞品C"],
        )

    async def test_successful_empty_search_returns_no_competitors_without_placeholders(self):
        agent = _EmptySuccessfulSearchDiscoveryAgent()

        with patch.object(config, "ENABLE_LLM", True):
            result = await agent.run("Target", max_competitors=3)

        self.assertEqual(result.product_name, "Target")
        self.assertEqual(result.competitors, [])


if __name__ == "__main__":
    unittest.main()
