# -*- coding: utf-8 -*-
"""Tests for Orchestrator feature flag switching."""

import contextlib
import io
import unittest
from unittest.mock import patch

import config
import main
from models.domain import StrategyReport
from tests.test_orchestrator_baseline import make_orchestrator


async def run_quietly(orchestrator, *args, **kwargs):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        return await orchestrator.analyze(*args, **kwargs)


class OrchestratorFacadeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_flag = config.USE_LANGGRAPH_WORKFLOW

    async def asyncTearDown(self):
        config.USE_LANGGRAPH_WORKFLOW = self.old_flag

    async def test_default_flag_uses_langgraph_path(self):
        config.USE_LANGGRAPH_WORKFLOW = True
        orch = make_orchestrator()

        report = await run_quietly(orch, "Target product", 2)

        self.assertEqual(report.product_name, "Target")
        self.assertEqual(orch.finalized[-1]["status"], "completed")
        self.assertEqual(
            [check.phase for check in report.qa_timeline.checks],
            ["collection", "product", "pricing", "market", "strategy"],
        )
        self.assertEqual(orch._last_competitor_list.product_name, "Target")

    async def test_feature_flag_can_switch_to_legacy_path(self):
        config.USE_LANGGRAPH_WORKFLOW = False
        orch = make_orchestrator()

        report = await run_quietly(orch, "Target product", 2)

        self.assertEqual(report.product_name, "Target")
        self.assertEqual(orch.finalized[-1]["status"], "completed")
        self.assertEqual(
            [check.phase for check in report.qa_timeline.checks],
            ["collection", "product", "pricing", "market", "strategy"],
        )
        self.assertEqual(orch._last_competitor_list.product_name, "Target")

    async def test_main_does_not_export_success_report_when_graph_failed(self):
        class FailedArtifactStore:
            def __init__(self):
                self.saved = []

            def save_text(self, name, text):
                self.saved.append(("text", name))
                raise AssertionError("failed workflow must not save success HTML")

            def save_json(self, name, data):
                self.saved.append(("json", name))
                raise AssertionError("failed workflow must not save success JSON")

        class FailedOrchestrator:
            last_instance = None

            def __init__(self):
                FailedOrchestrator.last_instance = self
                self.strategy_agent = make_orchestrator().strategy_agent
                self.artifact_store = FailedArtifactStore()
                self.run_dir = "failed-run"
                self._last_status = "failed"
                self.meta_updated = False

            async def analyze(self, product_description, max_competitors):
                return StrategyReport(product_name="Target")

            def print_stats(self):
                pass

            def get_timings(self):
                return {}

            def update_artifact_meta(self):
                self.meta_updated = True

        stdout = io.StringIO()
        with patch.object(main, "Orchestrator", FailedOrchestrator):
            with contextlib.redirect_stdout(stdout):
                report = await main.run_analysis("Target product", use_llm=False, max_competitors=2)

        self.assertEqual(report.product_name, "Target")
        self.assertTrue(FailedOrchestrator.last_instance.meta_updated)
        self.assertEqual(FailedOrchestrator.last_instance.artifact_store.saved, [])


if __name__ == "__main__":
    unittest.main()
