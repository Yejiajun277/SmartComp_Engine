"""Collection and repair preserve explicit, visible source bindings."""
import json
import unittest
from unittest.mock import patch

from agents.collection_agent import CollectionAgent
from models.domain import Citation, CompetitorData, FeatureItem, PricingTier


class SourceSearch:
    def __init__(self):
        self.queries = []

    def batch_search(self, queries):
        self.queries.extend(queries)
        return [{"query": query, "result": {"references": [{
            "title": "Official source", "url": "https://example.test/source",
            "content": "SOURCE_EVIDENCE_MARKER: 399 yuan/night, selected city and date. Feature detail.",
        }]}, "references": [{
            "title": "Official source", "url": "https://example.test/source",
            "content": "SOURCE_EVIDENCE_MARKER: 399 yuan/night, selected city and date. Feature detail.",
        }]} for query in queries]

    async def async_batch_search(self, queries):
        return self.batch_search(queries)


def payload(feature_id="Rival:q0:r0", price_id="Rival:q0:r0"):
    return {"product_features": [{"name": "Feature", "description": "Source feature detail.",
                                  "citations": [feature_id, "Unknown:q0:r0"]}],
            "pricing_tiers": [{"tier_name": "Offer", "price": "399 yuan/night, selected city/date",
                               "features": ["Date restriction"], "citations": [price_id, "Unknown:q0:r0"]}],
            "market_share": "Source gives no market-share statistic.",
            "strengths": "Source describes a specific feature advantage.",
            "weaknesses": "Source describes one limited service condition.",
            "channels": "Source describes a direct purchase channel.",
            "user_reviews": "Source describes a limited customer review."}


class CollectionCitationBindingTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, response):
        agent = CollectionAgent()
        agent.search_client = SourceSearch()
        self.requests = []

        def transport(system, prompt, **kwargs):
            self.requests.append(prompt)
            return {"content": json.dumps(response, ensure_ascii=False), "finish_reason": "stop"}

        async def async_transport(*args, **kwargs):
            return transport(*args, **kwargs)

        self.transport, self.async_transport = transport, async_transport
        return agent

    async def main_collection(self, asynchronous, response=None, feedback=""):
        agent = self.agent(response or payload())
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", self.transport), \
             patch("agents.base_agent.async_llm_call", self.async_transport):
            args = ("Target", "Current product context", "Rival", ["Rival price and specification"])
            data = (await agent._async_collect_entity(*args, feedback=feedback) if asynchronous
                    else agent._collect_entity(*args, feedback=feedback))
        return agent, data

    async def test_sync_and_async_main_collection_keep_only_real_explicit_item_citations(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent, data = await self.main_collection(asynchronous)
                self.assertEqual(data.product_features[0].citations, ["Rival:q0:r0"])
                self.assertEqual(data.pricing_tiers[0].citations, ["Rival:q0:r0"])
                self.assertIn("Rival:q0:r0", self.requests[0])
                self.assertIn("SOURCE_EVIDENCE_MARKER", self.requests[0])
                self.assertIn("Rival:q0:r0", agent.get_search_texts()["Rival"])

    async def test_an_unmatched_item_does_not_borrow_all_entity_sources(self):
        _, data = await self.main_collection(True, payload("Missing:q9:r9", "Missing:q9:r9"))
        self.assertEqual(data.product_features[0].citations, [])
        self.assertEqual(data.pricing_tiers[0].citations, [])
        self.assertEqual(len(data.citations), 1)

    async def test_quality_suggestions_are_not_accepted_as_original_numerical_evidence(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                response = payload()
                response["strengths"] = "Unsupported feature handles 9000 units."
                _, data = await self.main_collection(asynchronous, response, feedback="Check a claim of 9000 units.")
                self.assertEqual(data.strengths, "")

    async def test_automatic_price_supplement_keeps_item_bindings_and_uses_neutral_queries(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = self.agent(payload(price_id="Rival:sup_price_0:r1"))
                existing = [Citation("Rival:q0:r0", "Old source", "https://example.test/old")]
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", self.transport), \
                     patch("agents.base_agent.async_llm_call", self.async_transport):
                    result, sources = (await agent._async_supplement_pricing("Rival", "Target", [], existing)
                                       if asynchronous else agent._supplement_pricing("Rival", "Target", [], existing))
                self.assertEqual(result[0].citations, ["Rival:sup_price_0:r1"])
                self.assertIn("Rival:sup_price_0:r1", self.requests[0])
                self.assertIn("Rival:sup_price_0:r1", {c.id for c in sources})
                self.assertFalse(any(term in q.lower() for q in agent.search_client.queries
                                     for term in ("免费版", "付费版", "premium")))

    async def test_sync_and_async_requested_array_repairs_stay_typed_and_bound_to_actual_sources(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                response = payload("Rival:sup_product_features_0:r1", "Rival:sup_pricing_tiers_0:r3")
                agent = self.agent(response)
                old = Citation("Rival:q0:r0", "Old source", "https://example.test/old")
                data = {"Rival": CompetitorData("Rival", citations=[old])}
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", self.transport), \
                     patch("agents.base_agent.async_llm_call", self.async_transport):
                    fields = {"Rival": ["product_features", "pricing_tiers"]}
                    updated = (await agent.async_supplement_missing_fields("Target", data, fields)
                               if asynchronous else agent.supplement_missing_fields("Target", data, fields))
                feature, tier = updated["Rival"].product_features[0], updated["Rival"].pricing_tiers[0]
                self.assertIsInstance(feature, FeatureItem)
                self.assertIsInstance(tier, PricingTier)
                self.assertEqual(feature.citations, ["Rival:sup_product_features_0:r1"])
                self.assertEqual(tier.citations, ["Rival:sup_pricing_tiers_0:r3"])
                self.assertIn("Rival:sup_product_features_0:r1", agent.get_search_texts().get("Rival", ""))
                self.assertFalse(any(term in q.lower() for q in agent.search_client.queries
                                     for term in ("免费版", "付费版", "premium")))

    async def test_supplement_evidence_is_added_to_the_next_quality_snapshot(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = self.agent(payload())
                agent._last_search_texts = {"Rival": "Original source evidence."}
                data = {"Rival": CompetitorData("Rival", strengths="")}
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", self.transport), \
                     patch("agents.base_agent.async_llm_call", self.async_transport):
                    fields = {"Rival": ["strengths"]}
                    if asynchronous:
                        await agent.async_supplement_missing_fields("Target", data, fields)
                    else:
                        agent.supplement_missing_fields("Target", data, fields)
                self.assertIn("SOURCE_EVIDENCE_MARKER", agent.get_search_texts()["Rival"])
                self.assertIn("Rival:sup_strengths_0:r0", agent.get_search_texts()["Rival"])

    async def test_collection_context_is_bounded_without_cutting_off_quality_feedback(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = self.agent(payload())
                original = agent.search_client.batch_search

                def many_sources(queries):
                    rows = original(queries)
                    for row in rows:
                        refs = [{"title": f"Source{i}", "url": f"https://example.test/{i}",
                                 "content": (("FINAL_QUERY_EVIDENCE_SENTINEL " if row["query"].endswith("6") else "")
                                             + "Long evidence " * 1000)} for i in range(80)]
                        row["references"] = refs
                        row["result"] = {"references": refs}
                    return rows

                agent.search_client.batch_search = many_sources
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", self.transport), \
                     patch("agents.base_agent.async_llm_call", self.async_transport):
                    args = ("Target", "Current product context", "Rival", [f"Source query {i}" for i in range(7)])
                    if asynchronous:
                        await agent._async_collect_entity(*args, feedback="FULL_QA_FEEDBACK_SENTINEL")
                    else:
                        agent._collect_entity(*args, feedback="FULL_QA_FEEDBACK_SENTINEL")
                self.assertIn("FULL_QA_FEEDBACK_SENTINEL", self.requests[0])
                self.assertIn("FINAL_QUERY_EVIDENCE_SENTINEL", self.requests[0])
                self.assertIn("excerpt_truncated", self.requests[0])
                raw = self.requests[0].split("### 搜索结果", 1)[1].split("### 提取要求", 1)[0]
                self.assertLessEqual(len(raw), 16500)

    async def test_an_existing_but_undisplayed_source_is_not_accepted_as_item_evidence(self):
        agent = self.agent(payload("Rival:q0:r79", "Rival:q0:r79"))
        original = agent.search_client.batch_search

        def many_sources(queries):
            rows = original(queries)
            for row in rows:
                refs = [{"title": f"Source{i}", "url": f"https://example.test/{i}",
                         "content": "Long evidence " * 1000} for i in range(80)]
                row["references"] = refs
                row["result"] = {"references": refs}
            return rows

        agent.search_client.batch_search = many_sources
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", self.async_transport):
            data = await agent._async_collect_entity("Target", "Product context", "Rival", ["Source query"])
        self.assertIn("Rival:q0:r79", {c.id for c in data.citations})
        self.assertNotIn("Rival:q0:r79", self.requests[0])
        self.assertEqual(data.product_features[0].citations, [])
        self.assertEqual(data.pricing_tiers[0].citations, [])

    async def test_new_market_number_is_validated_against_its_actual_supplement_source(self):
        class MarketSearch(SourceSearch):
            def batch_search(self, queries):
                rows = super().batch_search(queries)
                for row in rows:
                    if "市场" in row["query"] or "行业" in row["query"]:
                        for ref in [*row["references"], *row["result"]["references"]]:
                            ref["content"] = "The public source reports a 24% share in the stated market."
                return rows

        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                main = payload()
                main["market_share"] = ""
                queue = iter((main, {"market_share": "The public source reports a 24% share in the stated market."}))
                agent = CollectionAgent()
                agent.search_client = MarketSearch()

                def transport(*args, **kwargs):
                    return {"content": json.dumps(next(queue)), "finish_reason": "stop"}

                async def async_transport(*args, **kwargs):
                    return transport(*args, **kwargs)

                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", transport), \
                     patch("agents.base_agent.async_llm_call", async_transport):
                    args = ("Target", "Product context", "Rival", ["Initial collection"])
                    data = await agent._async_collect_entity(*args) if asynchronous else agent._collect_entity(*args)
                self.assertIn("24%", data.market_share)

    async def test_failed_repair_keeps_acquired_sources_without_inventing_item_links(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = self.agent({})
                old = Citation("Rival:q0:r0", "Old source", "https://example.test/old")
                data = {"Rival": CompetitorData("Rival", citations=[old])}
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", self.transport), \
                     patch("agents.base_agent.async_llm_call", self.async_transport):
                    if asynchronous:
                        await agent.async_supplement_missing_fields("Target", data, {"Rival": ["strengths"]})
                    else:
                        agent.supplement_missing_fields("Target", data, {"Rival": ["strengths"]})
                self.assertEqual(data["Rival"].strengths, "")
                self.assertEqual({c.id for c in data["Rival"].citations},
                                 {"Rival:q0:r0", "Rival:sup_strengths_0:r1", "Rival:sup_strengths_1:r2"})
                self.assertEqual(data["Rival"].product_features, [])

    async def test_invalid_array_repair_cannot_replace_typed_lists_with_text(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                agent = self.agent({"product_features": "Not a structured list.",
                                    "pricing_tiers": "No structured offers found."})
                data = {"Rival": CompetitorData("Rival")}
                with patch("config.ENABLE_LLM", True), patch("agents.base_agent.llm_call", self.transport), \
                     patch("agents.base_agent.async_llm_call", self.async_transport):
                    fields = {"Rival": ["product_features", "pricing_tiers"]}
                    if asynchronous:
                        await agent.async_supplement_missing_fields("Target", data, fields)
                    else:
                        agent.supplement_missing_fields("Target", data, fields)
                self.assertEqual(data["Rival"].product_features, [])
                self.assertEqual(data["Rival"].pricing_tiers, [])


if __name__ == "__main__":
    unittest.main()
