"""A model check must finish before a QA gate can claim success."""
import json
import unittest
from unittest.mock import patch

from agents.quality_agent import QualityAgent
from models.domain import (
    Citation, FeatureComparison, FeatureItem, PricingTier, QualityCheckResult,
    SWOTAnalysis, SWOTCrossStrategy, SWOTQuadrant,
)
from tests.test_orchestrator_baseline import (
    competitor_data, market_analysis, pricing_analysis, product_analysis,
    strategy_report,
)


SUCCESS = json.dumps({"passed": True, "score": 100, "issues": []})
CRITICAL = json.dumps({"issues": [{
    "severity": "critical", "category": "hallucination", "field": "summary",
    "description": "The room price omits its city and date scope.",
    "suggestion": "Retain the source scope rather than a universal price.",
}]})


class QualityRuntimeIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def check_phase(self, phase, responses, agent=None):
        agent = agent or QualityAgent()
        self.calls = []
        queue = iter(responses)

        async def transport(system, message, **kwargs):
            content, finish = next(queue)
            self.calls.append((message, kwargs["max_tokens"]))
            return {"content": content, "finish_reason": finish,
                    "timestamp": "", "model": "fixture"}

        data = {name: competitor_data(name) for name in ("CompA", "CompB")}
        for item in data.values():
            item.pricing_tiers = [PricingTier("Room", "399 yuan/night")]
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            if phase == "collection":
                result = await agent.check_collection(data, {name: "public source" for name in data})
            elif phase == "strategy":
                result = await agent.check_strategy(strategy_report(), product_analysis(),
                                                    pricing_analysis(), market_analysis())
            else:
                analysis = {"product": product_analysis, "pricing": pricing_analysis,
                            "market": market_analysis}[phase]()
                result = await agent.check_analysis(phase, analysis, data)
        return result, agent

    async def test_async_json_with_reason_rejects_parseable_but_truncated_result(self):
        async def transport(*args, **kwargs):
            return {"content": SUCCESS, "finish_reason": "length"}
        agent = QualityAgent()
        with patch("agents.base_agent.async_llm_call", transport):
            result, reason = await agent.async_ask_llm_json_with_reason("check")
        self.assertEqual(result, {})
        self.assertIn("truncated", reason)
        self.assertEqual(agent.llm_logs[-1]["parse_error"], reason)

    def test_sync_json_with_reason_rejects_parseable_but_truncated_result(self):
        agent = QualityAgent()
        with patch("agents.base_agent.llm_call", return_value={"content": SUCCESS, "finish_reason": "length"}):
            result, reason = agent.ask_llm_json_with_reason("check")
        self.assertEqual(result, {})
        self.assertIn("truncated", reason)

    async def test_truncated_check_retries_same_facts_and_keeps_complete_critical_finding(self):
        for phase in ("collection", "product", "pricing", "market", "strategy"):
            with self.subTest(phase=phase):
                result, _ = await self.check_phase(phase, [(SUCCESS, "length"), (CRITICAL, "stop")])
                self.assertFalse(result.passed)
                self.assertEqual(result.hallucination_status, "found")
                self.assertTrue(any(issue.description.startswith("The room price") for issue in result.issues))
                self.assertEqual([call[1] for call in self.calls], [8192, 12288])
                # Recovery checks the original artifact, rather than regenerating
                # the data or trying to certify the truncated response.
                self.assertTrue(self.calls[1][0].startswith(self.calls[0][0]))

    async def test_invalid_stop_json_is_rechecked_once_before_a_successful_gate(self):
        result, _ = await self.check_phase("pricing", [('{"issues":[', "stop"), (SUCCESS, "stop")])
        self.assertTrue(result.passed)
        self.assertEqual(result.hallucination_status, "passed")
        self.assertEqual(len(self.calls), 2)

    async def test_exhausted_model_check_never_passes_or_caches_fields(self):
        for phase in ("collection", "product", "pricing", "market", "strategy"):
            with self.subTest(phase=phase):
                result, agent = await self.check_phase(phase, [("{", "length"), ("{", "length")])
                self.assertFalse(result.passed)
                self.assertFalse(result.degraded)
                self.assertEqual(result.hallucination_status, "failed")
                self.assertEqual(len(self.calls), 2)
                self.assertTrue(any(i.field == "__hallucination_check__" and i.severity == "critical"
                                    for i in result.issues))
                self.assertEqual(agent._passed_fields, set())

    async def test_wrong_issues_schema_is_an_incomplete_check_instead_of_an_empty_pass(self):
        for malformed in ({"passed": True}, {"issues": None}, {"issues": ["bad"]},
                          {"issues": [{"severity": "critical", "type": "citation_invalid"}]}):
            with self.subTest(malformed=malformed):
                payload = json.dumps(malformed)
                try:
                    result, _ = await self.check_phase("product", [(payload, "stop"), (payload, "stop")])
                except (TypeError, AttributeError) as exc:
                    self.fail(f"Malformed model issues crashed the gate instead of remaining unfinished: {exc}")
                self.assertFalse(result.passed)
                self.assertEqual(result.hallucination_status, "failed")
                self.assertEqual(len(self.calls), 2)

    async def test_a_complete_first_check_does_not_make_extra_model_calls(self):
        result, _ = await self.check_phase("pricing", [(SUCCESS, "stop")])
        self.assertTrue(result.passed)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result.hallucination_status, "passed")

    async def test_a_new_critical_finding_cannot_be_hidden_by_prior_field_cache(self):
        _, agent = await self.check_phase("collection", [(SUCCESS, "stop")])
        critical = json.loads(CRITICAL)
        critical["issues"][0]["field"] = "CompA.strengths"
        result, _ = await self.check_phase("collection", [(json.dumps(critical), "stop")], agent)
        self.assertFalse(result.passed)
        self.assertTrue(any(i.field == "CompA.strengths" and i.severity == "critical" for i in result.issues))

    async def test_collection_check_receives_full_saved_fields_and_late_sources(self):
        item = competitor_data("CompA")
        item.strengths = "s" * 250 + "SOURCE_SCOPE_MUST_SURVIVE"
        item.weaknesses = "w" * 250 + "UNRESOLVED_LIMITATION"
        item.user_reviews = "r" * 250 + "REVIEW_CONDITION"
        item.pricing_tiers = [PricingTier("Room", "399/night", ["CITY_DATE_CONDITION"], ["late:source"])]
        item.product_features = [FeatureItem("Room", "Hotel room", ["late:source"])]
        item.citations = [Citation(f"source:{i}", f"Source{i}", f"https://example.test/{i}",
                                  f"FULL_SNIPPET_{i}") for i in range(40)]
        search = "x" * 8200 + "LATE_PUBLIC_EVIDENCE"
        prompts = []

        async def transport(system, message, **kwargs):
            prompts.append(message)
            return {"content": SUCCESS, "finish_reason": "stop"}

        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            await QualityAgent().check_collection({"CompA": item}, {"CompA": search})
        prompt = prompts[0]
        for expected in ("SOURCE_SCOPE_MUST_SURVIVE", "UNRESOLVED_LIMITATION", "REVIEW_CONDITION",
                         "CITY_DATE_CONDITION", "late:source", "FULL_SNIPPET_39", "LATE_PUBLIC_EVIDENCE"):
            self.assertIn(expected, prompt)
        raw = prompt.split("### LLM 提取的结构化数据", 1)[1].lstrip()
        snapshot, _ = json.JSONDecoder().raw_decode(raw)
        self.assertEqual(snapshot["CompA"]["pricing_tiers"][0]["features"], ["CITY_DATE_CONDITION"])
        self.assertEqual(snapshot["CompA"]["product_features"][0]["citations"], ["late:source"])
        self.assertEqual(len(snapshot["CompA"]["citations"]), 40)

    async def test_analysis_checker_receives_source_scope_limits_as_its_contract(self):
        await self.check_phase("pricing", [(SUCCESS, "stop")])
        prompt = self.calls[0][0]
        raw = prompt.split("### 当前分析契约", 1)[1].lstrip()
        contract, _ = json.JSONDecoder().raw_decode(raw)
        self.assertEqual(contract.get("scope_policy"), {
            "retain_source_qualifiers": True, "missing_scope": "unknown",
            "cross_scope_comparison_requires_evidence": True,
            "unqualified_claim_from_limited_source": "critical_citation",
        })
        self.assertNotIn("不要重新验证", prompt)
        self.assertNotIn("每个分析类型最多标记 1 个", prompt)

    async def test_strategy_check_sees_saved_swot_full_analyses_and_sources_without_process_logs(self):
        product, pricing, market = product_analysis(), pricing_analysis(), market_analysis()
        pricing.dimension_comparison = [FeatureComparison("Room type", {"Target": "CITY_DATE_PRICE_SCOPE"})]
        pricing.comparable_basis = {"evidence": "BASIS_MARKER"}
        pricing.source_scope_notes = {"Target": ["INCOMPLETE_QUOTE_SCOPE"]}
        market.user_profiles["CompA"].occupation_distribution = ["PROFILE_FROM_REPORT"]
        report = strategy_report()
        report.swot = SWOTAnalysis(strengths=SWOTQuadrant(["Saved SWOT fact"]),
                                   cross_strategies=SWOTCrossStrategy(so=["Saved cross strategy"]))
        report.citation_index.add(Citation("report-source", "Saved source", "https://example.test/report",
                                           "Full saved source excerpt"))
        report.raw_llm_logs = [{"result": "RAW_TRANSPORT_SHOULD_NOT_BE_QA_FACT"}]
        report.qa_timeline.add_check(QualityCheckResult("collection", "QualityAgent", False, 0,
                                                       feedback_to_agent="FAILED_HISTORY_NOT_CURRENT_FACT"))
        prompts = []

        async def transport(system, message, **kwargs):
            prompts.append(message)
            return {"content": SUCCESS, "finish_reason": "stop"}

        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            await QualityAgent().check_strategy(report, product, pricing, market)
        prompt = prompts[0]
        for expected in ("Saved SWOT fact", "Saved cross strategy", "Full saved source excerpt",
                         "CITY_DATE_PRICE_SCOPE", "BASIS_MARKER", "INCOMPLETE_QUOTE_SCOPE", "PROFILE_FROM_REPORT"):
            self.assertIn(expected, prompt)
        self.assertNotIn("RAW_TRANSPORT_SHOULD_NOT_BE_QA_FACT", prompt)
        self.assertNotIn("FAILED_HISTORY_NOT_CURRENT_FACT", prompt)
        raw = prompt.split("### 三维分析结果", 1)[1].lstrip()
        analyses, _ = json.JSONDecoder().raw_decode(raw)
        self.assertEqual(analyses["pricing_analysis"]["source_scope_notes"], {"Target": ["INCOMPLETE_QUOTE_SCOPE"]})
        raw = prompt.split("### 策略报告", 1)[1].lstrip()
        facts, _ = json.JSONDecoder().raw_decode(raw)
        self.assertEqual(facts["swot"]["strengths"]["items"], ["Saved SWOT fact"])
        self.assertEqual(facts["citation_index"]["citations"]["report-source"]["snippet"], "Full saved source excerpt")


if __name__ == "__main__":
    unittest.main()
