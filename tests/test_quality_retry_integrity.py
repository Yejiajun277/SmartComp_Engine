"""Failed analysis checks remain failures throughout retries and exhaustion."""

import json
import unittest
from unittest.mock import AsyncMock, patch

import config
from agents.quality_agent import QualityAgent
from core.artifact_store import to_jsonable
from models.domain import (
    Citation, CompetitorData, CompetitiveAdvantage, FeatureComparison, FeatureItem,
    MarketAnalysis, MarketShareItem, PricingAnalysis, PricingItem, PricingTier,
    ProductAnalysis, QualityCheckResult, QualityIssue, UserProfile, UserReputation,
)
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
                             *, target_product_data=None, product_name="", sub_dimensions=""):
        if analysis_type == "product":
            return failed_check(next(self.scores), attempt)
        return await super().check_analysis(analysis_type, analysis, competitors_data, attempt)


class QualityRetryIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def test_exhausted_product_does_not_consume_another_failed_phases_retry_budget(self):
        state = {
            "qa_product": failed_check(64, 3), "product_retry_count": 2,
            "qa_pricing": QualityCheckResult("pricing", "PricingAgent", True, 100),
            "qa_market": QualityCheckResult("market", "MarketAgent", False, 34),
            "market_retry_count": 0,
        }
        self.assertEqual(route_analysis_quality(state), "retry_market")
        state["market_retry_count"] = 1
        self.assertEqual(route_analysis_quality(state), "retry_market")
        state["market_retry_count"] = 2
        self.assertEqual(route_analysis_quality(state), "exhausted")

    async def test_graph_retries_other_failed_phases_after_product_exhaustion(self):
        orch = make_orchestrator(analysis_passes={
            "product": [False, False, False], "pricing": [True], "market": [False, False, True],
        })
        with patch.object(config, "SKIP_QA", False):
            state = await run_graph_quietly(orch, "Protein powder", 2)

        self.assertEqual(state["status"], "completed_degraded")
        self.assertEqual(state["product_retry_count"], 2)
        self.assertEqual(state["market_retry_count"], 2)
        self.assertTrue(state["qa_market"].passed)
        self.assertFalse(state["qa_market"].degraded)
        self.assertEqual(state["quality_exhausted"], {"product": True})
        self.assertEqual(len(orch.market_agent.feedbacks), 3)
        market_checks = [c for c in state["report"].qa_timeline.checks if c.phase == "market"]
        self.assertEqual([c.attempt for c in market_checks], [1, 2, 3])
        self.assertEqual([c.passed for c in market_checks], [False, False, True])

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
                    "product_sub_dims_text": "1. **Safety certification**",
                    "pricing_sub_dims_text": "1. **Package price**",
                })

                with patch.object(config, "SKIP_QA", False):
                    await AnalysisGraphNodes(orch)._check_analysis_quality(state, phase, product_analysis())

                self.assertEqual(calls[0][0], rivals)
                self.assertEqual(calls[0][1].get("target_product_data"), target)
                self.assertEqual(calls[0][1].get("product_name"), "OPTIMUM NUTRITION")
                self.assertEqual(calls[0][1].get("sub_dimensions"), {
                    "product": "1. **Safety certification**",
                    "pricing": "1. **Package price**", "market": "",
                }[phase])
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


def prompt_json_objects(prompt):
    """Read actual serialized payloads passed to the external model boundary."""
    objects = []
    decoder = json.JSONDecoder()
    offset = 0
    while (start := prompt.find("{", offset)) >= 0:
        try:
            obj, length = decoder.raw_decode(prompt[start:])
        except json.JSONDecodeError:
            offset = start + 1
        else:
            objects.append(obj)
            offset = start + length
    return objects


class AnalysisQualityPromptIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def capture_payloads(self, phase, analysis, rivals, **context):
        prompts = []

        async def external_model(prompt, **kwargs):
            prompts.append(prompt)
            return {"issues": []}, ""

        agent = QualityAgent()
        with (
            patch.object(config, "ENABLE_LLM", True),
            patch.object(agent, "async_ask_llm_json_with_reason", external_model),
        ):
            try:
                await agent.check_analysis(phase, analysis, rivals, **context)
            except TypeError as exc:
                self.fail(f"Analysis QA cannot accept the current analysis contract: {exc}")
        return prompt_json_objects(prompts[0])

    async def test_rival_reference_keeps_late_features_complete_facts_and_source_metadata(self):
        rival = CompetitorData(
            name="Dymatize",
            product_features=[FeatureItem(f"Feature {i}", "Collected fact") for i in range(7)] + [
                FeatureItem("Safety certification", "Batch screening certificate", ["Dymatize:q6:r32"]),
            ],
            pricing_tiers=[PricingTier("2 lb", "$55", ["Whey isolate"], ["Dymatize:q6:r31"])],
            strengths="a" * 220 + "Traceable supplier quality process",
            channels="Official distributor",
            citations=[
                Citation("Dymatize:q6:r31", "Product facts", "https://example.test/dymatize", "Whey isolate"),
                Citation("Dymatize:q6:r32", "Safety source", "https://example.test/cert", "Batch screening certificate"),
            ],
        )
        payloads = await self.capture_payloads("product", product_analysis(), {"Dymatize": rival})
        references = next(p for p in payloads if "Dymatize" in p)
        reference = references["Dymatize"]
        self.assertEqual(len(reference["product_features"]), 8)
        self.assertEqual(reference["product_features"][-1], {
            "name": "Safety certification", "description": "Batch screening certificate",
            "citations": ["Dymatize:q6:r32"],
        })
        self.assertEqual(reference["pricing_tiers"][0]["price"], "$55")
        self.assertTrue(reference["strengths"].endswith("Traceable supplier quality process"))
        self.assertEqual(reference["channels"], "Official distributor")
        self.assertEqual(reference["citations"][-1]["id"], "Dymatize:q6:r32")
        self.assertEqual(reference["citations"][-1]["url"], "https://example.test/cert")
        self.assertEqual(reference["citations"][-1]["snippet"], "Batch screening certificate")

    async def test_full_product_snapshot_keeps_existing_advantages_and_row_citations(self):
        analysis = ProductAnalysis(
            feature_matrix=[FeatureComparison("Safety certification", {"ON": "⚪", "Dymatize": "🔶"}, ["Dymatize:q6:r32"])],
            competitive_advantages=[CompetitiveAdvantage("Dymatize", "Unknown", "Batch screening", ["Dymatize:q6:r32"])],
            differentiation_points=["Available batch screening evidence"],
            summary="分片恢复后仍有资料缺口，未知格保持⚪。",
            citations=["Dymatize:q6:r32"],
        )
        payloads = await self.capture_payloads("product", analysis, {})
        snapshot = next(p for p in payloads if "feature_matrix" in p)
        self.assertEqual(snapshot, {
            "feature_matrix": [{"feature": "Safety certification", "values": {"ON": "⚪", "Dymatize": "🔶"}, "citations": ["Dymatize:q6:r32"]}],
            "competitive_advantages": [{"competitor": "Dymatize", "our_advantage": "Unknown", "their_advantage": "Batch screening", "citations": ["Dymatize:q6:r32"]}],
            "differentiation_points": ["Available batch screening evidence"],
            "summary": "分片恢复后仍有资料缺口，未知格保持⚪。",
            "citations": ["Dymatize:q6:r32"],
        })

    async def test_full_pricing_and_market_snapshots_keep_explanations_profiles_and_citations(self):
        cases = [
            ("pricing", PricingAnalysis(
                pricing_comparison=[PricingItem("Dymatize", "Unknown", "$55", "One-time retail", ["price-source"])],
                pricing_strategy_analysis="Compare equal package sizes", value_ranking=["Dymatize"],
                summary="Pricing scope is explicit", citations=["price-source"],
            ), {
                "pricing_comparison": [{"competitor": "Dymatize", "free_tier": "Unknown", "paid_tier": "$55", "pricing_model": "One-time retail", "citations": ["price-source"]}],
                "pricing_strategy_analysis": "Compare equal package sizes", "value_ranking": ["Dymatize"],
                "summary": "Pricing scope is explicit", "citations": ["price-source"],
                "dimension_comparison": [],
            }),
            ("market", MarketAnalysis(
                market_share_data=[MarketShareItem("Dymatize", "Unknown", "No measured share", ["market-source"])],
                growth_trends="More low-sugar launches",
                user_reputation={"Dymatize": UserReputation("Unknown", ["Taste"], ["review-source"])},
                user_profiles={"Dymatize": UserProfile(target_audience="Strength athletes", citations=["profile-source"])},
                channel_analysis="Official retail", summary="Qualitative market signals", citations=["market-source"],
            ), {
                "market_share_data": [{"competitor": "Dymatize", "share_estimate": "Unknown", "trend": "No measured share", "citations": ["market-source"]}],
                "growth_trends": "More low-sugar launches",
                "user_reputation": {"Dymatize": {"score": "Unknown", "keywords": ["Taste"], "citations": ["review-source"]}},
                "user_profiles": {"Dymatize": {"target_audience": "Strength athletes", "age_range": "", "occupation_distribution": [], "use_cases": [], "pain_points": [], "citations": ["profile-source"]}},
                "channel_analysis": "Official retail", "summary": "Qualitative market signals", "citations": ["market-source"],
            }),
        ]
        for phase, analysis, expected in cases:
            with self.subTest(phase=phase):
                payloads = await self.capture_payloads(phase, analysis, {})
                snapshot = next(p for p in payloads if "summary" in p)
                self.assertEqual(snapshot, expected)

    async def test_current_product_contract_is_sent_with_scope_dimensions_and_status_meanings(self):
        analysis = ProductAnalysis(
            feature_matrix=[FeatureComparison("Safety certification", {"ON": "⚪", "Dymatize": "🔶"})],
            summary="分片恢复：来源不足，未知格保持⚪。",
        )
        payloads = await self.capture_payloads(
            "product", analysis, {"Dymatize": CompetitorData(name="Dymatize")},
            product_name="ON", sub_dimensions="1. **Safety certification**: available batch tests",
        )
        contract = next((p for p in payloads if p.get("analysis_type") == "product"), None)
        self.assertIsNotNone(contract)
        self.assertEqual(contract["schema_fields"], ["feature_matrix", "competitive_advantages", "differentiation_points", "summary", "citations"])
        self.assertEqual(contract["sub_dimensions"], "1. **Safety certification**: available batch tests")
        self.assertEqual(contract["feature_dimensions"], ["Safety certification"])
        self.assertEqual(contract["compared_entities"], ["ON", "Dymatize"])
        self.assertEqual(contract["status_legend"]["⚪"], "unknown_evidence")
        self.assertEqual(contract["status_legend"]["❌"], "explicitly_unsupported")

    async def test_pricing_contract_carries_actual_dimensions_and_native_price_text(self):
        analysis = PricingAnalysis(summary="同一入住日期、房型与取消条件才可比价")
        analysis.dimension_comparison = [FeatureComparison(
            "取消条件", {"全季": "资料不足", "酒店B": "提前24小时可取消"})]
        payloads = await self.capture_payloads(
            "pricing", analysis, {"酒店B": CompetitorData(name="酒店B")},
            product_name="全季", sub_dimensions="1. **取消条件**：同日期房型的退订条件",
        )
        contract = next(p for p in payloads if p.get("analysis_type") == "pricing")
        self.assertEqual(contract.get("pricing_dimensions"), ["取消条件"])
        self.assertEqual(contract.get("compared_entities"), ["全季", "酒店B"])
        self.assertEqual(contract.get("value_kind"), "native_price_or_terms_text")
        self.assertEqual(contract.get("unknown_value"), "资料不足")
