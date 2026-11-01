"""Every collection search keeps explicit public scope without agent state."""
import unittest
from unittest.mock import patch
from agents.collection_agent import CollectionAgent
from models.domain import CompetitorList, CompetitorInfo, CompetitorData
from tests.test_collection_citation_binding import SourceSearch


class CollectionSearchScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_entrypoints_keep_query_count_scope_and_private_description_out(self):
        for target in [False, True]:
            for asynchronous in [False, True]:
                with self.subTest(target=target, asynchronous=asynchronous):
                    agent = CollectionAgent()
                    agent.search_client = SourceSearch()
                    method = ("async_collect_target_product" if asynchronous else "collect_target_product") if target else (
                        "_async_collect_competitor" if asynchronous else "_collect_competitor")
                    args = ("Full user text PRIVATE_CLAUSE", "Target") if target else ("Target", "Full user text PRIVATE_CLAUSE", "Rival")
                    with patch("config.ENABLE_LLM", False):
                        result = getattr(agent, method)(*args, search_scope=["RegionOmega", "personal accounts"])
                        if asynchronous:
                            await result
                    self.assertEqual(len(agent.search_client.queries), 7)
                    self.assertTrue(all("RegionOmega" in q and "personal accounts" in q for q in agent.search_client.queries))
                    self.assertTrue(all("PRIVATE_CLAUSE" not in q for q in agent.search_client.queries))

    async def test_run_uses_saved_scope_and_same_agent_next_task_does_not_reuse_it(self):
        agent = CollectionAgent()
        agent.search_client = SourceSearch()
        competitors = CompetitorList("Target", competitors=[CompetitorInfo("Rival")], search_scope=["RegionOmega"])
        with patch("config.ENABLE_LLM", False):
            await agent.run("PRIVATE_CLAUSE", competitors)
            await agent.async_collect_target_product("Another task", "Another")
        self.assertTrue(all("RegionOmega" in q for q in agent.search_client.queries[:7]))
        self.assertTrue(all("RegionOmega" not in q for q in agent.search_client.queries[7:]))

    async def test_automatic_and_directed_supplement_queries_use_the_same_explicit_scope(self):
        for asynchronous in [False, True]:
            for field in ["pricing_tiers", "market_share", "strengths"]:
                with self.subTest(asynchronous=asynchronous, field=field):
                    agent = CollectionAgent()
                    agent.search_client = SourceSearch()
                    if field == "strengths":
                        method = "async_supplement_missing_fields" if asynchronous else "supplement_missing_fields"
                        args = ("Target", {"Rival": CompetitorData("Rival")}, {"Rival": [field]})
                    else:
                        method = ("_async_" if asynchronous else "_") + ("supplement_pricing" if field == "pricing_tiers" else "supplement_market_share")
                        args = ("Rival", "Target", [], []) if field == "pricing_tiers" else ("Rival", "", [])
                    with patch("config.ENABLE_LLM", False):
                        value = getattr(agent, method)(*args, search_scope=["RegionOmega"])
                        if asynchronous:
                            await value
                    self.assertEqual(len(agent.search_client.queries), 2)
                    self.assertTrue(all("RegionOmega" in q for q in agent.search_client.queries))
