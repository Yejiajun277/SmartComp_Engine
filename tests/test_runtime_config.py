# -*- coding: utf-8 -*-
"""Runtime configuration API contract tests."""

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import config
from server.main import app
from server.routers import tasks as tasks_router
from server.services.event_bus import EventBus
import server.services.task_manager as task_manager_module
from server.services.task_manager import TaskManager, TaskState


class RuntimeConfigApiTests(unittest.TestCase):
    def test_reports_rule_mode_without_api_keys(self):
        with (
            patch.object(config, "MIMO_API_KEY", ""),
            patch.object(config, "MIMO_MODEL", "mimo-v2.5-pro"),
            patch.object(config, "LLM_PROVIDER", "mimo"),
            patch.object(config, "TAVILY_API_KEY", ""),
            TestClient(app) as client,
        ):
            response = client.get("/api/runtime")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "llm": {
                "configured": False,
                "provider": "mimo",
                "model": None,
            },
            "search": {
                "configured": False,
                "provider": "tavily",
                "model": None,
            },
            "default_mode": "rule",
        })

    def test_reports_model_without_exposing_secrets(self):
        with (
            patch.object(config, "MIMO_API_KEY", "super-secret-model-key"),
            patch.object(config, "MIMO_MODEL", "mimo-v2.5-pro"),
            patch.object(config, "LLM_PROVIDER", "mimo"),
            patch.object(config, "TAVILY_API_KEY", "super-secret-search-key"),
            TestClient(app) as client,
        ):
            response = client.get("/api/runtime")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "llm": {
                "configured": True,
                "provider": "mimo",
                "model": "mimo-v2.5-pro",
            },
            "search": {
                "configured": True,
                "provider": "tavily",
                "model": None,
            },
            "default_mode": "model",
        })
        serialized = response.text.lower()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("super-secret", serialized)

    def test_normalizes_supported_provider_aliases(self):
        with (
            patch.object(config, "MIMO_API_KEY", "configured-placeholder"),
            patch.object(config, "MIMO_MODEL", "mimo-v2.5-pro"),
            patch.object(config, "LLM_PROVIDER", "doubao"),
            TestClient(app) as client,
        ):
            response = client.get("/api/runtime")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["llm"], {
            "configured": True,
            "provider": "mimo",
            "model": "mimo-v2.5-pro",
        })
        self.assertEqual(response.json()["default_mode"], "model")

    def test_rejects_an_unsupported_provider_even_when_a_key_exists(self):
        with (
            patch.object(config, "MIMO_API_KEY", "configured-placeholder"),
            patch.object(config, "LLM_PROVIDER", "unsupported-provider"),
            TestClient(app) as client,
        ):
            response = client.get("/api/runtime")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["llm"], {
            "configured": False,
            "provider": "unsupported-provider",
            "model": None,
        })
        self.assertEqual(response.json()["default_mode"], "rule")


class TaskExecutionMetadataTests(unittest.TestCase):
    def test_task_summary_exposes_the_actual_model_and_qa_mode(self):
        task = TaskState(
            id="model-task",
            product_description="飞书",
            max_competitors=5,
            skip_qa=False,
            use_rule_engine=False,
        )
        task.llm_provider = "mimo"
        task.llm_model = "mimo-v2.5-pro"

        builder = getattr(tasks_router, "_build_task_summary", None)
        self.assertTrue(callable(builder), "task summary builder is missing")
        summary = builder(task).model_dump()

        self.assertFalse(summary["use_rule_engine"])
        self.assertFalse(summary["skip_qa"])
        self.assertEqual(summary["llm_provider"], "mimo")
        self.assertEqual(summary["llm_model"], "mimo-v2.5-pro")

    def test_rule_task_summary_does_not_claim_a_model(self):
        task = TaskState(
            id="rule-task",
            product_description="飞书",
            max_competitors=5,
            skip_qa=True,
            use_rule_engine=True,
        )

        builder = getattr(tasks_router, "_build_task_summary", None)
        self.assertTrue(callable(builder), "task summary builder is missing")
        summary = builder(task).model_dump()

        self.assertTrue(summary["use_rule_engine"])
        self.assertTrue(summary["skip_qa"])
        self.assertIsNone(summary["llm_provider"])
        self.assertIsNone(summary["llm_model"])


class TaskSubmissionMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_api_forces_rule_mode_before_task_is_saved(self):
        manager = TaskManager(EventBus())
        manager._tasks = {}

        with (
            patch.object(config, "MIMO_API_KEY", ""),
            patch.object(manager, "_save_task"),
            patch.object(manager, "_run_task", new_callable=AsyncMock) as run_task,
        ):
            task_id = await manager.submit("飞书", 5, False, False)
            await asyncio.sleep(0)

        task = manager.get(task_id)
        self.assertTrue(task.use_rule_engine)
        self.assertIsNone(task.llm_provider)
        self.assertIsNone(task.llm_model)
        run_task.assert_awaited_once()

    async def test_configured_api_is_persisted_as_the_selected_model(self):
        manager = TaskManager(EventBus())
        manager._tasks = {}

        with (
            patch.object(config, "MIMO_API_KEY", "configured-placeholder"),
            patch.object(config, "LLM_PROVIDER", "mimo"),
            patch.object(config, "MIMO_MODEL", "mimo-v2.5-pro"),
            patch.object(manager, "_save_task"),
            patch.object(manager, "_run_task", new_callable=AsyncMock) as run_task,
        ):
            task_id = await manager.submit("飞书", 5, False, False)
            await asyncio.sleep(0)

        task = manager.get(task_id)
        self.assertFalse(task.use_rule_engine)
        self.assertEqual(task.llm_provider, "mimo")
        self.assertEqual(task.llm_model, "mimo-v2.5-pro")
        run_task.assert_awaited_once()

    async def test_unsupported_provider_forces_rule_mode(self):
        manager = TaskManager(EventBus())
        manager._tasks = {}

        with (
            patch.object(config, "MIMO_API_KEY", "configured-placeholder"),
            patch.object(config, "LLM_PROVIDER", "unsupported-provider"),
            patch.object(manager, "_save_task"),
            patch.object(manager, "_run_task", new_callable=AsyncMock),
        ):
            task_id = await manager.submit("飞书", 5, False, False)
            await asyncio.sleep(0)

        task = manager.get(task_id)
        self.assertTrue(task.use_rule_engine)
        self.assertIsNone(task.llm_provider)
        self.assertIsNone(task.llm_model)


class ConcurrentExecutionModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelling_a_task_while_it_waits_for_the_mode_lock_cleans_up(self):
        original_sleep = asyncio.sleep

        async def fast_startup_sleep(_delay):
            await original_sleep(0)

        manager = TaskManager(EventBus(), max_concurrent=2)
        task = TaskState("waiting", "waiting", 5, False, use_rule_engine=False)
        manager._tasks = {task.id: task}
        await manager._runtime_config_lock.acquire()

        try:
            with (
                patch.object(task_manager_module.asyncio, "sleep", fast_startup_sleep),
                patch.object(manager, "_save_task") as save_task,
                patch.object(manager._event_bus, "emit", new_callable=AsyncMock),
            ):
                run = asyncio.create_task(
                    manager._run_task(task.id, task.product_description, 5, False, False),
                )
                await original_sleep(0.01)
                self.assertFalse(run.done())

                run.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await run

            self.assertEqual(task.status, "cancelled")
            self.assertIsNotNone(task.finished_at)
            self.assertIsNone(task.current_agent)
            self.assertNotIn(manager._on_workflow_event, manager._event_bus._listeners)
            self.assertGreaterEqual(save_task.call_count, 2)
        finally:
            manager._runtime_config_lock.release()

    async def test_opposite_modes_cannot_overwrite_each_others_runtime_config(self):
        observations = []
        original_sleep = asyncio.sleep

        class FakeAgent:
            on_log_added = None

            def format_html_report(self, *args, **kwargs):
                return "<html></html>"

        class FakeOrchestrator:
            def __init__(self):
                self.discovery_agent = FakeAgent()
                self.collection_agent = FakeAgent()
                self.dimension_agent = FakeAgent()
                self.product_agent = FakeAgent()
                self.pricing_agent = FakeAgent()
                self.market_agent = FakeAgent()
                self.strategy_agent = FakeAgent()
                self.quality_agent = FakeAgent()

            async def analyze(self, product_description, *args, **kwargs):
                observations.append((
                    product_description,
                    "start",
                    config.ENABLE_LLM,
                    config.SKIP_QA,
                ))
                await original_sleep(0.03)
                observations.append((
                    product_description,
                    "end",
                    config.ENABLE_LLM,
                    config.SKIP_QA,
                ))
                return object()

            def get_timings(self):
                return {}

        async def fast_startup_sleep(_delay):
            await original_sleep(0)

        manager = TaskManager(EventBus(), max_concurrent=2)
        manager._tasks = {
            "rule": TaskState("rule", "rule", 5, True, use_rule_engine=True),
            "model": TaskState(
                "model",
                "model",
                5,
                False,
                use_rule_engine=False,
                llm_provider="mimo",
                llm_model="mimo-v2.5-pro",
            ),
        }
        fake_module = SimpleNamespace(Orchestrator=FakeOrchestrator)

        with (
            patch.dict(sys.modules, {"core.orchestrator": fake_module}),
            patch.object(task_manager_module.asyncio, "sleep", fast_startup_sleep),
            patch.object(manager, "_save_task"),
            patch.object(manager._event_bus, "emit", new_callable=AsyncMock),
            patch.object(manager, "_sync_llm_logs_live", new_callable=AsyncMock),
            patch.object(config, "ENABLE_LLM", True),
            patch.object(config, "SKIP_QA", False),
        ):
            rule_run = asyncio.create_task(manager._run_task("rule", "rule", 5, True, True))
            await original_sleep(0.005)
            model_run = asyncio.create_task(manager._run_task("model", "model", 5, False, False))
            await asyncio.gather(rule_run, model_run)

        self.assertEqual(observations, [
            ("rule", "start", False, True),
            ("rule", "end", False, True),
            ("model", "start", True, False),
            ("model", "end", True, False),
        ])


if __name__ == "__main__":
    unittest.main()
