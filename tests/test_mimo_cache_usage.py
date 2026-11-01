"""Provider cache accounting stays unknown unless trustworthy usage is returned."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agents.quality_agent import QualityAgent
from core.llm_client import get_last_usage
from models.domain import StrategyReport
from server.services.event_bus import EventBus
from server.services.task_manager import TaskManager, TaskState
import server.services.task_manager as task_manager_module
import tests.test_mimo_completion_contract as native_contract


class CacheUsageTests(unittest.IsolatedAsyncioTestCase):
    setUp = native_contract.NativeCompletionContractTests.setUp
    answer = staticmethod(native_contract.NativeCompletionContractTests.answer)

    async def test_sync_and_async_keep_missing_zero_partial_and_full_cache_distinct(self):
        for asynchronous in [False, True]:
            for cached in [None, 0, 40, 100]:
                with self.subTest(asynchronous=asynchronous, cached=cached):
                    body = self.answer()
                    if cached is not None:
                        body["usage"]["prompt_tokens_details"] = {"cached_tokens": cached}
                    self.responses = [(body, 200)]
                    agent = QualityAgent()
                    result = (await agent.async_ask_llm("check", thinking="enabled") if asynchronous
                              else agent.ask_llm("check", thinking="enabled"))
                    self.assertTrue(result)
                    log = agent.llm_logs[-1]
                    self.assertEqual(log["cached_tokens"], cached)
                    self.assertEqual(log["uncached_tokens"], None if cached is None else 100 - cached)
                    self.assertEqual(get_last_usage()["cached_tokens"], cached)
                    self.assertEqual(log["reasoning_tokens"], 17)
                    self.assertEqual(log["thinking"], "enabled")
                    self.assertNotIn("PRIVATE_REASONING", json.dumps(log))

    async def test_invalid_cache_usage_never_produces_a_fictitious_miss_total(self):
        for asynchronous in [False, True]:
            for cached in [-1, 101, "40", 40.0, True]:
                with self.subTest(asynchronous=asynchronous, cached=cached):
                    body = self.answer()
                    body["usage"]["prompt_tokens_details"] = {"cached_tokens": cached}
                    self.responses = [(body, 200)]
                    agent = QualityAgent()
                    if asynchronous:
                        await agent.async_ask_llm("check")
                    else:
                        agent.ask_llm("check")
                    self.assertIsNone(agent.llm_logs[-1]["cached_tokens"])
                    self.assertIsNone(agent.llm_logs[-1]["uncached_tokens"])

    async def test_failed_final_answer_still_retains_returned_cost_usage(self):
        for finish in ["length", "content_filter", "stop"]:
            with self.subTest(finish=finish):
                body = self.answer(content="", finish=finish)
                body["usage"]["prompt_tokens_details"] = {"cached_tokens": 40}
                self.responses = [(body, 200)]
                agent = QualityAgent()
                result, _ = await agent.async_ask_llm_json_with_reason("check", thinking="enabled")
                self.assertFalse(result)
                self.assertEqual(agent.llm_logs[-1]["cached_tokens"], 40)
                self.assertEqual(agent.llm_logs[-1]["uncached_tokens"], 60)
                self.assertEqual(agent.llm_logs[-1]["finish_reason"], finish)
                self.assertFalse(agent.llm_logs[-1]["success"])

    async def test_live_terminal_and_reloaded_task_logs_preserve_only_safe_cost_metadata(self):
        metrics = {"cached_tokens": 40, "uncached_tokens": 60, "reasoning_tokens": 17,
                   "content_chars": 14, "thinking": "enabled", "max_completion_tokens": 16384,
                   "requested_temperature": 0.3}
        entries = [dict(metrics), {**metrics, "cached_tokens": 0, "uncached_tokens": 100}, {}]
        logs = [{"agent_id": "QualityAgent", "result": '{"issues": []}', "prompt_tokens": 100,
                 "completion_tokens": 25, "finish_reason": "stop", **item,
                 "reasoning_content": "DO_NOT_PERSIST_REASONING"} for item in entries]
        captured = []
        actual_sleep = asyncio.sleep

        class Agent:
            def __init__(self):
                self.agent_id = "FixtureAgent"
                self.llm_logs = []
                self.on_log_added = None

            def format_html_report(self, *args, **kwargs):
                return "<html></html>"

        class Orchestrator:
            def __init__(self):
                for name in ["discovery", "collection", "dimension", "product", "pricing", "market", "strategy", "quality"]:
                    setattr(self, name + "_agent", Agent())

            async def analyze(self, *args, **kwargs):
                for log in logs:
                    self.quality_agent.llm_logs.append(deepcopy(log))
                    self.quality_agent.on_log_added(log)
                manager._save_task(task)
                captured.extend(json.loads((tasks_dir / (task.id + ".json")).read_text())["llm_logs"])
                await actual_sleep(0)
                return StrategyReport("Fixture product")

            def get_timings(self):
                return {}

        async def fast_sleep(delay):
            await actual_sleep(0)

        with tempfile.TemporaryDirectory() as temporary:
            tasks_dir = Path(temporary) / "tasks"
            with patch.object(task_manager_module, "_TASKS_DIR", tasks_dir), \
                    patch.dict(sys.modules, {"core.orchestrator": SimpleNamespace(Orchestrator=Orchestrator)}), \
                    patch.object(task_manager_module.asyncio, "sleep", fast_sleep), patch("config.SKIP_QA", False):
                manager = TaskManager(EventBus())
                task = TaskState("cost-fixture", "Fixture product", 3, False)
                manager._tasks[task.id] = task
                with patch.object(manager._event_bus, "emit", AsyncMock()), \
                        patch.object(manager, "_sync_llm_logs_live", AsyncMock()):
                    await manager._run_task(task.id, task.product_description, 3, False, False)
                self.assertEqual(task.status, "completed")
                saved = json.loads((tasks_dir / (task.id + ".json")).read_text())["llm_logs"]
                reloaded = TaskManager(EventBus())._tasks[task.id].llm_logs
        for snapshot in [captured, saved, reloaded]:
            self.assertEqual(len(snapshot), 3)
            for key, value in metrics.items():
                self.assertEqual(snapshot[0][key], value)
            self.assertEqual(snapshot[1]["cached_tokens"], 0)
            self.assertEqual(snapshot[1]["uncached_tokens"], 100)
            self.assertIsNone(snapshot[2]["cached_tokens"])
            self.assertIsNone(snapshot[2]["uncached_tokens"])
            self.assertNotIn("DO_NOT_PERSIST_REASONING", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
