# -*- coding: utf-8 -*-
"""
agents/discovery_agent.py - 竞品发现 Agent
"""

from __future__ import annotations

import re

import config
from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from core.search_client import SearchClient
from models.domain import CompetitorInfo, CompetitorList


class DiscoveryAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("discovery_agent")
        super().__init__(
            agent_id="DiscoveryAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_keywords = prompts["prompt_keywords"]
        self._prompt_filter = prompts["prompt_filter"]
        self.search_client = SearchClient()

    async def run(
        self,
        product_description: str,
        max_competitors: int = config.DEFAULT_COMPETITOR_COUNT,
    ) -> CompetitorList:
        keywords = self._generate_keywords(product_description)
        search_results = self.search_client.batch_search(keywords)
        competitor_list = self._filter_competitors(product_description, search_results, max_competitors)
        self._log(f"发现竞品 {len(competitor_list.competitors)} 个")
        return competitor_list

    def _generate_keywords(self, product_description: str) -> list[str]:
        if config.ENABLE_LLM:
            result = self.ask_llm_json(
                self._prompt_keywords.format(
                    product_description=product_description,
                    count=5,
                )
            )
            if result.get("keywords"):
                return [str(item) for item in result["keywords"][:5]]
        core = product_description.split("，")[0].split(",")[0].strip()
        return [
            f"{core} competitors",
            f"{core} alternatives",
            f"{core} 对比 竞品",
        ]

    def _filter_competitors(
        self,
        product_description: str,
        search_results: list[dict],
        max_competitors: int,
    ) -> CompetitorList:
        texts = []
        for item in search_results:
            result = item.get("result")
            if result:
                texts.append(SearchClient.extract_text(result)[:1500])
        merged = "\n".join(texts)
        if config.ENABLE_LLM and merged:
            result = self.ask_llm_json(
                self._prompt_filter.format(
                    product_description=product_description,
                    search_results=merged[:6000],
                    max_competitors=max_competitors,
                ),
                max_tokens=2048,
            )
            if result.get("competitors"):
                return CompetitorList(
                    product_name=result.get("product_name", product_description),
                    product_category=result.get("product_category", ""),
                    competitors=[
                        CompetitorInfo(
                            name=str(item.get("name", "")).strip(),
                            brief=str(item.get("brief", "")).strip(),
                            relevance=str(item.get("relevance", "MEDIUM")),
                        )
                        for item in result["competitors"][:max_competitors]
                        if str(item.get("name", "")).strip()
                    ],
                    search_keywords_used=[entry.get("query", "") for entry in search_results],
                )

        names = []
        seen = {product_description.lower()}
        for token in re.findall(r"\b[A-Z][A-Za-z0-9][A-Za-z0-9 ._-]{1,40}\b", merged):
            name = token.strip(" ._-")
            lowered = name.lower()
            if lowered in seen or len(name.split()) > 4:
                continue
            seen.add(lowered)
            names.append(CompetitorInfo(name=name, brief="从搜索摘要中识别。", relevance="MEDIUM"))
            if len(names) >= max_competitors:
                break
        if not names:
            names = [
                CompetitorInfo(name=f"竞品{i + 1}", brief="自动发现失败，待手工补充。", relevance="LOW")
                for i in range(min(max_competitors, 3))
            ]
        return CompetitorList(
            product_name=product_description,
            competitors=names,
            search_keywords_used=[entry.get("query", "") for entry in search_results],
        )
