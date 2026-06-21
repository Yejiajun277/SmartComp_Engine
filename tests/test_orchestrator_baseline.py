# -*- coding: utf-8 -*-
"""Baseline tests for the legacy Orchestrator flow.

These tests intentionally avoid LangGraph. They pin the current orchestration
behavior with fake agents so the migration can compare against a stable baseline.
"""

import asyncio
import contextlib
import io
import time
import unittest

import config
from agents.quality_agent import QualityAgent
from agents.strategy_agent import StrategyAgent
from core.artifact_store import to_jsonable
from core.orchestrator import Orchestrator
from models.domain import (
    ActionItem,
    Citation,
    CompetitorData,
    CompetitorInfo,
    CompetitorList,
    DimensionConfig,
    FeatureComparison,
    FeatureItem,
    MarketAnalysis,
    MarketShareItem,
    PricingAnalysis,
    PricingItem,
    ProductAnalysis,
    ProductCategory,
    QATimeline,
    QualityCheckResult,
    QualityIssue,
    StrategyReport,
    SubDimension,
    UserProfile,
    UserReputation,
)


def competitor_list(names=("CompA", "CompB")):
    return CompetitorList(
        product_name="Target",
        product_category="Collaboration",
        competitors=[
            CompetitorInfo(name=name, brief=f"{name} brief", relevance="HIGH")
            for name in names
        ],
        search_keywords_used=["target competitors"],
    )


def competitor_data(name):
    return CompetitorData(
        name=name,
        product_features=[
            FeatureItem(name="Chat", description="Team messaging"),
            FeatureItem(name="Docs", description="Document collaboration"),
        ],
        market_share="10%",
        user_reviews="Users mention stable collaboration features.",
        strengths="Strong workflow coverage.",
        weaknesses="Setup is complex.",
        channels="Direct sales and partners.",
        citations=[
            Citation(
                id=f"{name}:source:1",
                title=f"{name} source",
                url=f"https://example.com/{name.lower()}",
                competitor=name,
            )
        ],
    )


def target_data():
    data = competitor_data("Target")
    data.strengths = "Integrated target workflow."
    return data


def dimension_config():
    return DimensionConfig(
        product_category=ProductCategory(level1="Software", level2="Collaboration"),
        product_sub_dimensions=[
            SubDimension(name="Core", description="Core capability"),
            SubDimension(name="UX", description="User experience"),
        ],
        pricing_sub_dimensions=[
            SubDimension(name="Model", description="Pricing model"),
            SubDimension(name="Value", description="Value for money"),
        ],
        reasoning="Fixture dimensions",
    )


def product_analysis():
    return ProductAnalysis(
        feature_matrix=[
            FeatureComparison(
                feature="Chat",
                values={"Target": "✅", "CompA": "✅", "CompB": "🔶"},
            ),
            FeatureComparison(
                feature="Docs",
                values={"Target": "✅", "CompA": "🔶", "CompB": "✅"},
            ),
            FeatureComparison(
                feature="AI",
                values={"Target": "🔶", "CompA": "❌", "CompB": "🔶"},
            ),
        ],
        differentiation_points=["Integrated workflow"],
        summary="Target has a differentiated integrated workflow.",
    )


def pricing_analysis():
    return PricingAnalysis(
        pricing_comparison=[
            PricingItem(
                competitor="CompA",
                free_tier="Free team plan",
                paid_tier="$10/user/month",
                pricing_model="Seat subscription",
            ),
            PricingItem(
                competitor="CompB",
                free_tier="Trial",
                paid_tier="$15/user/month",
                pricing_model="Seat subscription",
            ),
        ],
        pricing_strategy_analysis="Seat pricing is common.",
        value_ranking=["Target", "CompA", "CompB"],
        summary="Target can compete on bundled value.",
    )


def market_analysis():
    return MarketAnalysis(
        market_share_data=[
            MarketShareItem(competitor="CompA", share_estimate="10%", trend="stable"),
            MarketShareItem(competitor="CompB", share_estimate="8%", trend="rising"),
        ],
        growth_trends="The category is growing steadily.",
        user_reputation={
            "CompA": UserReputation(score="8/10", keywords=["stable"]),
            "CompB": UserReputation(score="7/10", keywords=["modern"]),
        },
        user_profiles={
            "CompA": UserProfile(target_audience="SMB teams"),
            "CompB": UserProfile(target_audience="Enterprise teams"),
        },
        channel_analysis="Vendors use direct and partner channels.",
        summary="The market rewards integrated collaboration suites.",
    )


