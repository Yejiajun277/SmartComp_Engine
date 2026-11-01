"""Pricing claims must remain within their selected original quote's scope."""
import json
import unittest
from unittest.mock import patch

from agents.pricing_agent import PricingAgent
from models.domain import Citation, CompetitorData, PricingTier


class PricingScopeIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def analyze(self, payload, competitors, target=None, dimensions="1. **Quote**: native terms"):
        self.prompts = []
        async def transport(system_prompt, user_message, **kwargs):
            self.prompts.append(user_message)
            return {"content": json.dumps(payload, ensure_ascii=False), "finish_reason": "stop",
                    "usage": {}, "timestamp": "", "model": "fixture", "prompt_tokens": 0,
                    "completion_tokens": 0, "total_tokens": 0, "duration_ms": 0}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            return await PricingAgent().run("Target", competitors, target, sub_dimensions=dimensions)

    async def test_missing_comparable_basis_removes_ranking_claims_from_every_price_surface(self):
        data = {"A": CompetitorData("A", pricing_tiers=[PricingTier(
            "Mini SKU", "$20/unit on 2025-01-01", ["No accessories"], ["A:price"])],
            citations=[Citation("A:price", snippet="Mini SKU $20/unit on 2025-01-01. No accessories.")]),
                "B": CompetitorData("B", pricing_tiers=[PricingTier(
            "Complete SKU", "$40/unit on 2026-03-01", ["Includes accessories"], ["B:price"])],
            citations=[Citation("B:price", snippet="Complete SKU $40/unit on 2026-03-01. Includes accessories.")])}
        payload = {"value_ranking": ["A", "B"], "comparable_basis": {},
                   "summary": "上述性价比排名为A、B。原报价分属不同SKU与日期。",
                   "pricing_strategy_analysis": "参考排序：A更便宜，B最贵。品牌提供不同配件组合。",
                   "pricing_comparison": [{"competitor": "A", "paid_tier": "$20; A is cheaper than B", "pricing_model": "one-time"}],
                   "dimension_comparison": [{"feature": "Quote", "values": {"A": "$20; best value", "B": "$40"}}]}
        result = await self.analyze(payload, data)
        self.assertEqual(result.value_ranking, [])
        visible = " ".join([result.summary, result.pricing_strategy_analysis,
            *(item.paid_tier for item in result.pricing_comparison),
            *(value for row in result.dimension_comparison for value in row.values.values())])
        for claim in ["上述性价比排名", "参考排序", "A更便宜", "B最贵", "A is cheaper than B", "best value"]:
            self.assertNotIn(claim, visible)
        self.assertIn("不可直接排名", result.summary)
        notes = json.dumps(result.source_scope_notes, ensure_ascii=False)
        for quote in ["$20/unit on 2025-01-01", "$40/unit on 2026-03-01", "No accessories", "Includes accessories"]:
            self.assertIn(quote, notes)

    async def test_dollar_quote_without_region_cannot_become_a_us_quote(self):
        source = Citation("A:price", "Price increase", snippet="Individual plan now $10.99 per month, previously $9.99.")
        unrelated = Citation("A:other", "United States hardware launch", snippet="United States, 2026-01-01, headphones.")
        data = CompetitorData("A", pricing_tiers=[PricingTier(
            "Individual (US)", "$10.99/month", ["Terms not stated"], [source.id])], citations=[source, unrelated])
        payload = {"summary": "A美国个人价$10.99/月。", "pricing_strategy_analysis": "A的美区报价为$10.99/月。",
                   "pricing_comparison": [{"competitor": "A", "paid_tier": "US $10.99/month", "citations": [source.id]}],
                   "dimension_comparison": [{"feature": "Quote", "values": {"A": "美国$10.99/月"}, "citations": [source.id]}]}
        result = await self.analyze(payload, {"A": data})
        visible = " ".join([result.summary, result.pricing_strategy_analysis,
            result.pricing_comparison[0].paid_tier, result.dimension_comparison[0].values["A"]])
        self.assertNotIn("美国", visible)
        self.assertNotIn("美区", visible)
        self.assertNotIn("US ", visible)
        self.assertIn("$10.99", visible)
        self.assertIn("未注明地区", visible)
        self.assertIn("A", result.source_scope_notes)
        self.assertIn("未注明地区", " ".join(result.source_scope_notes["A"]))
        self.assertEqual(data.pricing_tiers[0].tier_name, "Individual (US)")
        self.assertEqual(data.citations[0].snippet, source.snippet)

    async def test_explicit_us_quote_is_preserved(self):
        source = Citation("A:price", "US quote", snippet="United States Individual plan $10.99/month, 2026-01-01.")
        data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", "$10.99/month", citations=[source.id])], citations=[source])
        payload = {"dimension_comparison": [{"feature": "Quote", "values": {"A": "美国$10.99/月，2026-01-01"}, "citations": [source.id]}]}
        result = await self.analyze(payload, {"A": data})
        self.assertEqual(result.dimension_comparison[0].values["A"], "美国$10.99/月，2026-01-01")

    async def test_same_source_other_price_and_shared_year_cannot_supply_us_scope(self):
        source = Citation("A:price", snippet="Individual $10.99/month, 2026.\nUnited States Family $20.99/month, 2026.")
        data = CompetitorData("A", pricing_tiers=[PricingTier(
            "Individual", "$10.99/month, 2026", citations=[source.id])], citations=[source])
        payload = {"dimension_comparison": [{"feature": "Quote", "values": {"A": "美国$10.99/月，2026"}, "citations": [source.id]}]}
        result = await self.analyze(payload, {"A": data})
        self.assertNotIn("美国", result.dimension_comparison[0].values["A"])
        self.assertIn("$10.99", result.dimension_comparison[0].values["A"])

    async def test_source_notes_bind_every_original_quote_to_its_own_reference_in_html(self):
        from agents.strategy_agent import StrategyAgent
        from models.domain import StrategyReport
        data = CompetitorData("A", pricing_tiers=[
            PricingTier("Basic SKU", "$10/month, 2024-01", ["Only one device"], ["A:basic"]),
            PricingTier("Full SKU", "$30/month, 2026-02", ["Three devices"], ["A:full"])],
            citations=[Citation("A:basic", snippet="Basic SKU $10/month in January 2024, one device."),
                       Citation("A:full", snippet="Full SKU $30/month in February 2026, three devices.")])
        result = await self.analyze({}, {"A": data})
        notes = " ".join(result.source_scope_notes["A"])
        for term in ["Basic SKU", "$10/month, 2024-01", "Only one device", "[A:basic]",
                     "Full SKU", "$30/month, 2026-02", "Three devices", "[A:full]"]:
            self.assertIn(term, notes)
        html = StrategyAgent().format_html_report(StrategyReport("Target", competitor_count=1), pricing_analysis=result)
        for fact in ["$10/month, 2024-01", "Only one device", "$30/month, 2026-02", "Three devices"]:
            self.assertIn(fact, html)

    async def test_chunk_merge_cannot_restore_parent_or_child_comparative_prose(self):
        replies = iter([("参考排序为A优于B。", "A性价比领先。", True),
                        ("A has best value.", "A更便宜。", False),
                        ("B价格最高。", "B is more expensive.", False)])
        async def transport(system_prompt, user_message, **kwargs):
            summary, strategy, truncated = next(replies)
            payload = {"summary": summary, "pricing_strategy_analysis": strategy,
                       "dimension_comparison": [{"feature": "Quote", "values": {"A": "$10", "B": "$30"}}]}
            return {"content": json.dumps(payload, ensure_ascii=False), "finish_reason": "length" if truncated else "stop",
                    "usage": {}, "timestamp": "", "model": "fixture", "prompt_tokens": 0,
                    "completion_tokens": 0, "total_tokens": 0, "duration_ms": 0}
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await PricingAgent().run("Target", {"A": CompetitorData("A"), "B": CompetitorData("B")}, sub_dimensions="1. **Quote**: native terms")
        self.assertEqual(result.value_ranking, [])
        for claim in ["参考排序", "A优于B", "性价比领先", "best value", "A更便宜", "B价格最高", "more expensive"]:
            self.assertNotIn(claim, result.summary + result.pricing_strategy_analysis)
        self.assertIn("不可直接排名", result.summary)

    async def test_non_us_currency_and_us_inside_names_do_not_assert_a_country(self):
        for quote in ["Australia A$10.99/month", "Augustus author quote US$10.99/month", "Focus_US author quote US$10.99/month", "Plus EUR 10.99/month"]:
            with self.subTest(quote=quote):
                data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", quote, citations=["A:price"])],
                                      citations=[Citation("A:price", snippet=quote)])
                payload = {"dimension_comparison": [{"feature": "Quote", "values": {"A": quote}, "citations": ["A:price"]}]}
                result = await self.analyze(payload, {"A": data})
                self.assertEqual(result.dimension_comparison[0].values["A"], quote)

    async def test_region_in_source_title_or_query_cannot_supply_missing_quote_region(self):
        source = Citation("A:price", "US music plans", snippet="Individual plan $10.99/month.", query="US Individual 2026")
        data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", "$10.99/month", citations=[source.id])], citations=[source])
        result = await self.analyze({"dimension_comparison": [{"feature": "Quote", "values": {"A": "美国$10.99/月"}, "citations": [source.id]}]}, {"A": data})
        self.assertNotIn("美国", result.dimension_comparison[0].values["A"])
        self.assertIn("未注明地区", result.dimension_comparison[0].values["A"])

    async def test_us_service_scope_without_a_dollar_quote_is_not_rewritten_as_currency(self):
        data = CompetitorData("A", pricing_tiers=[PricingTier("Free service in US", "Free", ["US residents only"], ["A:free"])],
                              citations=[Citation("A:free", snippet="Free service in US, US residents only.")])
        result = await self.analyze({"dimension_comparison": [{"feature": "Quote", "values": {"A": "美国居民免费使用"}, "citations": ["A:free"]}]}, {"A": data})
        self.assertEqual(result.dimension_comparison[0].values["A"], "美国居民免费使用")

    async def test_same_amount_for_a_different_sku_cannot_supply_us_scope(self):
        source = Citation("A:price", snippet="Individual $10.99/month.\nUnited States Student $10.99/month.")
        data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", "$10.99/month", citations=[source.id])], citations=[source])
        result = await self.analyze({"dimension_comparison": [{"feature": "Quote", "values": {"A": "美国$10.99/月"}, "citations": [source.id]}]}, {"A": data})
        self.assertNotIn("美国", result.dimension_comparison[0].values["A"])

    async def test_basis_cannot_take_the_date_from_another_sku_in_the_same_source(self):
        from tests.test_pricing_dimensions import PricingDimensionTests
        data, basis = PricingDimensionTests.comparable_quotes()
        data["A"].citations[0].snippet = "上海2025-01-01标准套装：100元/台。上海2026-11-01高级套装：500元/台。"
        payload = {"value_ranking": ["B", "A"], "comparable_basis": basis,
                   "summary": "A has better value than B."}
        result = await self.analyze(payload, {name: data[name] for name in ["A", "B"]}, target=data["Target"])
        self.assertEqual(result.comparable_basis, {})
        self.assertEqual(result.value_ranking, [])

    async def test_price_linked_source_retains_late_scope_in_model_input(self):
        source = Citation("A:price", snippet="Background. " * 100 + "Individual $10.99/month; eligible residents of CityOmega only, expires 2025-12-31.")
        data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", "$10.99/month", citations=[source.id])], citations=[source])
        await self.analyze({}, {"A": data})
        self.assertIn("eligible residents of CityOmega only, expires 2025-12-31", self.prompts[0])

    async def test_us_country_aliases_do_not_escape_missing_region_guard(self):
        data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", "$10.99/month", citations=["A:price"])],
                              citations=[Citation("A:price", snippet="Individual $10.99/month.")])
        for region in ["USA", "U.S.A.", "美國", "美區"]:
            with self.subTest(region=region):
                result = await self.analyze({"dimension_comparison": [{"feature": "Quote", "values": {"A": region + " $10.99/month"}, "citations": ["A:price"]}]}, {"A": data})
                self.assertNotIn(region, result.dimension_comparison[0].values["A"])
                self.assertIn("未注明地区", result.dimension_comparison[0].values["A"])

    async def test_longer_offering_with_the_same_name_prefix_cannot_supply_region(self):
        for offering, different in [("Individual", "Individual Plus"), ("Edition2", "Edition20"),
                                     ("标准套装", "标准套装增强版")]:
            with self.subTest(offering=offering):
                source = Citation("A:price", snippet=f"United States {different} $10.99/month, 2026-01-01.")
                data = CompetitorData("A", pricing_tiers=[PricingTier(offering, "$10.99/month", citations=[source.id])], citations=[source])
                result = await self.analyze({"dimension_comparison": [{"feature": "Quote", "values": {"A": "US $10.99/month"}, "citations": [source.id]}]}, {"A": data})
                self.assertNotIn("US ", result.dimension_comparison[0].values["A"])
                self.assertIn("未注明地区", result.dimension_comparison[0].values["A"])
                self.assertIn("$10.99", result.dimension_comparison[0].values["A"])

    async def test_explicit_code_currency_quotes_keep_valid_same_scope_basis(self):
        from tests.test_pricing_dimensions import PricingDimensionTests
        for currency in ["CNY", "EUR", "GBP"]:
            for position in ["prefix", "suffix"]:
                with self.subTest(currency=currency, position=position):
                    data, basis = PricingDimensionTests.comparable_quotes()
                    for item in data.values():
                        tier = item.pricing_tiers[0]
                        amount = tier.price.split("元")[0]
                        code_price = (currency + amount if position == "prefix" else amount + currency) + "/台"
                        item.citations[0].snippet = item.citations[0].snippet.replace(tier.price, code_price)
                        tier.price = code_price
                    for quote in basis["quotes"]:
                        quote["price_text"] = data[quote["entity"]].pricing_tiers[0].price
                    basis.update(currency=currency, unit=currency + "/台")
                    # Prefix-code notation puts the amount between currency and
                    # '/台'; retain the common unit as an explicit source term.
                    if position == "prefix":
                        for item in data.values():
                            item.citations[0].snippet += "（计价单位" + currency + "/台）"
                    payload = {"value_ranking": ["B", "A"], "comparable_basis": basis,
                               "summary": "同地区、日期、套装及单位的明确报价。"}
                    result = await self.analyze(payload, {name: data[name] for name in ["A", "B"]}, target=data["Target"])
                    self.assertEqual(result.comparable_basis, basis)
                    self.assertEqual(result.value_ranking, ["B", "A"])

    async def test_unpriced_trailing_offering_cannot_borrow_another_offerings_price(self):
        source = Citation("A:price", snippet="United States Individual Plus $10.99/month, compared to Individual")
        data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", "$10.99/month", citations=[source.id])], citations=[source])
        result = await self.analyze({"dimension_comparison": [{"feature": "Quote", "values": {"A": "US $10.99/month"}, "citations": [source.id]}]}, {"A": data})
        self.assertNotIn("US ", result.dimension_comparison[0].values["A"])
        self.assertIn("未注明地区", result.dimension_comparison[0].values["A"])
        self.assertIn("$10.99/month", " ".join(result.source_scope_notes["A"]))
        self.assertEqual(data.citations[0].snippet, source.snippet)

    async def test_multiple_quotes_in_one_sentence_cannot_share_a_country_or_date(self):
        for other_price in ["$20.99", "$10.99"]:
            with self.subTest(other_price=other_price):
                source = Citation("A:price", snippet="Individual $10.99/month in Canada, 2025-01-01, Family " + other_price + "/month in United States, 2026-01-01")
                data = CompetitorData("A", pricing_tiers=[PricingTier("Individual", "$10.99/month", citations=[source.id])], citations=[source])
                result = await self.analyze({"dimension_comparison": [{"feature": "Quote", "values": {"A": "US $10.99/month"}, "citations": [source.id]}]}, {"A": data})
                self.assertNotIn("US ", result.dimension_comparison[0].values["A"])
                self.assertIn("未注明地区", result.dimension_comparison[0].values["A"])
                self.assertEqual(PricingAgent._quote_sentences(data, data.pricing_tiers[0], [source.id]), [])
                self.assertIn("$10.99/month", " ".join(result.source_scope_notes["A"]))


if __name__ == "__main__":
    unittest.main()
