# -*- coding: utf-8 -*-
"""Unit tests for LangGraph node wrappers."""

import asyncio
import unittest

from workflow.nodes import AnalysisGraphNodes
from workflow.state import initial_analysis_state

from tests.test_orchestrator_baseline import (
    make_orchestrator,
    product_analysis,
    pricing_analysis,
    market_analysis,
    strategy_report,
)


def merge_state(state, updates):
    merged = dict(state)
    merged.update(updates)
    return merged


async def run_to_collection_checked(nodes, state):
    for step in (
        nodes.initialize_run,
        nodes.discover_competitors,
        nodes.collect_target_product,
        nodes.collect_competitors,
        nodes.check_collection_quality,
    ):
        state = merge_state(state, await step(state))
    return state


async def run_to_dimensions(nodes, state):
    state = await run_to_collection_checked(nodes, state)
    state = merge_state(state, await nodes.generate_dimensions(state))
    state = merge_state(state, await nodes.build_degradation_warning(state))
    return state


async def run_to_analyses(nodes, state):
    state = await run_to_dimensions(nodes, state)
    updates = await asyncio.gather(
        nodes.run_product_analysis(state),
        nodes.run_pricing_analysis(state),
        nodes.run_market_analysis(state),
    )
    for update in updates:
        state = merge_state(state, update)
    state = merge_state(state, await nodes.join_parallel_analysis(state))
    return state


class FlakyDiscoveryAgent:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = 0
        self.llm_logs = []

    async def run(self, product_description, max_competitors):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("temporary discovery timeout")
        return await self.wrapped.run(product_description, max_competitors)


class WorkflowNodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_state_and_discovery_node(self):
        orch = make_orchestrator()
        nodes = AnalysisGraphNodes(orch)
        state = initial_analysis_state("Target product", 2)

        state = merge_state(state, await nodes.initialize_run(state))
        state = merge_state(state, await nodes.discover_competitors(state))

        self.assertEqual(state["status"], "running")
        self.assertEqual(state["product_name"], "Target")
        self.assertIn("discovery", state["timings"])
        self.assertIn("01_competitor_list.json", orch.saved_artifacts)

    async def test_collection_quality_node_and_retry_feedback(self):
        orch = make_orchestrator(collection_passes=[False, True])
        nodes = AnalysisGraphNodes(orch)
        state = initial_analysis_state("Target product", 2)

        state = await run_to_collection_checked(nodes, state)
        self.assertFalse(state["qa_collection"].passed)
        self.assertEqual(state["qa_collection"].attempt, 1)
        self.assertEqual(len(state["qa_checks"]), 1)

        state = merge_state(state, await nodes.prepare_collection_retry(state))
        self.assertEqual(state["collection_retry_count"], 1)
        self.assertEqual(state["collection_feedback"], "feedback:collection:CollectionAgent:1")

        state = merge_state(state, await nodes.collect_competitors(state))
        state = merge_state(state, await nodes.check_collection_quality(state))
        self.assertTrue(state["qa_collection"].passed)
        self.assertEqual(state["qa_collection"].attempt, 2)
        self.assertEqual(
            orch.collection_agent.run_feedbacks,
            ["", "feedback:collection:CollectionAgent:1"],
        )

    async def test_dimension_and_analysis_nodes_wrap_existing_agents(self):
        orch = make_orchestrator()
        nodes = AnalysisGraphNodes(orch)
        state = initial_analysis_state("Target product", 2)

        state = await run_to_analyses(nodes, state)

        self.assertIn("**Core**", state["product_sub_dims_text"])
        self.assertIn("**Model**", state["pricing_sub_dims_text"])
        self.assertEqual(len(state["product_analysis"].feature_matrix), 3)
        self.assertEqual(len(state["pricing_analysis"].pricing_comparison), 2)
        self.assertEqual(len(state["market_analysis"].market_share_data), 2)
        self.assertIn("parallel_analysis", state["timings"])
        self.assertIn("04_product_analysis.json", orch.saved_artifacts)
        self.assertEqual(orch.product_agent.feedbacks, [""])
        self.assertEqual(orch.pricing_agent.feedbacks, [""])
        self.assertEqual(orch.market_agent.feedbacks, [""])

    async def test_analysis_quality_join_and_targeted_retry_nodes(self):
        orch = make_orchestrator(
            analysis_passes={
                "product": [False, True],
                "pricing": [True],
                "market": [True],
            }
        )
        nodes = AnalysisGraphNodes(orch)
        state = initial_analysis_state("Target product", 2)
        state = await run_to_analyses(nodes, state)

        for step in (
            nodes.check_product_quality,
            nodes.check_pricing_quality,
            nodes.check_market_quality,
        ):
            state = merge_state(state, await step(state))
        state = merge_state(state, await nodes.join_analysis_quality(state))

        self.assertEqual(
            [check.phase for check in state["qa_checks"]],
            ["collection", "product", "pricing", "market"],
        )
        self.assertFalse(state["qa_product"].passed)

        state = merge_state(state, await nodes.prepare_product_retry(state))
        self.assertEqual(state["product_retry_count"], 1)
        self.assertEqual(state["product_feedback"], "feedback:product:ProductAgent:1")

        state = merge_state(state, await nodes.run_product_analysis(state))
        state = merge_state(state, await nodes.check_product_quality(state))
        self.assertTrue(state["qa_product"].passed)
        self.assertEqual(
            orch.product_agent.feedbacks,
            ["", "feedback:product:ProductAgent:1"],
        )
        self.assertEqual(orch.pricing_agent.feedbacks, [""])
        self.assertEqual(orch.market_agent.feedbacks, [""])

    async def test_strategy_finalize_and_failure_nodes(self):
        orch = make_orchestrator()
        nodes = AnalysisGraphNodes(orch)
        state = initial_analysis_state("Target product", 2)
        state = await run_to_analyses(nodes, state)
        state = merge_state(state, await nodes.generate_strategy(state))
        state = merge_state(state, await nodes.check_strategy_quality(state))
        state = merge_state(state, await nodes.finalize_report(state))

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["report"].product_name, "Target")
        self.assertEqual(orch.finalized[-1]["status"], "completed")
        self.assertEqual(orch._last_competitor_list.product_name, "Target")
        self.assertIn("07_strategy_report.json", orch.saved_artifacts)

        failed_orch = make_orchestrator(
            analysis_passes={"product": [False], "pricing": [True], "market": [True]}
        )
        failed_nodes = AnalysisGraphNodes(failed_orch)
        failed_state = initial_analysis_state("Target product", 2)
        failed_state.update({
            "product_name": "Target",
            "product_analysis": product_analysis(),
            "pricing_analysis": pricing_analysis(),
            "market_analysis": market_analysis(),
            "report": strategy_report(),
        })
        failed_state = merge_state(
            failed_state,
            await failed_nodes.initialize_run(failed_state),
        )
        # Use a real failed QA result from the fake quality agent.
        qa = await failed_orch.quality_agent.check_analysis(
            "product", product_analysis(), {}
        )
        failed_orch.quality_agent.timeline.add_check(qa)
        failed_state["qa_product"] = qa
        failed_state["qa_checks"] = [qa]
        failed_state["latest_feedback"] = "feedback:product:ProductAgent:1"

        failed_state = merge_state(failed_state, await failed_nodes.fail_run(failed_state))
        self.assertEqual(failed_state["status"], "failed")
        self.assertEqual(failed_state["failure"]["phase"], "product")
        self.assertEqual(failed_state["failure"]["feedback"], "feedback:product:ProductAgent:1")
        self.assertIn("failed_state.json", failed_orch.saved_artifacts)

    async def test_node_level_retry_for_transient_exception(self):
        orch = make_orchestrator()
        orch.discovery_agent = FlakyDiscoveryAgent(orch.discovery_agent)
        nodes = AnalysisGraphNodes(orch, node_retries=1)
        state = initial_analysis_state("Target product", 2)

        state = merge_state(state, await nodes.initialize_run(state))
        state = merge_state(state, await nodes.discover_competitors(state))

        self.assertEqual(orch.discovery_agent.calls, 2)
        self.assertEqual(state["product_name"], "Target")


if __name__ == "__main__":
    unittest.main()