def strategy_report():
    return StrategyReport(
        product_name="Target",
        competitor_count=2,
        target_product_data=target_data(),
        overall_positioning="Target should position around integrated workflow.",
        differentiation_strategy={
            "core_differentiator": "Integrated workflow",
            "supporting_points": ["Chat", "Docs"],
        },
        action_plan=[
            ActionItem(
                priority="P0",
                action="Strengthen integrated workflow messaging.",
                timeline="2 weeks",
                expected_impact="Clearer differentiation",
            ),
            ActionItem(
                priority="P1",
                action="Bundle core collaboration features.",
                timeline="1 month",
                expected_impact="Higher perceived value",
            ),
        ],
        risk_assessment="Competitors may discount seat pricing.",
        product_analysis_summary="Strong workflow integration.",
        pricing_analysis_summary="Bundled value opportunity.",
        market_analysis_summary="Growing collaboration category.",
        summary="Target should compete through workflow integration.",
    )


def qa_result(phase, target_agent, passed=True, attempt=1, fail_score=50.0):
    issues = []
    if not passed:
        issues = [
            QualityIssue(
                severity="critical",
                category="completeness",
                field=f"{phase}.field",
                description=f"{phase} failed",
                suggestion="Fix fixture issue",
            )
        ]
    return QualityCheckResult(
        phase=phase,
        target_agent=target_agent,
        passed=passed,
        score=100.0 if passed else fail_score,
        issues=issues,
        attempt=attempt,
    )


class FakeDiscoveryAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.llm_logs = []

    async def run(self, product_description, max_competitors):
        self.calls.append((product_description, max_competitors))
        return self.result


class FakeCollectionAgent:
    def __init__(self):
        self.target_calls = []
        self.run_feedbacks = []
        self.supplement_calls = []
        self.llm_logs = []
        self._search_texts = {"CompA": "source text A", "CompB": "source text B"}

    def collect_target_product(self, product_description, product_name, feedback=""):
        self.target_calls.append((product_description, product_name, feedback))
        return target_data()

    async def run(self, product_description, competitors, feedback=""):
        self.run_feedbacks.append(feedback)
        return {c.name: competitor_data(c.name) for c in competitors.competitors}

    def get_search_texts(self):
        return dict(self._search_texts)

    def supplement_missing_fields(self, product_name, competitors_data, missing_fields):
        self.supplement_calls.append((product_name, dict(missing_fields)))
        return competitors_data


class FakeDimensionAgent:
    def __init__(self):
        self.calls = []
        self.llm_logs = []

    async def run(self, product_description, competitors):
        self.calls.append((product_description, competitors.product_name))
        return dimension_config()


class FakeAnalysisAgent:
    def __init__(self, analysis_type, delay=0.0):
        self.analysis_type = analysis_type
        self.delay = delay
        self.feedbacks = []
        self.starts = []
        self.ends = []
        self.llm_logs = []

    async def run(self, *args, **kwargs):
        self.starts.append(time.perf_counter())
        self.feedbacks.append(kwargs.get("feedback", ""))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.analysis_type == "product":
            result = product_analysis()
        elif self.analysis_type == "pricing":
            result = pricing_analysis()
        else:
            result = market_analysis()
        self.ends.append(time.perf_counter())
        return result


class FakeStrategyAgent:
    def __init__(self):
        self.feedbacks = []
        self.llm_logs = []
        self.formatter = StrategyAgent()

    async def run(self, *args, **kwargs):
        self.feedbacks.append(kwargs.get("feedback", ""))
        report = strategy_report()
        report.competitor_count = args[1]
        report.target_product_data = kwargs.get("target_product_data")
        if report.target_product_data:
            for citation in report.target_product_data.citations:
                report.citation_index.add(citation)
        for data in (kwargs.get("competitors_data") or {}).values():
            for citation in data.citations:
                report.citation_index.add(citation)
        return report

    def format_report(self, report):
        return f"REPORT:{report.product_name}:{len(report.action_plan)}"

    def format_html_report(self, *args, **kwargs):
        return self.formatter.format_html_report(*args, **kwargs)


