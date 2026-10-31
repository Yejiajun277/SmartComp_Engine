"""Failed analysis checks remain failures throughout retries and exhaustion."""

import unittest
from unittest.mock import AsyncMock, patch

import config
from agents.quality_agent import QualityAgent
from core.artifact_store import to_jsonable
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier, QualityCheckResult, QualityIssue
from server.services.event_bus import EventBus
from workflow.graph import route_analysis_quality
from workflow.nodes import AnalysisGraphNodes
from workflow.state import initial_analysis_state

from tests.test_orchestrator_baseline import FakeQualityAgent, make_orchestrator, pricing_analysis, product_analysis
from tests.test_workflow_graph import run_graph_quietly


def failed_check(score, attempt=1):
    return QualityCheckResult(
        phase="product", target_agent="ProductAgent", passed=False,
        score=score, attempt=attempt, hallucination_status="found",
        issues=[QualityIssue(
            severity="critical", category="hallucination", field="summary",
            description="Protein powder has an unsupported AI capability claim.",
        )],
    )


class ScoredProductQualityAgent(FakeQualityAgent):
    def __init__(self, scores):
        super().__init__()
        self.scores = iter(scores)

    async def check_analysis(self, analysis_type, analysis, competitors_data, attempt=1,
                             *, target_product_data=None, product_name=""):
        if analysis_type == "product":
            return failed_check(next(self.scores), attempt)
        return await super().check_analysis(analysis_type, analysis, competitors_data, attempt)


class QualityRetryIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_nodes_supply_target_reference_separately_from_rivals(self):
        for phase in ("product", "pricing", "market"):
            with self.subTest(phase=phase):
                orch = make_orchestrator()
                calls = []

                async def check(analysis_type, analysis, competitors_data, attempt=1, **context):
                    calls.append((competitors_data, context))
                    return QualityCheckResult(analysis_type, "TestAgent", passed=True, score=100)

                orch.quality_agent.check_analysis = check
                target = CompetitorData(name="ON")
                rivals = {"Rival": CompetitorData(name="Rival")}
                state = initial_analysis_state("Protein powder", 2)
                state.update({
                    "product_name": "OPTIMUM NUTRITION", "competitors_data": rivals,
                    "target_product_data": target,
                })

                with patch.object(config, "SKIP_QA", False):
                    await AnalysisGraphNodes(orch)._check_analysis_quality(state, phase, product_analysis())

                self.assertEqual(calls[0][0], rivals)
                self.assertEqual(calls[0][1].get("target_product_data"), target)
                self.assertEqual(calls[0][1].get("product_name"), "OPTIMUM NUTRITION")
                self.assertEqual(list(rivals), ["Rival"])

    async def test_target_facts_and_citations_reach_qa_without_expanding_pricing_coverage(self):
        agent = QualityAgent()
        target = CompetitorData(
            name="ON",
            product_features=[FeatureItem("Protein", "24 g per serving", ["on-source"])],
            pricing_tiers=[PricingTier("2 lb", "$44", citations=["on-source"])],
            citations=[Citation("on-source", "Official nutrition label", "https://example.test/on", "24 g protein")],
        )
        rivals = {"CompA": CompetitorData(name="CompA"), "CompB": CompetitorData(name="CompB")}
        prompts = []

        async def model_check(prompt, **kwargs):
            prompts.append(prompt)
            return {"issues": []}, ""

        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(agent, "async_ask_llm_json_with_reason", model_check),
        ):
            try:
                result = await agent.check_analysis(
                    "pricing", pricing_analysis(), rivals,
                    target_product_data=target, product_name="OPTIMUM NUTRITION",
                )
            except TypeError as exc:
                self.fail(f"Analysis QA rejects the separate target reference context: {exc}")

        self.assertTrue(result.passed)
        self.assertEqual(result.total_fields, 5)
        self.assertEqual(result.coverage_rate, 100)
        self.assertEqual(list(rivals), ["CompA", "CompB"])
        self.assertIn("OPTIMUM NUTRITION", prompts[0])
        self.assertIn('"target_reference"', prompts[0])
        self.assertIn("24 g per serving", prompts[0])
        self.assertIn("on-source", prompts[0])
        self.assertIn("https://example.test/on", prompts[0])
        self.assertIn("Official nutrition label", prompts[0])
        self.assertIn("$44", prompts[0])

    async def test_lower_or_equal_retry_score_stays_failed_and_routes_to_retry(self):
        for score in (40.0, 52.0):
            with self.subTest(score=score):
                orch = make_orchestrator()
                orch.quality_agent = ScoredProductQualityAgent([score])
                events = EventBus()
                nodes = AnalysisGraphNodes(orch, event_bus=events, task_id="retry")
                state = initial_analysis_state("Protein powder", 2)
                state.update({
                    "product_analysis": product_analysis(), "competitors_data": {},
                    "product_retry_count": 1, "product_prev_score": 52.0,
                })

                with patch.object(config, "SKIP_QA", False):
                    state.update(await nodes.check_product_quality(state))

                result = state["qa_product"]
                self.assertFalse(result.passed)
                self.assertFalse(result.degraded)
                self.assertEqual(result.score, score)
                self.assertEqual(result.issues[0].severity, "critical")
                self.assertEqual(route_analysis_quality(state), "retry_product")
                self.assertEqual(events.get_history("retry")[-1]["type"], "qa_check_failed")
                state["product_retry_count"] = 2
                self.assertEqual(route_analysis_quality(state), "exhausted")

    async def test_successful_retry_still_passes(self):
        orch = make_orchestrator()
        nodes = AnalysisGraphNodes(orch)
        state = initial_analysis_state("Protein powder", 2)
        state.update({
            "product_analysis": product_analysis(), "competitors_data": {},
            "product_retry_count": 1, "product_prev_score": 52.0,
        })

        with patch.object(config, "SKIP_QA", False):
            state.update(await nodes.check_product_quality(state))

        self.assertTrue(state["qa_product"].passed)
        self.assertFalse(state["qa_product"].degraded)
        self.assertEqual(state["qa_product"].attempt, 2)

    async def test_high_score_does_not_override_critical_hallucination(self):
        agent = QualityAgent()
        analysis = product_analysis()
        analysis.competitive_advantages = ["Evidence-backed advantage"]
        # Only the external model response is replaced; parsing, scoring and the
        # pass decision all run through the real quality agent.
        response = {"issues": [{
            "severity": "critical", "category": "hallucination", "field": "summary",
            "description": "Unsupported AI capability claim for protein powder.",
        }]}
        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(agent, "async_ask_llm_json_with_reason", AsyncMock(return_value=(response, ""))),
        ):
            result = await agent.check_analysis("product", analysis, {})

        self.assertGreaterEqual(result.score, 75)
        self.assertFalse(result.passed)
        self.assertEqual(result.hallucination_status, "found")
        self.assertEqual(result.issues[0].severity, "critical")

    async def test_high_score_does_not_override_critical_missing_matrix(self):
        analysis = product_analysis()
        analysis.feature_matrix = []
        analysis.competitive_advantages = ["Evidence-backed advantage"]
        with patch.object(config, "ENABLE_LLM", False):
            result = await QualityAgent().check_analysis("product", analysis, {})

        self.assertGreaterEqual(result.score, 75)
        self.assertFalse(result.passed)
        self.assertEqual(result.issues[0].field, "feature_matrix")

    async def test_exhaustion_copies_terminal_result_without_rewriting_audit(self):
        orch = make_orchestrator()
        events = EventBus()
        nodes = AnalysisGraphNodes(orch, event_bus=events, task_id="exhausted")
        result = failed_check(40, attempt=3)
        state = initial_analysis_state("Protein powder", 2)
        state.update({"qa_product": result, "product_retry_count": 2})
        state.update(await nodes.join_analysis_quality(state))

        updates = await nodes.mark_analysis_degraded(state)

        self.assertFalse(result.degraded)
        self.assertFalse(state["qa_checks"][0].degraded)
        self.assertFalse(orch.quality_agent.timeline.checks[0].degraded)
        terminal = updates["qa_product"]
        self.assertFalse(terminal.passed)
        self.assertTrue(terminal.degraded)
        self.assertTrue(updates["quality_exhausted"]["product"])
        self.assertEqual(terminal.issues[0].severity, "critical")
        terminal.issues[0].description = "A later state edit"
        self.assertIn("unsupported AI", orch.quality_agent.timeline.checks[0].issues[0].description)
        event = events.get_history("exhausted")[-1]
        self.assertEqual(event["type"], "qa_check_failed")
        self.assertFalse(event["data"]["passed"])
        self.assertTrue(event["data"]["degraded"])

    async def test_join_records_independent_audit_snapshots(self):
        orch = make_orchestrator()
        nodes = AnalysisGraphNodes(orch)
        result = failed_check(52)
        state = initial_analysis_state("Protein powder", 2)
        state["qa_product"] = result

        updates = await nodes.join_analysis_quality(state)
        result.score = 100
        result.issues.clear()

        for recorded in (updates["qa_checks"][0], orch.quality_agent.timeline.checks[0]):
            self.assertEqual(recorded.score, 52)
            self.assertFalse(recorded.passed)
            self.assertEqual(recorded.issues[0].severity, "critical")

    async def test_exhausted_graph_persists_actual_failed_attempts_and_degraded_status(self):
        orch = make_orchestrator()
        orch.quality_agent = ScoredProductQualityAgent([52, 40, 40])
        saved = {}
        orch._save_artifact_json = lambda name, value: saved.update({name: to_jsonable(value)})

        with patch.object(config, "SKIP_QA", False):
            state = await run_graph_quietly(orch, "Protein powder", 2)

        self.assertEqual(state["status"], "completed_degraded")
        self.assertEqual(state["product_retry_count"], 2)
        self.assertFalse(state["qa_product"].passed)
        self.assertTrue(state["qa_product"].degraded)
        self.assertTrue(state["quality_exhausted"]["product"])
        self.assertEqual(orch.finalized[-1]["status"], "completed_degraded")
        checks = [c for c in saved["07_strategy_report.json"]["qa_timeline"]["checks"] if c["phase"] == "product"]
        self.assertEqual([c["score"] for c in checks], [52, 40, 40])
        self.assertEqual([c["attempt"] for c in checks], [1, 2, 3])
        self.assertTrue(all(not c["passed"] and not c["degraded"] for c in checks))
        self.assertTrue(all(c["issues"][0]["severity"] == "critical" for c in checks))
        self.assertEqual(saved["qa_timeline.json"]["checks"], saved["07_strategy_report.json"]["qa_timeline"]["checks"])
        self.assertEqual(saved["qa_timeline.json"].get("terminal_dispositions"), {
            "product": {"status": "degraded", "attempt": 3, "reason": "retry_exhausted"},
        })
        self.assertEqual(
            saved["07_strategy_report.json"]["qa_timeline"].get("terminal_dispositions"),
            saved["qa_timeline.json"]["terminal_dispositions"],
        )
