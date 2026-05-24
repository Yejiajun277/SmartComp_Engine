# -*- coding: utf-8 -*-
"""
agents/collection_agent.py — 数据采集Agent

职责：对每个竞品，采集产品功能、定价、用户评价、市场份额等信息
LLM调用：1+N次（维度拆解 + 逐竞品汇总）
外部工具：百度AI搜索
提示词来源：prompts/collection_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import CompetitorList, CompetitorData
from core.prompt_loader import load as load_prompts
from core.search_client import SearchClient
import config
import json


class CollectionAgent(BaseAgent):
    """数据采集Agent — 逐竞品深度采集"""

    def __init__(self):
        prompts = load_prompts("collection_agent")
        super().__init__(
            agent_id="CollectionAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_collect = prompts["prompt_collect"]
        self.search_client = SearchClient()

    async def run(self, product_description: str,
                  competitor_list: CompetitorList) -> dict[str, CompetitorData]:
        """
        主运行逻辑：逐竞品搜索+汇总

        Args:
            product_description: 用户产品描述
            competitor_list: 竞品列表

        Returns:
            dict[str, CompetitorData]: 竞品名称 → 采集数据
        """
        self._log(f"📊 开始采集数据，共{len(competitor_list.competitors)}个竞品")

        result_data = {}
        product_name = competitor_list.product_name

        for i, comp in enumerate(competitor_list.competitors):
            self._log(f"   采集 {i+1}/{len(competitor_list.competitors)}: {comp.name}")
            data = self._collect_competitor(product_name, product_description, comp.name)
            result_data[comp.name] = data

        self._log(f"✅ 数据采集完成: {len(result_data)}个竞品")
        return result_data

    def _collect_competitor(self, product_name: str,
                            product_description: str,
                            competitor_name: str) -> CompetitorData:
        """采集单个竞品数据"""
        # 生成搜索查询
        queries = [
            f"{competitor_name} 产品功能介绍",
            f"{competitor_name} 定价 价格 收费标准",
            f"{competitor_name} 市场份额 用户量 评测",
            f"{competitor_name} vs {product_name} 对比",
        ]

        # 执行搜索
        search_results = self.search_client.batch_search(queries)

        # 提取搜索文本
        all_text = ""
        sources = []
        for sr in search_results:
            query = sr.get("query", "")
            result = sr.get("result")
            text = SearchClient.extract_text(result) if result else ""
            if text:
                all_text += f"\n--- 搜索: {query} ---\n{text[:1500]}\n"
                sources.append(text[:500])

        # LLM汇总提取
        if config.ENABLE_LLM and all_text:
            prompt = self._prompt_collect.format(
                product_name=product_name,
                product_description=product_description,
                competitor_name=competitor_name,
                search_results=all_text[:8000],
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                return CompetitorData(
                    name=competitor_name,
                    product_features=result.get("product_features", ""),
                    pricing_info=result.get("pricing_info", ""),
                    market_share=result.get("market_share", ""),
                    user_reviews=result.get("user_reviews", ""),
                    strengths=result.get("strengths", ""),
                    weaknesses=result.get("weaknesses", ""),
                    channels=result.get("channels", ""),
                    search_sources=sources,
                )
            else:
                self._log(f"   ⚠️ {competitor_name} LLM汇总失败，降级到规则引擎")

        # Fallback: 规则引擎提取
        return CompetitorData(
            name=competitor_name,
            product_features=all_text[:500] if all_text else "数据采集失败",
            search_sources=sources,
        )