class FakeQualityAgent:
    def __init__(
        self,
        collection_passes=None,
        analysis_passes=None,
        strategy_passes=None,
    ):
        self.collection_passes = list(collection_passes or [True])
        self.analysis_passes = {
            "product": list((analysis_passes or {}).get("product", [True])),
            "pricing": list((analysis_passes or {}).get("pricing", [True])),
            "market": list((analysis_passes or {}).get("market", [True])),
        }
        self.strategy_passes = list(strategy_passes or [True])
        self.timeline = QATimeline(max_retries=QualityAgent.MAX_RETRIES)
        self.feedback_requests = []
        self.missing_fields = {}
        self.llm_logs = []

    async def check_collection(
        self,
        competitors_data,
        original_search_texts,
        competitor_list=None,
        attempt=1,
    ):
        passed = self.collection_passes.pop(0)
        return qa_result("collection", "CollectionAgent", passed, attempt)

    async def check_analysis(self, analysis_type, analysis, competitors_data, attempt=1):
        passed = self.analysis_passes[analysis_type].pop(0)
        target = {
            "product": "ProductAgent",
            "pricing": "PricingAgent",
            "market": "MarketAgent",
        }[analysis_type]
        # Strictly increasing fail score so the "score-not-improving" short-circuit
        # pass does not trigger, keeping the genuine exhaustion path testable.
        return qa_result(analysis_type, target, passed, attempt, fail_score=attempt * 10.0)

    async def check_strategy(
        self,
        report,
        product_analysis,
        pricing_analysis,
        market_analysis,
        attempt=1,
    ):
        passed = self.strategy_passes.pop(0)
        return qa_result("strategy", "StrategyAgent", passed, attempt)

    def build_feedback(self, result):
        feedback = f"feedback:{result.phase}:{result.target_agent}:{result.attempt}"
        self.feedback_requests.append(feedback)
        return feedback

    def extract_missing_fields(self, result, competitors_data=None):
        return dict(self.missing_fields)

    def build_supplement_feedback(self, missing_fields):
        feedback = f"supplement:{','.join(sorted(missing_fields))}"
        self.feedback_requests.append(feedback)
        return feedback


class NullAgent:
    def __init__(self):
        self.llm_logs = []

    def __getattr__(self, name):
        raise AssertionError(f"Unexpected call to NullAgent.{name}")


class BaselineOrchestrator(Orchestrator):
    def __init__(self):
        super().__init__()
        self.saved_artifacts = []
        self.finalized = []

    def _start_artifacts(self, product_description, max_competitors):
        self.run_dir = "test-run"
        self._run_meta = {}
        self.artifact_store = None

    def _save_artifact_json(self, name, data):
        self.saved_artifacts.append(name)

    def _finalize_artifacts(self, status, product_name, competitor_count):
        self.finalized.append(
            {
                "status": status,
                "product_name": product_name,
                "competitor_count": competitor_count,
            }
        )

    def _save_run_meta(self):
        pass


def make_orchestrator(
    competitors=None,
    collection_passes=None,
    analysis_passes=None,
    strategy_passes=None,
    analysis_delay=0.0,
):
    orch = BaselineOrchestrator()
    orch.discovery_agent = FakeDiscoveryAgent(competitors or competitor_list())
    orch.collection_agent = FakeCollectionAgent()
    orch.dimension_agent = FakeDimensionAgent()
    orch.product_agent = FakeAnalysisAgent("product", delay=analysis_delay)
    orch.pricing_agent = FakeAnalysisAgent("pricing", delay=analysis_delay)
    orch.market_agent = FakeAnalysisAgent("market", delay=analysis_delay)
    orch.strategy_agent = FakeStrategyAgent()
    orch.quality_agent = FakeQualityAgent(
        collection_passes=collection_passes,
        analysis_passes=analysis_passes,
        strategy_passes=strategy_passes,
    )
    return orch


async def run_quietly(orchestrator, *args, **kwargs):
    stdout = io.StringIO()
    old_flag = config.USE_LANGGRAPH_WORKFLOW
    config.USE_LANGGRAPH_WORKFLOW = False
    try:
        with contextlib.redirect_stdout(stdout):
            return await orchestrator.analyze(*args, **kwargs)
    finally:
        config.USE_LANGGRAPH_WORKFLOW = old_flag


class LegacyOrchestratorBaselineTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_competitors_stops_early(self):
        empty = CompetitorList(product_name="Target", competitors=[])
        orch = make_orchestrator(competitors=empty)
        orch.collection_agent = NullAgent()
        orch.dimension_agent = NullAgent()
        orch.product_agent = NullAgent()
        orch.pricing_agent = NullAgent()
        orch.market_agent = NullAgent()
        orch.strategy_agent = NullAgent()
        orch.quality_agent = NullAgent()

        report = await run_quietly(orch, "Target", 2)

        self.assertEqual(report.product_name, "Target")
        self.assertEqual(report.competitor_count, 0)
        self.assertEqual(
            orch.finalized[-1],
            {
                "status": "stopped_no_competitors",
                "product_name": "Target",
                "competitor_count": 0,
            },
        )
        self.assertEqual(
            orch.saved_artifacts,
            ["01_competitor_list.json", "07_strategy_report.json", "llm_logs.json"],
        )

    async def test_happy_path_call_order_and_outputs(self):
        orch = make_orchestrator()

        report = await run_quietly(orch, "Target product", 2)

        self.assertEqual(report.product_name, "Target")
        self.assertEqual(report.competitor_count, 2)
        self.assertEqual(len(report.qa_timeline.checks), 5)
        self.assertEqual(
            [check.phase for check in report.qa_timeline.checks],
            ["collection", "product", "pricing", "market", "strategy"],
        )
        self.assertEqual(orch.collection_agent.run_feedbacks, [""])
        self.assertEqual(orch.strategy_agent.feedbacks, [""])
        self.assertEqual(orch.finalized[-1]["status"], "completed")
        for name in [
            "00_target_product_data.json",
            "01_competitor_list.json",
            "02_competitors_data.json",
            "02_search_texts.json",
            "03_dimension_config.json",
            "04_product_analysis.json",
            "05_pricing_analysis.json",
            "06_market_analysis.json",
            "07_strategy_report.json",
            "qa_timeline.json",
            "llm_logs.json",
        ]:
            self.assertIn(name, orch.saved_artifacts)
        self.assertIs(orch._last_product_analysis, orch._last_product_analysis)
        self.assertEqual(orch._last_competitor_list.product_name, "Target")

    async def test_collection_quality_retry_feedback(self):
        orch = make_orchestrator(collection_passes=[False, True])

        report = await run_quietly(orch, "Target product", 2)

        self.assertEqual(
            orch.collection_agent.run_feedbacks,
            ["", "feedback:collection:CollectionAgent:1"],
        )
        self.assertEqual(
            [check.phase for check in report.qa_timeline.checks[:2]],
            ["collection", "collection"],
        )
        self.assertEqual(report.qa_timeline.total_retries, 1)

    async def test_analysis_quality_retry_is_targeted(self):
        orch = make_orchestrator(
            analysis_passes={
                "product": [False, True],
                "pricing": [True],
                "market": [True],
            }
        )

        report = await run_quietly(orch, "Target product", 2)

        self.assertEqual(
            orch.product_agent.feedbacks,
            ["", "feedback:product:ProductAgent:1"],
        )
        self.assertEqual(orch.pricing_agent.feedbacks, [""])
        self.assertEqual(orch.market_agent.feedbacks, [""])
        self.assertEqual(
            [check.phase for check in report.qa_timeline.checks],
            ["collection", "product", "product", "pricing", "market", "strategy"],
        )

    async def test_strategy_quality_retry_feedback(self):
        orch = make_orchestrator(strategy_passes=[False, True])

        report = await run_quietly(orch, "Target product", 2)

        self.assertEqual(
            orch.strategy_agent.feedbacks,
            ["", "feedback:strategy:StrategyAgent:1"],
        )
        self.assertEqual(
            [check.phase for check in report.qa_timeline.checks[-2:]],
            ["strategy", "strategy"],
        )

    async def test_parallel_analysis_runtime(self):
        orch = make_orchestrator(analysis_delay=0.2)

        start = time.perf_counter()
        await run_quietly(orch, "Target product", 2)
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 0.5)
        starts = [
            orch.product_agent.starts[0],
            orch.pricing_agent.starts[0],
            orch.market_agent.starts[0],
        ]
        self.assertLess(max(starts) - min(starts), 0.05)

    async def test_html_and_json_report_format_smoke(self):
        orch = make_orchestrator()
        report = await run_quietly(orch, "Target product", 2)

        html = orch.strategy_agent.format_html_report(
            report,
            product_analysis=orch._last_product_analysis,
            pricing_analysis=orch._last_pricing_analysis,
            market_analysis=orch._last_market_analysis,
            competitor_list=orch._last_competitor_list,
            competitors_data=orch._last_competitors_data,
            timings=orch.get_timings(),
        )
        report_json = to_jsonable(report)

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Target", html)
        self.assertIn("qa_timeline", report_json)
        self.assertIn("action_plan", report_json)
        self.assertEqual(report_json["product_name"], "Target")


if __name__ == "__main__":
    unittest.main()
