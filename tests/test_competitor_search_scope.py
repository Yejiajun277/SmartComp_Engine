"""Research scope survives discovery without becoming source evidence."""
import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from agents.discovery_agent import DiscoveryAgent
from models.domain import CompetitorList


class PublicSearch:
    def __init__(self, actual=None):
        self.calls = []
        self.actual = actual

    async def async_batch_search(self, queries):
        self.calls.append(list(queries))
        return [{"query": q, "result": {"references": [{"title": "Rival", "content": "CompA service", "url": "https://example.test/a"}]}}
                for q in (self.actual if self.actual is not None else queries)]


class DiscoverySearchScopeTests(unittest.IsolatedAsyncioTestCase):
    async def discover(self, scopes, description="Spotify 音乐订阅，美国个人用户市场", actual=None, agent=None, product_name="Spotify"):
        replies = iter([{"keywords": ["Spotify 美国个人用户 音乐服务对比"]},
                        {"product_name": product_name, "competitors": [{"name": "CompA"}], "search_scope": scopes}])
        self.calls = []
        async def transport(system, user, **kwargs):
            self.calls.append(user)
            return {"content": json.dumps(next(replies), ensure_ascii=False), "finish_reason": "stop"}
        agent = agent or DiscoveryAgent()
        agent.search_client = PublicSearch(actual)
        with patch("config.ENABLE_LLM", True), patch("agents.base_agent.async_llm_call", transport):
            result = await agent.run(description, 3)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(agent.search_client.calls), 1)
        return result

    async def test_scope_is_saved_from_existing_filter_call_and_only_shared_literal_phrases(self):
        result = await self.discover(["美国", "个人用户", "加拿大", "家庭"])
        self.assertEqual(getattr(result, "search_scope", []), ["美国", "个人用户"])
        self.assertEqual(result.search_keywords_used, ["Spotify 美国个人用户 音乐服务对比"])

    async def test_generated_but_not_actually_used_scope_is_rejected(self):
        result = await self.discover(["美国", "个人用户"], actual=["Spotify 加拿大 家庭 音乐服务"])
        self.assertEqual(getattr(result, "search_scope", []), [])

    async def test_reused_discovery_agent_does_not_keep_previous_scope(self):
        agent = DiscoveryAgent()
        first = await self.discover(["美国"], agent=agent)
        second = await self.discover([], description="Generic cleaning product", agent=agent)
        self.assertEqual(getattr(first, "search_scope", []), ["美国"])
        self.assertEqual(getattr(second, "search_scope", []), [])

    async def test_target_name_or_model_is_not_a_shared_market_scope(self):
        for name, candidates, description, queries, expected in [
            ("Focus US", ["US"], "Focus US headphones", ["Focus US competitors"], []),
            ("Dyson V15 Detect", ["V15", "中国家用"], "Dyson V15 Detect 中国家用清洁市场", ["Dyson V15 Detect 中国家用 竞品"], ["中国家用"]),
        ]:
            with self.subTest(name=name):
                result = await self.discover(candidates, description, queries, product_name=name)
                self.assertEqual(getattr(result, "search_scope", []), expected)

    def test_old_saved_discovery_is_readable_with_empty_scope(self):
        result = CompetitorList(**{"product_name": "Legacy", "search_keywords_used": ["US personal"]})
        self.assertEqual(getattr(result, "search_scope", []), [])


