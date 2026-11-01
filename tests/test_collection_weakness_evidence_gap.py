"""An absent negative review is a gap, not permission to invent weaknesses."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agents.quality_agent import QualityAgent
from agents.collection_agent import CollectionAgent
from core.collection_repair_plan import build_collection_repair_plan
from models.domain import Citation, QualityCheckResult, QualityIssue
from tests.test_target_collection_quality import entity


# Saved case 31410807, first collection QA: q5:r25 discusses the old machine
# before buying T12, whereas Dreame q5:r25 explicitly names a Z20 limitation.
OLD_MACHINE = (
    'Jun 12, 2022 — ”吸尘主机太重了，拖来拖去很麻烦。”'
    '“电线插头总是要拔来插去。”每次媳妇用吸尘器的时候，都能听到她的抱怨。'
    '我决定用小狗T12 Max Rinse减轻她的家务负担'
)
CURRENT_MODEL = (
    '追觅Z20Station旋锋版吸尘器怎么样？深度测评，优缺点客观分析\n'
    '❌ 缺点：\n1. 集尘噪音：约 80-84 分贝，虽然只有10 秒，但夜间使用可能影响浅眠者'
)


class CollectionWeaknessEvidenceGapTests(unittest.IsolatedAsyncioTestCase):
    async def review(self, name, source, issues=(), *, finish="stop", evidence=True):
        agent = QualityAgent()
        data = entity(name)
        data.weaknesses = ""
        for citation in data.citations:
            citation.snippet = source if evidence else ""
        before = deepcopy(asdict(data))
        calls = []

        async def transport(system, message, **kwargs):
            calls.append((system, message))
            return {"content": json.dumps({"issues": list(issues)}, ensure_ascii=False),
                    "finish_reason": finish, "model": "offline-fixture"}

        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await agent.check_collection({name: data}, {name: source} if evidence else {})
        self.assertEqual(asdict(data), before, "QA must never manufacture or rewrite a fact")
        return agent, data, result, calls

    async def test_old_machine_complaints_do_not_force_current_model_weaknesses(self):
        name = "小狗 T12 系列"
        finding = {"severity": "warning", "category": "completeness", "field": name + ".weaknesses",
                   "description": "本次检索未见针对T12系列的明确差评要点；q5:r25的抱怨属于旧机。"}
        agent, data, result, calls = await self.review(name, OLD_MACHINE, [finding])
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.entity_review_trace[0]["completed"])
        self.assertTrue(result.passed)
        self.assertFalse(any(i.severity == "critical" for i in result.issues))
        self.assertTrue(any("资料缺口" in i.description for i in result.issues))
        self.assertNotIn("weaknesses", agent.extract_missing_fields(result, {name: data}).get(name, []))

    async def test_current_model_negative_source_omission_remains_critical(self):
        name = "追觅 Dreame（Z20 Station / V16S）"
        finding = {"severity": "critical", "category": "completeness", "field": name + ".weaknesses",
                   "description": "weaknesses为空字符串，但q5:r25明确列出Z20 Station集尘噪音缺点。"}
        agent, data, result, calls = await self.review(name, CURRENT_MODEL, [finding])
        self.assertEqual(len(calls), 1)
        self.assertIn(CURRENT_MODEL, calls[0][1].replace("\\n", "\n"))
        self.assertFalse(result.passed)
        self.assertTrue(result.entity_review_trace[0]["completed"])
        self.assertTrue(any(i.severity == "critical" and i.description == finding["description"]
                            for i in result.issues))
        self.assertIn("weaknesses", agent.extract_missing_fields(result, {name: data})[name])

    async def test_unfinished_semantic_review_cannot_accept_empty_weaknesses(self):
        _, _, result, calls = await self.review("Current", OLD_MACHINE, finish="length")
        self.assertEqual(len(calls), 2)
        self.assertFalse(result.passed)
        self.assertEqual(result.hallucination_status, "failed")
        self.assertFalse(result.entity_review_trace[0]["completed"])

    async def test_missing_original_sources_cannot_accept_empty_weaknesses(self):
        _, _, result, calls = await self.review("Current", "", evidence=False)
        self.assertEqual(calls, [])
        self.assertFalse(result.passed)
        self.assertEqual(result.entity_review_trace[0]["failure_reason"], "missing_original_sources")

    def test_non_string_weaknesses_remains_schema_error_and_repairable(self):
        agent = QualityAgent()
        data = entity("Current")
        object.__setattr__(data, "weaknesses", None)
        issues = agent._check_collection_completeness({"Current": data})
        self.assertTrue(any(i.field == "Current.weaknesses" and i.severity == "critical"
                            and i.category == "schema" for i in issues))

    def test_nonempty_truncated_weaknesses_keeps_existing_missing_field_detection(self):
        data = entity("Current")
        data.weaknesses = "An attributed source limitation whose description has been cut off midway through"
        result = QualityCheckResult("collection", "CollectionAgent", passed=False, score=0)
        self.assertIn("weaknesses", QualityAgent().extract_missing_fields(result, {"Current": data}).get("Current", []))

    def test_semantic_prompt_requires_scoped_negative_source_review(self):
        prompt = QualityAgent()._prompt_check_collection
        self.assertIn("weaknesses", prompt)
        self.assertIn("旧型号", prompt)
        self.assertIn("负面", prompt)
        self.assertIn("critical", prompt)

    async def test_gap_warning_does_not_authorize_old_machine_quote_during_other_repair(self):
        name = "小狗 T12 系列"
        data = entity(name)
        data.weaknesses = ""
        data.citations[0].snippet = OLD_MACHINE
        issues = [QualityIssue("warning", "completeness", name + ".weaknesses", "缺口；勿借旧机负评"),
                  QualityIssue("critical", "citation", name + ".strengths", "Correct this other field")]
        plan = build_collection_repair_plan({name: data}, issues)
        self.assertNotIn("weaknesses", plan[name]["text_fields"])
        source_id = data.citations[0].id
        data.citations[0].snippet += "\nSupported current-model capability."
        # Compile after the source mutation so snapshot integrity remains real.
        plan = build_collection_repair_plan({name: data}, issues)
        valid = {"strengths": [{"source_id": source_id, "exact_quote": "Supported current-model capability."}]}
        for include_forbidden in (False, True):
            payload = deepcopy(valid)
            if include_forbidden:
                payload["weaknesses"] = [{"source_id": source_id, "exact_quote": OLD_MACHINE}]
            async def transport(*args, **kwargs):
                return {"content": json.dumps(payload), "finish_reason": "stop"}
            agent = CollectionAgent()
            before = deepcopy(data)
            with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
                result = await agent.async_reextract_saved_sources(name, "Scope", {name: data},
                    {name: data.citations[0].snippet}, repair_plan=plan)
            self.assertEqual(data, before)
            self.assertEqual(result[name].weaknesses, "")
            if include_forbidden:
                self.assertEqual(result[name], before, "Unauthorized extra field rolls back the entire entity")
                self.assertEqual(agent.get_repair_outcomes()[0]["status"], "failed")
            else:
                self.assertNotEqual(result[name].strengths, before.strengths)
                self.assertEqual(agent.get_repair_outcomes()[0]["status"], "accepted")

    def test_critical_current_model_omission_still_authorizes_repair_after_gap_warning(self):
        data = entity("Current")
        data.weaknesses = ""
        warning = QualityIssue("warning", "completeness", "Current.weaknesses", "Unknown gap")
        critical = QualityIssue("critical", "completeness", "Current.weaknesses", "Source negative omitted")
        for issues in ([warning, critical], [critical, warning]):
            self.assertIn("weaknesses", build_collection_repair_plan({"Current": data}, issues)["Current"]["text_fields"])

    def test_empty_weakness_warning_category_or_wording_cannot_grant_authority(self):
        data = entity("Current")
        data.weaknesses = " "
        for category in ("completeness", "citation", "hallucination"):
            warning = QualityIssue("warning", category, "Current.weaknesses", "Arbitrary text; no language heuristic")
            self.assertNotIn("weaknesses", build_collection_repair_plan({"Current": data}, [warning])["Current"]["text_fields"])
            data.weaknesses = "An existing attributed negative needs a scope correction."
            self.assertIn("weaknesses", build_collection_repair_plan({"Current": data}, [warning])["Current"]["text_fields"])
            data.weaknesses = " "

    async def test_saved_qa1_warning_vs_critical_controls_actual_source_quote_patch(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" /
                              "collection_weaknesses_31410807.json").read_text(encoding="utf-8"))
        for case in fixture["cases"]:
            name = case["entity"]
            with self.subTest(entity=name):
                data = entity(name)
                data.weaknesses = case["original_weaknesses"]
                source = case["complete_original_source_record"]
                data.citations.append(Citation(**source))
                # The fixture keeps both original issues. Only the last one is
                # the completed semantic finding; recompute the old mechanical
                # finding with today's rule rather than rewriting saved QA1.
                semantic = case["qa1_weakness_issues"][-1]
                async def quality_transport(*args, **kwargs):
                    return {"content": json.dumps({"issues": [semantic]}), "finish_reason": "stop"}
                quality = QualityAgent()
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", quality_transport):
                    result = await quality.check_collection({name: data}, {name: source["snippet"]})
                self.assertTrue(result.entity_review_trace[0]["completed"])
                negative_is_supported = semantic["severity"] == "critical"
                self.assertEqual(result.passed, not negative_is_supported)
                issues = result.issues + [QualityIssue("critical", "citation", name + ".strengths", "Other allowed correction")]
                plan = build_collection_repair_plan({name: data}, issues)
                self.assertEqual("weaknesses" in plan[name]["text_fields"], negative_is_supported)
                quote = case["after_patch_exact_evidence"][0]
                payload = {"weaknesses": [quote]}
                async def repair_transport(*args, **kwargs):
                    return {"content": json.dumps(payload), "finish_reason": "stop"}
                collection = CollectionAgent()
                before = deepcopy(data)
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", repair_transport):
                    after = await collection.async_reextract_saved_sources(name, "Scope", {name: data},
                        {name: source["snippet"]}, repair_plan=plan)
                self.assertEqual(data, before)
                self.assertEqual(collection.get_repair_outcomes()[0]["status"],
                                 "accepted" if negative_is_supported else "failed")
                if negative_is_supported:
                    self.assertIn(quote["exact_quote"], after[name].weaknesses)
                else:
                    self.assertEqual(after[name], before)


if __name__ == "__main__":
    unittest.main()
