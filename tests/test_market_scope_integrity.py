"""Market outputs retain collected scope instead of manufacturing statistics."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from agents.market_agent import MarketAgent
from models.domain import Citation, CompetitorData, FeatureItem


SHARE = "截至2024年记录出现47%，但统计主体、地区和样本未披露，不能视为该型号或全品牌全球份额。"
REVIEW = "2025年地区甲站点评分4.6/5（仅指定版本，样本120份，不代表全品牌）。"


def entity(name, *, rated=False):
    review = REVIEW if rated else "个别用户描述使用体验；没有公开评分、样本或人口统计。"
    return CompetitorData(name, product_features=[FeatureItem("Edition", "Named edition only")],
        market_share=SHARE, user_reviews=review, channels="仅限指定地区渠道，不代表全球覆盖。",
        citations=[Citation(f"{name}:q0:r0", "Market record", f"https://example.test/{name}/market",
                             snippet=SHARE, competitor=name),
                   Citation(f"{name}:q1:r1", "Named edition reviews", f"https://example.test/{name}/review",
                             snippet=review, competitor=name)])


def invented(name):
    return {"entity_sources": {},
            "market_share_data": [{"competitor": name, "share_estimate": "全球47%", "trend": "快速上升"}],
            "growth_trends": "全球增长999%", "channel_analysis": "覆盖999个地区",
            "user_reputation": {name: {"score": "8.5/10", "keywords": ["90%好评"]}},
            "user_profiles": {name: {"age_range": "18-35岁占80%", "occupation_distribution": ["学生70%"]}},
            "summary": "品牌全球份额47%，评分8.5/10，18-35岁占80%，全球增长999%。"}


class MarketScopeIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def run_agent(self, data, target=None, responses=None, *, llm=True):
        self.agent = MarketAgent()
        self.requests = []
        queue = list(responses or [(invented(next(iter(data), "Target")), "stop")])
        before, before_target = deepcopy(data), deepcopy(target)

        async def transport(system, prompt, **kwargs):
            self.requests.append((prompt, kwargs["max_tokens"]))
            payload, finish = queue.pop(0) if queue else ({"entity_sources": {}}, "stop")
            return {"content": json.dumps(payload, ensure_ascii=False), "finish_reason": finish}

        with patch("config.ENABLE_LLM", llm), patch("agents.base_agent.async_llm_call", transport):
            result = await self.agent.run("Target", data, target, "Retain the original entity/date/region scope.")
        self.assertEqual(data, before)
        self.assertEqual(target, before_target)
        return result

    def test_input_keeps_all_fields_and_complete_source_metadata_without_duplicate_raw_texts(self):
        item = entity("Rival")
        item.market_share += " SCOPE_MARKET_TAIL" * 80
        item.user_reviews += " SCOPE_REVIEW_TAIL" * 80
        item.channels += " SCOPE_CHANNEL_TAIL" * 80
        item.citations[0].snippet += " FULL_SOURCE_TAIL" * 80
        item.citations[0].query = "Original named edition query"
        item.search_sources = ["DUPLICATE_RAW_SEARCH_MUST_NOT_BE_APPENDED"]
        text = MarketAgent()._build_competitors_text("Target", {"Rival": item})
        for value in [item.market_share, item.user_reviews, item.channels,
                      item.citations[0].snippet, item.citations[0].query, item.citations[0].collected_at]:
            self.assertIn(value, text)
        self.assertNotIn("DUPLICATE_RAW_SEARCH_MUST_NOT_BE_APPENDED", text)

    async def test_normal_response_cannot_promote_unknown_scope_or_invent_ratings_profiles_and_summary(self):
        result = await self.run_agent({"Rival": entity("Rival")})
        self.assertEqual(result.market_share_data[0].share_estimate, SHARE)
        self.assertEqual(result.market_share_data[0].trend, "未知")
        self.assertEqual(result.user_reputation["Rival"].score, "未知")
        self.assertEqual(result.user_profiles["Rival"].age_range, "未知")
        self.assertEqual(result.user_profiles["Rival"].occupation_distribution, [])
        rendered = json.dumps(asdict(result), ensure_ascii=False)
        for claim in ["全球47%", "8.5/10", "18-35", "999%", "学生70%", "90%好评"]:
            self.assertNotIn(claim, rendered)
        self.assertIn(SHARE, result.summary)

    async def test_actual_rating_requires_entity_bound_full_original_scope_and_keeps_denominator(self):
        data = {"Rival": entity("Rival", rated=True)}
        result = await self.run_agent(data)
        self.assertEqual(result.user_reputation["Rival"].score, "4.6/5")
        self.assertEqual(result.user_reputation["Rival"].source_text, REVIEW)
        self.assertEqual(result.user_reputation["Rival"].citations, ["Rival:q1:r1"])
        self.assertIn("4.6/5", result.summary)
        self.assertNotIn("8.5/10", result.summary)

    async def test_estimated_or_multiple_platform_scores_remain_separate_original_material(self):
        for review in ["根据正面口碑估计评分8.5/10，没有实际测评样本。",
                       "平台甲2024年评分4.6/5；平台乙2025年另一地区评分4.6/5。",
                       "平台甲2024年评分4.6/5；平台乙2025年另一地区评分8.5/10。"]:
            with self.subTest(review=review):
                item = entity("Rival", rated=True)
                item.user_reviews = item.citations[1].snippet = review
                result = await self.run_agent({"Rival": item})
                self.assertEqual(result.user_reputation["Rival"].score, "未知")
                self.assertEqual(result.user_reputation["Rival"].source_text, review)

    async def test_translated_rating_stays_visible_without_claiming_source_has_no_score(self):
        item = entity("Rival", rated=True)
        item.citations[1].snippet = "In 2025, users of edition A in region A rated it 4.6 out of 5, from 120 reviews."
        result = await self.run_agent({"Rival": item})
        self.assertEqual(result.user_reputation["Rival"].score, "未知")
        self.assertIn("4.6/5", result.user_reputation["Rival"].source_text)
        self.assertNotIn("来源没有评分", result.summary)

    async def test_unbound_borrowed_or_scope_different_rating_cannot_become_a_score(self):
        for change in ["missing", "foreign_owner", "changed_scope"]:
            with self.subTest(change=change):
                item = entity("Rival", rated=True)
                if change == "missing":
                    item.citations = []
                elif change == "foreign_owner":
                    item.citations[1].competitor = "Another entity"
                else:
                    item.citations[1].snippet = "2023年另一地区和版本评分4.6/5，样本不同。"
                result = await self.run_agent({"Rival": item})
                self.assertEqual(result.user_reputation["Rival"].score, "未知")
                self.assertEqual(result.user_reputation["Rival"].source_text, REVIEW)
                self.assertEqual(result.user_reputation["Rival"].keywords, [])

    async def test_rule_and_normal_paths_keep_target_and_full_original_market_records(self):
        target, rival = entity("Target", rated=True), entity("Rival")
        target.market_share += " TARGET_SCOPE_TAIL" * 50
        data = {"Rival": rival}
        normal = await self.run_agent(data, target)
        fallback = await self.run_agent(data, target, llm=False)
        for result in [normal, fallback]:
            rows = {row.competitor: row for row in result.market_share_data}
            self.assertEqual(set(rows), {"Target", "Rival"})
            self.assertEqual(rows["Target"].share_estimate, target.market_share)
            self.assertEqual(rows["Rival"].share_estimate, SHARE)
            self.assertEqual(result.user_reputation["Target"].score, "4.6/5")
            self.assertEqual(result.user_reputation["Target"].source_text, REVIEW)
            self.assertIn(target.channels, result.channel_analysis)
            self.assertIn(target.market_share, result.summary)

    async def test_chunked_recovery_keeps_one_target_and_never_merges_entity_statistics(self):
        data = {name: entity(name) for name in ["Alpha", "Beta", "Gamma"]}
        result = await self.run_agent(data, entity("Target"),
            [(invented("Target"), "length"), (invented("Alpha"), "stop"), (invented("Beta"), "stop")])
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(all(budget == 8192 for _, budget in self.requests))
        self.assertEqual([row.competitor for row in result.market_share_data].count("Target"), 1)
        self.assertEqual({row.competitor for row in result.market_share_data}, {"Target", *data})
        self.assertTrue(all(row.share_estimate == SHARE for row in result.market_share_data))
        self.assertNotIn("999%", json.dumps(asdict(result), ensure_ascii=False))

    async def test_chunked_recovery_keeps_review_source_bindings_per_entity(self):
        data = {name: entity(name) for name in ["Alpha", "Beta"]}
        selector = {"entity_sources": {name: {"user_reviews": [f"{name}:q1:r1"]}
                                        for name in ["Target", "Alpha", "Beta"]}}
        result = await self.run_agent(data, entity("Target"),
            [(selector, "length"), (selector, "stop"), (selector, "stop")])
        for name in ["Target", "Alpha", "Beta"]:
            self.assertEqual(result.user_reputation[name].citations, [f"{name}:q1:r1"])

    async def test_incomplete_selectors_are_discarded_with_bounded_recovery(self):
        for finish in ["length", "content_filter", "", "unknown"]:
            with self.subTest(finish=finish):
                item = entity("Rival")
                selector = {"entity_sources": {"Rival": {"market_share": ["Rival:q1:r1"]}}}
                result = await self.run_agent({"Rival": item}, responses=[(selector, finish)])
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(result.market_share_data[0].citations, [])
                self.assertEqual(result.market_share_data[0].share_estimate, SHARE)
        data = {name: entity(name) for name in ["A", "B", "C", "D"]}
        await self.run_agent(data, responses=[({"entity_sources": {}}, "length")] * 7)
        self.assertEqual(len(self.requests), 7)

    def test_unknown_or_negated_trend_is_never_defaulted_to_stable(self):
        for value in ["", "未知", "资料不足", "无公开证据表明增长", "没有稳定趋势统计", None, 17]:
            with self.subTest(value=value):
                self.assertEqual(MarketAgent._normalize_trend(value), "未知")

    async def test_completed_source_selection_cannot_borrow_another_entity_catalog(self):
        alpha, beta = entity("Alpha"), entity("Beta")
        payload = {"entity_sources": {"Alpha": {"market_share": ["Beta:q0:r0", "Alpha:q0:r0"]}}}
        result = await self.run_agent({"Alpha": alpha, "Beta": beta}, responses=[(payload, "stop")])
        rows = {row.competitor: row for row in result.market_share_data}
        self.assertEqual(rows["Alpha"].citations, ["Alpha:q0:r0"])
        self.assertNotIn("Beta:q0:r0", rows["Alpha"].citations)

    async def test_completed_source_review_is_distinct_from_failed_and_unrequested_review(self):
        data = {"Rival": entity("Rival", rated=True)}
        selector = {"entity_sources": {"Rival": {"user_reviews": ["Rival:q1:r1"]}}}
        complete = await self.run_agent(data, responses=[(selector, "stop")])
        failed = await self.run_agent(data, responses=[(selector, "length")])
        local = await self.run_agent(data, llm=False)
        self.assertIn("来源对应核对已完成", complete.summary)
        self.assertIn("来源对应核对未完成", failed.summary)
        self.assertIn("尚未进行来源对应核对", local.summary)
        for result in [complete, failed, local]:
            self.assertIn(SHARE, result.summary)
            self.assertEqual(result.user_reputation["Rival"].source_text, REVIEW)
            self.assertEqual(result.user_reputation["Rival"].score, "4.6/5")
        self.assertNotIn("来源对应核对已完成", failed.summary)

    async def test_partial_recovery_marks_only_unfinished_entities_without_losing_checked_target(self):
        data = {name: entity(name) for name in ["Alpha", "Beta"]}
        selector = {"entity_sources": {name: {"user_reviews": [f"{name}:q1:r1"]}
                                        for name in ["Target", "Alpha", "Beta"]}}
        result = await self.run_agent(data, entity("Target"),
            [(selector, "length"), (selector, "stop"), (selector, "length")])
        note = result.summary.split("\n", 1)[0]
        self.assertIn("来源对应核对未完成：Beta", note)
        self.assertIn("已完成：Target、Alpha", note)
        self.assertEqual(result.user_reputation["Target"].citations, ["Target:q1:r1"])
        self.assertEqual(result.user_reputation["Alpha"].citations, ["Alpha:q1:r1"])
        self.assertEqual(result.user_reputation["Beta"].citations, [])
        self.assertEqual({row.competitor for row in result.market_share_data}, {"Target", "Alpha", "Beta"})
        self.assertTrue(all(row.share_estimate == SHARE for row in result.market_share_data))
        self.assertNotIn("分片", result.summary)
        self.assertNotIn("降级", result.summary)

    async def test_nested_unfinished_review_names_survive_merge_and_invalid_schema_is_not_completed(self):
        data = {name: entity(name) for name in ["A", "B", "C", "D"]}
        good = {"entity_sources": {name: {"market_share": [f"{name}:q0:r0"]} for name in data}}
        invalid = {"entity_sources": {"C": {"market_share": "C:q0:r0"}}}
        result = await self.run_agent(data, responses=[(good, "length"), (good, "stop"),
            (good, "length"), (invalid, "stop"), (good, "stop")])
        note = result.summary.split("\n", 1)[0]
        self.assertIn("来源对应核对未完成：C", note)
        self.assertIn("已完成：A、B、D", note)
        rows = {row.competitor: row for row in result.market_share_data}
        self.assertEqual(rows["C"].citations, [])
        self.assertEqual(rows["D"].citations, ["D:q0:r0"])
        self.assertEqual(rows["C"].share_estimate, SHARE)


if __name__ == "__main__":
    unittest.main()
