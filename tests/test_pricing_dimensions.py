"""Pricing comparisons must follow the current category's actual dimensions."""
from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from agents.pricing_agent import PricingAgent
from agents.strategy_agent import StrategyAgent
from models.domain import Citation, CompetitorData, FeatureItem, PricingAnalysis, PricingItem, PricingTier, ProductAnalysis, MarketAnalysis, StrategyReport


VACUUM = "1. **购机价格**：当前渠道报价\n2. **耗材成本**：已披露耗材及频率"
HOTEL = "1. **每晚房价**：房型日期限定\n2. **退改条件**：可取消时间与费用"


def result(rows):
    return {"dimension_comparison": rows, "pricing_comparison": [],
            "pricing_strategy_analysis": "仅按已采集报价比较", "summary": "限定本次采集范围"}


class PricingDimensionTests(unittest.IsolatedAsyncioTestCase):
    async def run_transport(self, replies, dimensions=VACUUM, competitors=None, agent=None, target=None):
        queue = iter(replies)
        self.requests = []

        async def transport(system_prompt, user_message, **kwargs):
            content, truncated = next(queue)
            self.requests.append((system_prompt, user_message, kwargs["max_tokens"]))
            return {"content": content, "finish_reason": "length" if truncated else "stop",
                    "usage": {}, "timestamp": "", "model": "fixture", "prompt_tokens": 0,
                    "completion_tokens": 0, "total_tokens": 0, "duration_ms": 0}

        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            return await (agent or PricingAgent()).run(
                "Target", competitors or {"A": CompetitorData("A"), "B": CompetitorData("B")},
                target_product_data=target, sub_dimensions=dimensions)

    async def test_two_categories_keep_their_own_rows_and_complete_all_entity_columns(self):
        for dimensions, names in ((VACUUM, ["购机价格", "耗材成本"]), (HOTEL, ["每晚房价", "退改条件"])):
            with self.subTest(names=names):
                payload = result([{"feature": names[0], "values": {"Target": "¥2999，限指定规格", "A": "¥2499"},
                                   "citations": ["A:q0:r0"]}])
                analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)], dimensions)
                rows = getattr(analysis, "dimension_comparison", [])
                self.assertEqual([row.feature for row in rows], names)
                self.assertEqual(rows[0].values, {"Target": "¥2999，限指定规格", "A": "¥2499", "B": "资料不足"})
                self.assertEqual(rows[1].values, dict.fromkeys(("Target", "A", "B"), "资料不足"))
                self.assertIn("A:q0:r0", analysis.citations)

    async def test_failed_model_keeps_current_price_dimensions_unknown(self):
        analysis = await self.run_transport([("", False)])
        rows = getattr(analysis, "dimension_comparison", [])
        self.assertEqual([row.feature for row in rows], ["购机价格", "耗材成本"])
        self.assertTrue(all(value == "资料不足" for row in rows for value in row.values.values()))
        self.assertIn("降级", analysis.summary)

    async def test_invalid_truncated_chunks_split_before_discarding_failure(self):
        def leaf(name):
            return (json.dumps(result([{"feature": "购机价格", "values": {name: f"{name}渠道报价"},
                                        "citations": [f"{name}:q0:r0"]}]), ensure_ascii=False), False)
        analysis = await self.run_transport(
            [("{", True), ("{", True), leaf("A"), leaf("B"), ("{", True), leaf("C"), leaf("D")],
            competitors={name: CompetitorData(name) for name in "ABCD"})
        rows = getattr(analysis, "dimension_comparison", [])
        self.assertEqual([row.feature for row in rows], ["购机价格", "耗材成本"])
        self.assertEqual(rows[0].values, {"Target": "资料不足", **{name: f"{name}渠道报价" for name in "ABCD"}})
        self.assertEqual(len(self.requests), 7)
        self.assertEqual(self.requests[0][2], 8192)
        self.assertTrue(all(request[2] == 4096 for request in self.requests[1:]))

    async def test_partial_recovery_preserves_known_cells_and_unknown_competitors(self):
        known = result([{"feature": "购机价格", "values": {"Target": "¥3999", "A": "¥2999"}}])
        analysis = await self.run_transport([("{", True), (json.dumps(known), False), ("", False)])
        rows = getattr(analysis, "dimension_comparison", [])
        self.assertEqual([row.feature for row in rows], ["购机价格", "耗材成本"])
        self.assertEqual(rows[0].values, {"Target": "¥3999", "A": "¥2999", "B": "资料不足"})
        self.assertEqual([row.feature for row in rows], ["购机价格", "耗材成本"])

    async def test_dimension_names_are_exact_and_unrelated_model_rows_are_dropped(self):
        payload = result([
            {"feature": "购机价格（指定规格）", "values": {"A": "¥2999", "Stranger": "¥1"}},
            {"feature": "免费版", "values": {"A": "无"}},
            {"feature": "非购机价格", "values": {"A": "¥2"}},
        ])
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)])
        rows = getattr(analysis, "dimension_comparison", [])
        self.assertEqual([row.feature for row in rows], ["购机价格", "耗材成本"])
        self.assertEqual(rows[0].values["A"], "¥2999")
        self.assertNotIn("Stranger", rows[0].values)

    async def test_reused_agent_clears_old_category_dimensions_when_next_input_is_empty(self):
        agent = PricingAgent()
        await self.run_transport([("{}", False)], agent=agent)
        analysis = await self.run_transport([("{}", False)], dimensions="", agent=agent)
        self.assertEqual(getattr(analysis, "dimension_comparison", None), [])
        self.assertNotIn("购机价格", self.requests[0][0])
        self.assertNotIn("{sub_dimensions}", self.requests[0][0])

    async def test_total_truncation_is_bounded_and_has_complete_unknown_matrix(self):
        analysis = await self.run_transport(
            [("{", True)] * 7, competitors={name: CompetitorData(name) for name in "ABCD"})
        self.assertEqual(len(self.requests), 7)
        rows = getattr(analysis, "dimension_comparison", [])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(value == "资料不足" for row in rows for value in row.values.values()))

    async def test_rule_fallback_does_not_mislabel_first_paid_tier_as_free(self):
        with patch("config.ENABLE_LLM", False):
            analysis = await PricingAgent().run("Target", {"A": CompetitorData("A", pricing_tiers=[
                PricingTier("标准房", "¥399/晚", citations=["A:q0:r0"])])}, sub_dimensions=HOTEL)
        self.assertEqual(analysis.pricing_comparison[0].free_tier, "")
        self.assertIn("¥399/晚", analysis.pricing_comparison[0].paid_tier)
        self.assertEqual([row.feature for row in analysis.dimension_comparison], ["每晚房价", "退改条件"])

    async def test_prompt_requires_native_pricing_dimensions_instead_of_software_versions(self):
        await self.run_transport([("{}", False)])
        system, prompt, budget = self.requests[0]
        self.assertIn("dimension_comparison", prompt)
        self.assertNotIn("免费版内容、付费版价格", prompt)
        self.assertIn('"value_ranking": []', prompt)
        self.assertIn("购机价格", system)
        self.assertEqual(budget, 8192)

    async def test_native_terms_and_feature_source_details_reach_the_price_request(self):
        data = CompetitorData("A", pricing_tiers=[PricingTier(
            "2026上海标准房", "¥399/晚", ["入住前一日18点前免费取消", "含双早"], ["A:q2:r7"])],
            product_features=[FeatureItem("延迟退房", "仅限会员，可延至14点", ["A:q3:r8"])])
        await self.run_transport([("{}", False)], dimensions=HOTEL, competitors={"A": data})
        prompt = self.requests[0][1]
        for fact in ("入住前一日18点前免费取消", "含双早", "A:q2:r7", "仅限会员，可延至14点", "A:q3:r8"):
            self.assertIn(fact, prompt)

    async def test_partial_recovery_keeps_parent_quote_and_its_scope_when_only_model_changes(self):
        parent = result([])
        parent["summary"] = "仅适用于2026上海标准房含早报价。"
        parent["pricing_comparison"] = [{"competitor": "A", "paid_tier": "¥399/晚", "pricing_model": "按晚", "citations": ["A:q0:r0"]}]
        child = result([])
        child["pricing_comparison"] = [{"competitor": "A", "paid_tier": "资料不足", "pricing_model": "按房晚，日期限定", "citations": ["A:q1:r1"]}]
        analysis = await self.run_transport([(json.dumps(parent, ensure_ascii=False), True),
                                             (json.dumps(child, ensure_ascii=False), False), ("", False)], dimensions=HOTEL)
        self.assertEqual(analysis.pricing_comparison[0].paid_tier, "¥399/晚")
        self.assertIn(parent["summary"], analysis.summary)
        self.assertIn("A:q0:r0", analysis.pricing_comparison[0].citations)

    async def test_nested_recovery_keeps_original_subset_price_qualifications(self):
        a = result([])
        a["summary"] = "A仅2026上海标准房，含双早。"
        b = result([])
        b["summary"] = "B仅2025北京套房，不含早。"
        cd = result([])
        cd["summary"] = "C和D仅广州周末房型，均不可取消。"
        analysis = await self.run_transport([("{", True), ("{", True),
            (json.dumps(a, ensure_ascii=False), False), (json.dumps(b, ensure_ascii=False), False),
            (json.dumps(cd, ensure_ascii=False), False)], dimensions=HOTEL,
            competitors={name: CompetitorData(name) for name in "ABCD"})
        self.assertIn("4家竞品（A、B、C、D）", analysis.summary)
        self.assertIn("适用竞品（A）：" + a["summary"], analysis.summary)
        self.assertIn("适用竞品（B）：" + b["summary"], analysis.summary)
        self.assertIn("适用竞品（C、D）：" + cd["summary"], analysis.summary)

    async def test_corrected_competitor_does_not_keep_parent_batch_conclusions(self):
        parent = result([{"feature": "Installation fee", "values": {"A": "Free", "B": "Free"}}])
        parent["pricing_comparison"] = [{"competitor": "A", "paid_tier": "USD10"}, {"competitor": "B", "paid_tier": "USD20"}]
        parent["summary"] = "A and B both have free installation; 2025 US base SKU only."
        parent["pricing_strategy_analysis"] = "A is cheaper because installation is free."
        child = result([{"feature": "Installation fee", "values": {"A": "USD300 installation fee"}}])
        child["pricing_comparison"] = [{"competitor": "A", "paid_tier": "USD15"}]
        child["summary"] = "Correction: A charges USD300 installation; previous claim withdrawn."
        child["pricing_strategy_analysis"] = "A total cost must include USD300 installation."
        analysis = await self.run_transport([(json.dumps(parent), True), (json.dumps(child), False), ("", False)],
                                            dimensions="1. **Installation fee**: actual cost")
        self.assertEqual(analysis.dimension_comparison[0].values["A"], "USD300 installation fee")
        self.assertEqual(analysis.dimension_comparison[0].values["B"], "Free")
        self.assertNotIn(parent["pricing_strategy_analysis"], analysis.pricing_strategy_analysis)
        self.assertNotIn("适用竞品（A、B）：" + parent["summary"], analysis.summary)
        self.assertIn("仅保留B", analysis.summary)
        self.assertIn("并非当前结论", analysis.summary)
        self.assertIn("2025 US base SKU only", analysis.summary)
        self.assertIn(child["summary"], analysis.summary)

    async def test_recovered_charge_can_withdraw_parent_free_offer(self):
        parent = result([])
        parent["pricing_comparison"] = [{"competitor": "A", "free_tier": "Free installation", "paid_tier": "USD10"}]
        child = result([])
        child["pricing_comparison"] = [{"competitor": "A", "free_tier": "", "paid_tier": "USD15; installation USD300"}]
        analysis = await self.run_transport([(json.dumps(parent), True), (json.dumps(child), False), ("", False)])
        self.assertEqual(analysis.pricing_comparison[0].free_tier, "")
        self.assertEqual(analysis.pricing_comparison[0].paid_tier, "USD15; installation USD300")

    async def test_valid_json_with_wrong_field_shapes_keeps_unknowns_without_crashing(self):
        for field, value in (("dimension_comparison", None), ("pricing_comparison", None),
                             ("value_ranking", None), ("summary", {"scope": "Only standard rooms"}),
                             ("pricing_strategy_analysis", ["Only standard rooms"])):
            for truncated in (False, True):
                with self.subTest(field=field, truncated=truncated):
                    payload = result([])
                    payload[field] = value
                    try:
                        analysis = await self.run_transport([(json.dumps(payload), truncated)],
                            competitors={"A": CompetitorData("A")})
                    except (TypeError, AttributeError) as exc:
                        self.fail(f"Malformed field {field} crashed the comparison: {exc}")
                    self.assertIsInstance(analysis.summary, str)
                    self.assertIsInstance(analysis.pricing_strategy_analysis, str)
                    self.assertEqual([row.feature for row in analysis.dimension_comparison], ["购机价格", "耗材成本"])
                    self.assertEqual(analysis.value_ranking, [])
                    self.assertIn("格式", analysis.summary)

    @staticmethod
    def comparable_quotes():
        data = {}
        quotes = []
        for entity, amount in (("Target", 120), ("A", 100), ("B", 90)):
            cid = entity + ":q0:r0"
            price = f"{amount}元/台"
            data[entity] = CompetitorData(entity,
                pricing_tiers=[PricingTier("标准套装", price, ["上海", "2026-11-01"], [cid])],
                citations=[Citation(cid, "同日上海标准套装报价", "https://example.test/" + entity,
                                    f"上海2026-11-01标准套装：{price}")])
            quotes.append({"entity": entity, "tier_name": "标准套装", "price_text": price, "citations": [cid]})
        basis = {"unit": "元/台", "currency": "元", "region": "上海", "period": "2026-11-01",
                 "offering_scope": "标准套装", "quotes": quotes}
        return data, basis

    async def test_ranking_defaults_to_empty_without_source_backed_comparable_basis(self):
        payload = result([])
        payload["value_ranking"] = ["B", "A"]
        payload["summary"] = "城市、日期、配置不同，不可直接排名。"
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)])
        self.assertEqual(analysis.value_ranking, [])
        self.assertIn("不可直接", analysis.summary)

    async def test_exact_native_tier_and_its_evidence_allow_a_same_scope_ranking(self):
        data, basis = self.comparable_quotes()
        payload = result([])
        payload.update(value_ranking=["B", "A"], comparable_basis=basis)
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)],
            competitors={name: data[name] for name in ("A", "B")}, target=data["Target"])
        self.assertEqual(analysis.value_ranking, ["B", "A"])
        self.assertEqual(getattr(analysis, "comparable_basis", None), basis)

    async def test_comparability_cannot_borrow_scope_from_a_different_price_tier(self):
        data, basis = self.comparable_quotes()
        data["A"].pricing_tiers[0].features = []
        data["A"].citations[0].snippet = "标准套装100元/台，日期与城市未披露"
        data["A"].citations[0].title = "标准套装报价"
        data["A"].pricing_tiers.append(PricingTier("另一套餐", "500元/台", ["上海", "2026-11-01"]))
        payload = result([])
        payload.update(value_ranking=["B", "A"], comparable_basis=basis)
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)],
            competitors={name: data[name] for name in ("A", "B")}, target=data["Target"])
        self.assertEqual(analysis.value_ranking, [])
        self.assertEqual(getattr(analysis, "comparable_basis", None), {})

    async def test_explicit_noncomparability_vetoes_even_a_complete_basis(self):
        data, basis = self.comparable_quotes()
        payload = result([])
        payload.update(value_ranking=["B", "A"], comparable_basis=basis,
                       summary="尽管给出报价，本轮无法确认权益等价，不宜直接排名。")
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)],
            competitors={name: data[name] for name in ("A", "B")}, target=data["Target"])
        self.assertEqual(analysis.value_ranking, [])

    async def test_title_only_and_truncated_native_terms_remain_visible_as_source_limits(self):
        native = ["订单低至3折（据新闻文章标题，适用条件不详）", "金卡及（原文截断）会员含早"]
        data = CompetitorData("A", pricing_tiers=[PricingTier("会员报价", "资料不足", native)])
        payload = result([{"feature": "退改条件", "values": {"A": "资料不足"}}])
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)], dimensions=HOTEL,
                                           competitors={"A": data})
        notes = getattr(analysis, "source_scope_notes", {})
        self.assertIn("A", notes)
        for original in native:
            self.assertIn(original, " ".join(notes["A"]))
        html = StrategyAgent().format_html_report(StrategyReport("Target", competitor_count=1), pricing_analysis=analysis)
        for original in native:
            self.assertIn(original, html)
        self.assertIn("不能作为普适", self.requests[0][0] + self.requests[0][1])

    async def test_unknown_original_quote_is_not_a_valid_ranking_basis(self):
        data, basis = self.comparable_quotes()
        data["A"].pricing_tiers[0].price = "资料不足"
        data["A"].pricing_tiers[0].features.append("元/台")
        data["A"].citations[0].snippet = "上海2026-11-01标准套装，报价资料不足"
        basis["quotes"][1]["price_text"] = "资料不足"
        payload = result([])
        payload.update(value_ranking=["B", "A"], comparable_basis=basis)
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)],
            competitors={name: data[name] for name in ("A", "B")}, target=data["Target"])
        self.assertEqual(analysis.value_ranking, [])

    async def test_indirect_noncomparability_statement_also_vetoes_ranking(self):
        data, basis = self.comparable_quotes()
        payload = result([])
        payload.update(value_ranking=["B", "A"], comparable_basis=basis,
                       summary="报价不是同一时间，不能据此进行性价比排名。")
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)],
            competitors={name: data[name] for name in ("A", "B")}, target=data["Target"])
        self.assertEqual(analysis.value_ranking, [])

    async def test_original_uncertainty_is_visible_even_without_generated_price_dimensions(self):
        native = "优惠低至3折（仅文章标题，日期不详）"
        data = CompetitorData("A", pricing_tiers=[PricingTier("会员线索", "资料不足", [native])])
        analysis = await self.run_transport([("{}", False)], dimensions="", competitors={"A": data})
        html = StrategyAgent().format_html_report(StrategyReport("Target", competitor_count=1), pricing_analysis=analysis)
        self.assertIn(native, html)

    async def test_legacy_price_data_stays_readable_without_fixed_software_headings(self):
        analysis = PricingAnalysis(pricing_comparison=[PricingItem("A", paid_tier="¥2999，指定规格")])
        self.assertEqual(analysis.dimension_comparison, [])
        html = StrategyAgent().format_html_report(StrategyReport("Target", competitor_count=1), pricing_analysis=analysis)
        self.assertIn("¥2999，指定规格", html)
        self.assertNotIn(">免费版<", html)
        self.assertNotIn(">付费版<", html)

    async def test_paid_hotel_or_hardware_offer_has_no_empty_free_offer_column(self):
        analysis = PricingAnalysis(pricing_comparison=[PricingItem("A", paid_tier="¥399/晚")])
        report = StrategyReport("Target", competitor_count=1, target_product_data=CompetitorData(
            "Target", pricing_tiers=[PricingTier("基础房", "¥499/晚")]))
        html = StrategyAgent().format_html_report(report, pricing_analysis=analysis)
        self.assertNotIn("免费方案（如有）", html)
        self.assertIn("¥499/晚", html)

    async def test_dynamic_rows_reach_json_strategy_input_and_html_as_text(self):
        payload = result([{"feature": "每晚房价", "values": {"Target": "¥399/晚，2026年上海标准房", "A": "<script>bad</script>"}}])
        analysis = await self.run_transport([(json.dumps(payload, ensure_ascii=False), False)], dimensions=HOTEL)
        self.assertIn("dimension_comparison", asdict(analysis))
        report = StrategyReport("Target", competitor_count=2)
        html = StrategyAgent().format_html_report(report, pricing_analysis=analysis)
        strategy_input = StrategyAgent()._build_analysis_text("Target", ProductAnalysis(), analysis, MarketAnalysis())
        for value in ("每晚房价", "退改条件", "¥399/晚，2026年上海标准房"):
            self.assertIn(value, html)
            self.assertIn(value, strategy_input)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)
        self.assertNotIn("<script>bad</script>", html)
        self.assertNotIn(">免费版<", html)
        self.assertNotIn(">付费版<", html)


if __name__ == "__main__":
    unittest.main()