class ScopeSanitizationTests(unittest.TestCase):
    def test_latin_terms_need_literal_word_boundaries_in_description_and_used_queries(self):
        from core.competitor_search_scope import sanitize_scope
        self.assertEqual(sanitize_scope(["US", "individual"], "Focus_US product for individuals", ["Focus_US individual plans"]), [])
        self.assertEqual(sanitize_scope(["US", "individual"], "Music for US individual users", ["US individual music plans"]), ["US", "individual"])

    def test_private_or_malformed_scope_is_rejected_even_if_it_was_in_both_inputs(self):
        from core.competitor_search_scope import sanitize_scope
        values = ["a@example.test", "+1 212 555 0123", "13800138000", "212.555.0123", "138‑0013‑8000", "https://example.test/us", "example.test", "US\npersonal", "\nUS", "x" * 80, None, {}]
        text = " ".join(v for v in values if isinstance(v, str))
        self.assertEqual(sanitize_scope(values, text, [text]), [])
        self.assertEqual(sanitize_scope("US", "US", ["US"]), [])

    def test_scope_is_deduplicated_bounded_and_not_inferred_by_country_or_brand(self):
        from core.competitor_search_scope import sanitize_scope
        result = sanitize_scope(["US", "us", "个人用户", "2026", "订阅服务", "第五星区"],
            "US 个人用户 2026 订阅服务 第五星区", ["US 个人用户 2026 订阅服务 第五星区"])
        self.assertEqual(result, ["US", "个人用户", "2026", "订阅服务"])
        self.assertEqual(sanitize_scope(["US"], "美国个人用户", ["US music"]), [])

    def test_irrelevant_candidates_do_not_exhaust_the_valid_scope_budget(self):
        from core.competitor_search_scope import sanitize_scope
        self.assertEqual(sanitize_scope(["irrelevant1", "irrelevant2", "irrelevant3", "irrelevant4", "US", "individual"],
                         "US individual users", ["US individual service"]), ["US", "individual"])

    def test_scope_queries_preserves_count_and_native_query_intent(self):
        from core.competitor_search_scope import scope_queries
        queries = ["Rival 功能", "Rival 价格", "US Rival reviews"]
        scoped = scope_queries(queries, ["US", "individual"])
        self.assertEqual(len(scoped), 3)
        for original, result in zip(queries, scoped):
            self.assertIn(original, result)
            self.assertIn("US", result)
            self.assertIn("individual", result)
        self.assertEqual(scope_queries(queries, []), queries)
        self.assertEqual(scope_queries(queries, None), queries)
        self.assertEqual(queries, ["Rival 功能", "Rival 价格", "US Rival reviews"])


class ScopePropagationTests(unittest.IsolatedAsyncioTestCase):
    def orchestrator(self):
        from tests.test_orchestrator_baseline import make_orchestrator, competitor_list, FakeCollectionAgent
        listing = competitor_list()
        listing.search_scope = ["美国", "个人用户"]
        class ScopeCollection(FakeCollectionAgent):
            def collect_target_product(self, description, product_name, feedback="", search_scope=None):
                self.target_scope = search_scope
                return super().collect_target_product(description, product_name, feedback)

            async def async_collect_target_product(self, description, product_name, feedback="", search_scope=None):
                return self.collect_target_product(description, product_name, feedback, search_scope)

            async def run(self, description, competitors, feedback=""):
                self.rival_scope = competitors.search_scope
                return await super().run(description, competitors, feedback)
        orch = make_orchestrator(competitors=listing, collection_passes=[False, True])
        orch.collection_agent = ScopeCollection()
        return orch

    async def test_legacy_target_and_collection_repair_receive_discovery_scope(self):
        from tests.test_orchestrator_baseline import run_quietly
        orch, repairs = self.orchestrator(), []
        async def repair(*args, **kwargs):
            repairs.append(kwargs.get("search_scope"))
            return args[3], args[4], ""
        with patch("config.SKIP_QA", False), patch("core.orchestrator.repair_collection", repair):
            await run_quietly(orch, "Target 美国个人用户市场", 2)
        self.assertEqual(orch.collection_agent.target_scope, ["美国", "个人用户"])
        self.assertEqual(orch.collection_agent.rival_scope, ["美国", "个人用户"])
        self.assertEqual(repairs, [["美国", "个人用户"]])

    async def test_graph_target_and_collection_repair_receive_discovery_scope(self):
        from workflow.nodes import AnalysisGraphNodes
        from workflow.state import initial_analysis_state
        from tests.test_workflow_nodes import run_to_collection_checked, merge_state
        orch, repairs = self.orchestrator(), []
        async def repair(*args, **kwargs):
            repairs.append(kwargs.get("search_scope"))
            return args[3], args[4], ""
        nodes = AnalysisGraphNodes(orch)
        with patch("config.SKIP_QA", False), patch("workflow.nodes.repair_collection", repair):
            state = await run_to_collection_checked(nodes, initial_analysis_state("Target 美国个人用户市场", 2))
            state = merge_state(state, await nodes.prepare_collection_retry(state))
        self.assertEqual(orch.collection_agent.target_scope, ["美国", "个人用户"])
        self.assertEqual(orch.collection_agent.rival_scope, ["美国", "个人用户"])
        self.assertEqual(repairs, [["美国", "个人用户"]])


if __name__ == "__main__":
    unittest.main()
