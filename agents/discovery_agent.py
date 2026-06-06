# -*- coding: utf-8 -*-
"""
agents/discovery_agent.py — 竞品发现Agent

职责：根据用户产品描述，搜索并筛选出3~8个核心竞品
LLM调用：2次（关键词生成 + 结果筛选）
外部工具：百度AI搜索
提示词来源：prompts/discovery_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import CompetitorInfo, CompetitorList
from core.prompt_loader import load as load_prompts
from core.search_client import SearchClient
import config
import json


class DiscoveryAgent(BaseAgent):
    """竞品发现Agent — 搜索并筛选核心竞品"""

    def __init__(self):
        prompts = load_prompts("discovery_agent")
        super().__init__(
            agent_id="DiscoveryAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_keywords = prompts["prompt_keywords"]
        self._prompt_filter = prompts["prompt_filter"]
        self.search_client = SearchClient()

    async def run(self, product_description: str,
                  max_competitors: int = config.DEFAULT_COMPETITOR_COUNT) -> CompetitorList:
        """
        主运行逻辑：生成搜索关键词 → 搜索 → 筛选竞品

        Args:
            product_description: 用户产品描述
            max_competitors: 最大竞品数量

        Returns:
            CompetitorList: 发现的竞品列表
        """
        self._log(f"🔍 开始发现竞品: {product_description[:50]}...")

        # ── 步骤1: 生成搜索关键词 ──
        keywords = self._generate_keywords(product_description)
        self._log(f"   生成搜索关键词: {keywords}")

        # ── 步骤2: 执行搜索 ──
        search_results = self._search(keywords)
        self._log(f"   搜索完成，获得{len(search_results)}组结果")

        # ── 步骤3: 筛选竞品 ──
        competitor_list = self._filter_competitors(
            product_description, search_results, max_competitors
        )

        self._log(f"✅ 发现{len(competitor_list.competitors)}个核心竞品")
        for c in competitor_list.competitors:
            self._log(f"   • {c.name} ({c.relevance}): {c.brief[:40]}...")

        return competitor_list

    def _generate_keywords(self, product_description: str) -> list[str]:
        """生成搜索关键词（LLM + 规则引擎降级）"""
        if config.ENABLE_LLM:
            prompt = self._prompt_keywords.format(
                product_description=product_description,
                count=5,
            )
            result = self.ask_llm_json(prompt)
            if result and "keywords" in result:
                keywords = result["keywords"]
                self._log(f"   LLM生成关键词: {keywords}")
                return keywords[:8]  # 最多8组关键词
            else:
                self._log("   LLM关键词生成失败，降级到规则引擎")

        # Fallback: 规则引擎生成关键词
        return self._rule_keywords(product_description)

    def _rule_keywords(self, product_description: str) -> list[str]:
        """规则引擎生成搜索关键词"""
        name = product_description.strip().split("，")[0].split(",")[0]
        return [
            f"{name}竞品分析",
            f"{name}替代产品",
            f"{name}同类产品对比",
            f"类似{name}的产品",
        ]

    def _search(self, keywords: list[str]) -> list[dict]:
        """执行搜索"""
        results = self.search_client.batch_search(keywords)
        return results

    def _filter_competitors(self, product_description: str,
                            search_results: list[dict],
                            max_competitors: int) -> CompetitorList:
        """筛选核心竞品（LLM + 规则引擎降级）"""
        # 提取搜索文本
        all_text = ""
        for sr in search_results:
            query = sr.get("query", "")
            result = sr.get("result")
            text = SearchClient.extract_text(result) if result else ""
            if text:
                all_text += f"\n--- 搜索: {query} ---\n{text[:1000]}\n"

        if config.ENABLE_LLM and all_text:
            prompt = self._prompt_filter.format(
                product_description=product_description,
                search_results=all_text[:6000],  # 限制长度
                max_competitors=max_competitors,
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result and "competitors" in result:
                competitors = []
                for c in result["competitors"]:
                    competitors.append(CompetitorInfo(
                        name=c.get("name", ""),
                        brief=c.get("brief", ""),
                        relevance=c.get("relevance", "MEDIUM"),
                    ))
                return CompetitorList(
                    product_name=result.get("product_name", product_description),
                    product_category=result.get("product_category", ""),
                    competitors=competitors[:max_competitors],
                    search_keywords_used=[sr.get("query", "") for sr in search_results],
                )
            else:
                self._log("   LLM筛选失败，降级到规则引擎")

        # Fallback: 规则引擎筛选
        return self._rule_filter(product_description, search_results, max_competitors)

    def _rule_filter(self, product_description: str,
                     search_results: list[dict],
                     max_competitors: int) -> CompetitorList:
        """规则引擎筛选竞品（从搜索文本中提取产品名）"""
        import re
        competitors = []
        seen_names = set()
        product_name = product_description.strip().split("，")[0].split(",")[0]
        seen_names.add(product_name)

        for sr in search_results:
            result = sr.get("result")
            if not result:
                continue
            text = SearchClient.extract_text(result)
            if not text:
                continue

            # 尝试从搜索结果中提取产品名（简单启发式）
            # 查找《》或「」中的名称，或常见的产品名格式
            name_patterns = re.findall(r'[《「]([^」》]+)[」》]', text)
            for name in name_patterns:
                name = name.strip()
                if name and name not in seen_names and len(name) < 20:
                    seen_names.add(name)
                    competitors.append(CompetitorInfo(
                        name=name,
                        brief=f"从搜索结果中发现的相关产品",
                        relevance="MEDIUM",
                    ))
                    if len(competitors) >= max_competitors:
                        break
            if len(competitors) >= max_competitors:
                break

        if not competitors:
            self._log("   ⚠️ 规则引擎未发现竞品，使用内置示例")
            competitors = [
                CompetitorInfo(name="竞品A", brief="请手动补充", relevance="MEDIUM"),
                CompetitorInfo(name="竞品B", brief="请手动补充", relevance="MEDIUM"),
                CompetitorInfo(name="竞品C", brief="请手动补充", relevance="MEDIUM"),
            ]

        return CompetitorList(
            product_name=product_name,
            product_category="",
            competitors=competitors,
            search_keywords_used=[sr.get("query", "") for sr in search_results],
        )
