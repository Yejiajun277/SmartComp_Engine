# -*- coding: utf-8 -*-
"""Runtime configuration API contract tests."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import config
from server.main import app
from server.routers import tasks as tasks_router
from server.services.event_bus import EventBus
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


if __name__ == "__main__":
    unittest.main()
