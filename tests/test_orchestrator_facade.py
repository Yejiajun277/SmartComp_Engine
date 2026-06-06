# -*- coding: utf-8 -*-
"""Tests for Orchestrator feature flag switching."""

import contextlib
import io
import unittest

import config
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


if __name__ == "__main__":
    unittest.main()
