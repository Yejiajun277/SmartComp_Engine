# -*- coding: utf-8 -*-
"""Milestone 3 tests for the LangGraph StateGraph."""

import contextlib
import io
import time
import unittest

from models.domain import CompetitorList
from workflow.graph import build_analysis_graph, run_analysis_graph
from workflow.state import initial_analysis_state

from tests.test_orchestrator_baseline import make_orchestrator


async def run_graph_quietly(orchestrator, *args, **kwargs):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        return await run_analysis_graph(orchestrator, *args, **kwargs)


class WorkflowGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_compiles(self):
        orch = make_orchestrator()
        graph = build_analysis_graph(orch)

        self.assertIsNotNone(graph)
        self.assertTrue(hasattr(graph, "ainvoke"))

    async def test_no_competitors_branch_returns_empty_report(self):
        orch = make_orchestrator(competitors=CompetitorList(product_name="Target", competitors=[]))

        state = await run_graph_quietly(orch, "Target product", 2)

        self.assertEqual(state["status"], "stopped_no_competitors")
        self.assertEqual(state["report"].product_name, "Target")
        self.assertEqual(state["report"].competitor_count, 0)
        self.assertEqual(orch.finalized[-1]["status"], "stopped_no_competitors")
        self.assertIn("07_strategy_report.json", orch.saved_artifacts)

    async def test_happy_path_graph_executes_complete_chain(self):
        orch = make_orchestrator()

        state = await run_graph_quietly(orch, "Target product", 2)

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["report"].product_name, "Target")
        self.assertEqual(state["report"].competitor_count, 2)
        self.assertEqual(
            [check.phase for check in state["report"].qa_timeline.checks],
            ["collection", "product", "pricing", "market", "strategy"],
        )
        self.assertIn("parallel_analysis", state["timings"])
        self.assertIn("07_strategy_report.json", orch.saved_artifacts)
        self.assertEqual(orch._last_competitor_list.product_name, "Target")

    async def test_product_pricing_market_run_in_parallel(self):
        orch = make_orchestrator(analysis_delay=0.2)

        start = time.perf_counter()
        state = await run_graph_quietly(orch, "Target product", 2)
        elapsed = time.perf_counter() - start

        self.assertEqual(state["status"], "completed")
        self.assertLess(elapsed, 0.55)
        starts = [
            orch.product_agent.starts[0],
            orch.pricing_agent.starts[0],
            orch.market_agent.starts[0],
        ]
        self.assertLess(max(starts) - min(starts), 0.06)

    async def test_collection_quality_retry_then_success(self):
        orch = make_orchestrator(collection_passes=[False, True])

        state = await run_graph_quietly(orch, "Target product", 2)

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["collection_retry_count"], 1)
        self.assertEqual(
            orch.collection_agent.run_feedbacks,
            ["", "feedback:collection:CollectionAgent:1"],
        )
        self.assertEqual(
            [check.phase for check in state["report"].qa_timeline.checks[:2]],
            ["collection", "collection"],
        )

    async def test_analysis_quality_retry_returns_to_target_node(self):
        orch = make_orchestrator(
            analysis_passes={
                "product": [False, True],
                "pricing": [True],
                "market": [True],
            }
        )

        state = await run_graph_quietly(orch, "Target product", 2)

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["product_retry_count"], 1)
        self.assertEqual(
            orch.product_agent.feedbacks,
            ["", "feedback:product:ProductAgent:1"],
        )
        self.assertEqual(orch.pricing_agent.feedbacks, [""])
        self.assertEqual(orch.market_agent.feedbacks, [""])
        self.assertEqual(
            [check.phase for check in state["report"].qa_timeline.checks],
            ["collection", "product", "pricing", "market", "product", "strategy"],
        )

    async def test_strategy_quality_retry_then_success(self):
        orch = make_orchestrator(strategy_passes=[False, True])

        state = await run_graph_quietly(orch, "Target product", 2)

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["strategy_retry_count"], 1)
        self.assertEqual(
            orch.strategy_agent.feedbacks,
            ["", "feedback:strategy:StrategyAgent:1"],
        )
        self.assertEqual(
            [check.phase for check in state["report"].qa_timeline.checks[-2:]],
            ["strategy", "strategy"],
        )

    async def test_quality_exhaustion_routes_to_structured_failure_exit(self):
        orch = make_orchestrator(collection_passes=[False, False, False])

        state = await run_graph_quietly(orch, "Target product", 2)

        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["failure"]["phase"], "collection")
        self.assertEqual(state["failure"]["target_agent"], "CollectionAgent")
        self.assertEqual(state["failure"]["attempt"], 3)
        self.assertEqual(state["failure"]["feedback"], "feedback:collection:CollectionAgent:3")
        self.assertEqual(state["error"], "quality_exhausted:collection")
        self.assertEqual(state["collection_retry_count"], 2)
        self.assertEqual(len(orch.collection_agent.run_feedbacks), 3)
        self.assertIn("failed_state.json", orch.saved_artifacts)

    async def test_analysis_quality_exhaustion_stops_without_infinite_loop(self):
        orch = make_orchestrator(
            analysis_passes={
                "product": [False, False, False],
                "pricing": [True],
                "market": [True],
            }
        )

        state = await run_graph_quietly(orch, "Target product", 2)

        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["failure"]["phase"], "product")
        self.assertEqual(state["failure"]["attempt"], 3)
        self.assertEqual(state["failure"]["feedback"], "feedback:product:ProductAgent:3")
        self.assertEqual(state["product_retry_count"], 2)
        self.assertEqual(len(orch.product_agent.feedbacks), 3)
        self.assertEqual(orch.pricing_agent.feedbacks, [""])
        self.assertEqual(orch.market_agent.feedbacks, [""])

    async def test_compiled_graph_accepts_initial_state_directly(self):
        orch = make_orchestrator()
        graph = build_analysis_graph(orch)
        state = initial_analysis_state("Target product", 2)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            final_state = await graph.ainvoke(state)

        self.assertEqual(final_state["status"], "completed")
        self.assertEqual(final_state["report"].product_name, "Target")


if __name__ == "__main__":
    unittest.main()
