# -*- coding: utf-8 -*-
"""
agents/collection_agent.py — 数据采集Agent

职责：对每个竞品，采集产品功能、定价、用户评价、市场份额等信息
LLM调用：1+N次（维度拆解 + 逐竞品汇总）
外部工具：百度AI搜索
提示词来源：prompts/collection_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import CompetitorList, CompetitorData, Citation, FeatureItem, PricingTier
from core.prompt_loader import load as load_prompts
from core.search_client import SearchClient
import config
import json
import re


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
        self._last_search_texts: dict[str, str] = {}

    def get_search_texts(self) -> dict[str, str]:
        """返回每个竞品的原始搜索文本（供幻觉检测使用）"""
        return self._last_search_texts

    @staticmethod
    def _validate_against_source(data: 'CompetitorData', search_text: str) -> list[str]:
        """程序化校验高幻觉字段：提取内容中的数字和关键实体，检查是否在搜索文本中出现。

        Returns:
            list[str]: 被清空的字段名列表
        """
        if not search_text:
            return []

        cleared = []

        # 从字段内容中提取所有数字（含小数、百分比、亿/万单位）
        def extract_numbers(text: str) -> list[str]:
            return re.findall(r'\d[\d,.]*%?|\d+[万亿]', text)

        # 高幻觉字段校验
        high_risk_fields = {
            "market_share": data.market_share,
            "strengths": data.strengths,
            "weaknesses": data.weaknesses,
            "user_reviews": data.user_reviews,
        }

        for field_name, field_value in high_risk_fields.items():
            if not field_value or len(field_value.strip()) < 10:
                continue

            numbers = extract_numbers(field_value)
            if not numbers:
                continue

            # 检查数字是否在搜索文本中出现
            found_count = 0
            for num in numbers:
                clean_num = num.replace(",", "")
                if clean_num in search_text or num in search_text:
                    found_count += 1

            # 如果所有数字都不在搜索文本中，清空该字段
            if numbers and found_count == 0:
                print(f"   🚫 程序化校验: {field_name} 中的数字 {numbers[:3]} 未在搜索文本中找到，清空")
                setattr(data, field_name, "")
                cleared.append(field_name)

        return cleared

    def collect_target_product(self, product_description: str,
                               product_name: str,
                               feedback: str = "") -> CompetitorData:
        """采集目标产品自身信息"""
        self._log(f"   采集目标产品: {product_name}")
        queries = [
            f"{product_name} 产品功能介绍",
            f"{product_name} 定价 价格 收费标准",
            f"{product_name} 市场份额 用户量 评测",
            f"{product_name} 用户评价 使用场景",
            f"{product_name} 竞争优势 核心优势 行业地位",
            f"{product_name} 劣势 不足 用户吐槽 差评",
            f"{product_name} 渠道策略 推广方式 合作伙伴 生态",
        ]
        return self._collect_entity(
            product_name=product_name,
            product_description=product_description,
            entity_name=product_name,
            queries=queries,
            feedback=feedback,
            cache_search_text=False,
        )

    async def run(self, product_description: str,
                  competitor_list: CompetitorList,
                  feedback: str = "") -> dict[str, CompetitorData]:
        """
        主运行逻辑：逐竞品搜索+汇总

        Args:
            product_description: 用户产品描述
            competitor_list: 竞品列表

        Returns:
            dict[str, CompetitorData]: 竞品名称 → 采集数据
        """
        self._log(f"📊 开始采集数据，共{len(competitor_list.competitors)}个竞品")

        if feedback:
            self._log(f"   📝 收到质检反馈，将据此修正采集")

        result_data = {}
        product_name = competitor_list.product_name

        for i, comp in enumerate(competitor_list.competitors):
            self._log(f"   采集 {i+1}/{len(competitor_list.competitors)}: {comp.name}")
            data = self._collect_competitor(product_name, product_description, comp.name, feedback)
            result_data[comp.name] = data

        self._log(f"✅ 数据采集完成: {len(result_data)}个竞品")
        return result_data

    def _collect_competitor(self, product_name: str,
                            product_description: str,
                            competitor_name: str,
                            feedback: str = "") -> CompetitorData:
        """采集单个竞品数据，同时构建结构化引用"""
        queries = [
            f"{competitor_name} 产品功能介绍",
            f"{competitor_name} 定价 价格 收费标准",
            f"{competitor_name} 市场份额 用户量 评测",
            f"{competitor_name} vs {product_name} 对比",
            f"{competitor_name} 竞争优势 核心优势 行业地位",
            f"{competitor_name} 劣势 不足 用户吐槽",
            f"{competitor_name} 渠道策略 推广方式 生态布局",
        ]
        return self._collect_entity(
            product_name=product_name,
            product_description=product_description,
            entity_name=competitor_name,
            queries=queries,
            feedback=feedback,
            cache_search_text=True,
        )

    def _collect_entity(self, product_name: str,
                        product_description: str,
                        entity_name: str,
                        queries: list[str],
                        feedback: str = "",
                        cache_search_text: bool = True) -> CompetitorData:
        """采集单个实体数据，同时构建结构化引用"""
        # 执行搜索
        search_results = self.search_client.batch_search(queries)

        # 提取搜索文本 + 构建结构化引用
        all_text = ""
        sources = []
        citations = []
        citation_counter = 0

        for i, sr in enumerate(search_results):
            query = sr.get("query", "")
            result = sr.get("result")
            text = SearchClient.extract_text(result) if result else ""
            if text:
                all_text += f"\n--- 搜索: {query} ---\n{text[:2500]}\n"
                sources.append(text[:500])

            # 从结构化 references 构建 Citation 对象
            for ref in sr.get("references", []):
                ref_url = ref.get("url", "")
                ref_title = ref.get("title", "")
                if not ref_url and not ref_title:
                    continue
                citations.append(Citation(
                    id=f"{entity_name}:q{i}:r{citation_counter}",
                    title=ref_title,
                    url=ref_url,
                    snippet=ref.get("content", "") or ref.get("summary", ""),
                    site_name=ref.get("site_name", ""),
                    query=query,
                    competitor=entity_name,
                ))
                citation_counter += 1

        # 缓存原始搜索文本（供幻觉检测使用）
        if cache_search_text:
            self._last_search_texts[entity_name] = all_text

        # 注入质检反馈
        if feedback:
            all_text += f"\n--- 质检反馈（请据此修正）---\n{feedback}\n"

        # LLM汇总提取
        if config.ENABLE_LLM and all_text:
            prompt = self._prompt_collect.format(
                product_name=product_name,
                product_description=product_description,
                competitor_name=entity_name,
                search_results=all_text[:12000],
            )
            result = self.ask_llm_json(prompt, max_tokens=6144, temperature=0)
            if result:
                # 解析结构化产品功能
                product_features = []
                for fi in result.get("product_features", []):
                    if isinstance(fi, dict):
                        product_features.append(FeatureItem(
                            name=fi.get("name", ""),
                            description=fi.get("description", ""),
                        ))
                    elif isinstance(fi, str):
                        product_features.append(FeatureItem(name=fi, description=fi))

                # 解析结构化定价层级
                pricing_tiers = []
                for pt in result.get("pricing_tiers", []):
                    if isinstance(pt, dict):
                        pricing_tiers.append(PricingTier(
                            tier_name=pt.get("tier_name", ""),
                            price=pt.get("price", ""),
                            features=pt.get("features", []),
                        ))

                # 补充搜索：如果定价或市场份额数据缺失，执行专项搜索
                pricing_tiers, extra_cites1 = self._supplement_pricing(
                    entity_name, product_name, pricing_tiers, citations
                )
                market_share = result.get("market_share", "")
                market_share, extra_cites2 = self._supplement_market_share(
                    entity_name, market_share, citations
                )
                citations.extend(extra_cites1)
                citations.extend(extra_cites2)

                data = CompetitorData(
                    name=entity_name,
                    product_features=product_features,
                    pricing_tiers=pricing_tiers,
                    market_share=market_share,
                    user_reviews=result.get("user_reviews", ""),
                    strengths=result.get("strengths", ""),
                    weaknesses=result.get("weaknesses", ""),
                    channels=result.get("channels", ""),
                    search_sources=sources,
                    citations=citations,
                )
                # 程序化幻觉校验：清空搜索文本中完全不存在的数字内容
                self._validate_against_source(data, all_text)
                return data
            else:
                self._log(f"   ⚠️ {entity_name} LLM汇总失败，降级到规则引擎")

        # Fallback: 规则引擎提取
        return CompetitorData(
            name=entity_name,
            product_features=[FeatureItem(name="数据采集失败", description=all_text[:500] if all_text else "")],
            search_sources=sources,
            citations=citations,
        )

    def _supplement_pricing(self, entity_name: str, product_name: str,
                            pricing_tiers: list, existing_cites: list) -> tuple:
        """如果定价数据缺失，执行补充搜索"""
        if pricing_tiers and any(pt.price for pt in pricing_tiers):
            return pricing_tiers, []

        self._log(f"   📝 {entity_name} 定价数据缺失，执行补充搜索")
        extra_queries = [
            f"{entity_name} 会员价格 套餐 收费",
            f"{entity_name} 免费版 付费版 premium",
        ]
        extra_results = self.search_client.batch_search(extra_queries)
        extra_text = ""
        extra_cites = []
        cite_counter = len(existing_cites)

        for i, sr in enumerate(extra_results):
            result = sr.get("result")
            text = SearchClient.extract_text(result) if result else ""
            if text:
                extra_text += f"\n--- 补充搜索: {sr.get('query', '')} ---\n{text[:1500]}\n"
            for ref in sr.get("references", []):
                ref_url = ref.get("url", "")
                ref_title = ref.get("title", "")
                if not ref_url and not ref_title:
                    continue
                extra_cites.append(Citation(
                    id=f"{entity_name}:sup_price_{i}:r{cite_counter}",
                    title=ref_title,
                    url=ref_url,
                    snippet=ref.get("content", "") or ref.get("summary", ""),
                    site_name=ref.get("site_name", ""),
                    query=sr.get("query", ""),
                    competitor=entity_name,
                ))
                cite_counter += 1

        if extra_text and config.ENABLE_LLM:
            prompts = load_prompts("collection_agent")
            prompt = prompts["prompt_collect"].format(
                product_name=product_name,
                product_description="",
                competitor_name=entity_name,
                search_results=extra_text[:6000],
            )
            result = self.ask_llm_json(prompt, max_tokens=2048, temperature=0)
            if result and result.get("pricing_tiers"):
                for pt in result["pricing_tiers"]:
                    if isinstance(pt, dict) and pt.get("price"):
                        pricing_tiers.append(PricingTier(
                            tier_name=pt.get("tier_name", ""),
                            price=pt.get("price", ""),
                            features=pt.get("features", []),
                        ))

        return pricing_tiers, extra_cites

    def _supplement_market_share(self, entity_name: str,
                                  market_share: str,
                                  existing_cites: list) -> tuple:
        """如果市场份额数据缺失，执行补充搜索"""
        if market_share and len(market_share.strip()) > 5:
            return market_share, []

        self._log(f"   📝 {entity_name} 市场份额数据缺失，执行补充搜索")
        extra_queries = [
            f"{entity_name} 市场份额 用户规模 DAU MAU",
            f"{entity_name} 行业排名 市占率",
        ]
        extra_results = self.search_client.batch_search(extra_queries)
        extra_text = ""
        extra_cites = []
        cite_counter = len(existing_cites)

        for i, sr in enumerate(extra_results):
            result = sr.get("result")
            text = SearchClient.extract_text(result) if result else ""
            if text:
                extra_text += f"\n--- 补充搜索: {sr.get('query', '')} ---\n{text[:1500]}\n"
            for ref in sr.get("references", []):
                ref_url = ref.get("url", "")
                ref_title = ref.get("title", "")
                if not ref_url and not ref_title:
                    continue
                extra_cites.append(Citation(
                    id=f"{entity_name}:sup_market_{i}:r{cite_counter}",
                    title=ref_title,
                    url=ref_url,
                    snippet=ref.get("content", "") or ref.get("summary", ""),
                    site_name=ref.get("site_name", ""),
                    query=sr.get("query", ""),
                    competitor=entity_name,
                ))
                cite_counter += 1

        if extra_text and config.ENABLE_LLM:
            prompts = load_prompts("collection_agent")
            prompt = prompts["prompt_collect"].format(
                product_name=entity_name,
                product_description="",
                competitor_name=entity_name,
                search_results=extra_text[:6000],
            )
            result = self.ask_llm_json(prompt, max_tokens=2048, temperature=0)
            if result and result.get("market_share"):
                market_share = result["market_share"]

        return market_share, extra_cites

    def supplement_missing_fields(self, product_name: str,
                                   competitors_data: dict[str, 'CompetitorData'],
                                   missing_fields: dict[str, list[str]]) -> dict[str, 'CompetitorData']:
        """根据质检反馈的缺失/截断字段，对特定竞品做针对性补充搜索。

        Args:
            product_name: 我方产品名
            competitors_data: 当前采集数据
            missing_fields: {竞品名: [缺失字段名列表]}

        Returns:
            更新后的 competitors_data
        """
        field_queries = {
            "strengths": ["竞争优势 核心优势 行业地位", "优势 领先 竞争力"],
            "weaknesses": ["劣势 不足 用户吐槽 差评", "问题 缺点 改进"],
            "channels": ["渠道策略 推广方式 合作伙伴 生态", "分发 合作 生态布局"],
            "market_share": ["市场份额 用户量 DAU MAU 市占率", "行业排名 市场占有率"],
            "pricing_tiers": ["定价 价格 收费标准 会员 套餐", "免费版 付费版 premium"],
            "user_reviews": ["用户评价 口碑 评分 好评 差评", "用户反馈 评测"],
        }

        def _is_truncated(text: str) -> bool:
            """判断文本是否被截断"""
            if not text or len(text.strip()) < 10:
                return False
            text = text.strip()
            normal_endings = {"。", "！", "？", ".", "!", "?", "；", "」", "）", "》", "\"", "'", "…"}
            if text[-1] in normal_endings:
                return False
            if len(text) > 50:
                return True
            return False

        for comp_name, fields in missing_fields.items():
            if comp_name not in competitors_data:
                continue

            data = competitors_data[comp_name]
            all_extra_text = ""
            extra_cites = []
            cite_counter = len(data.citations)

            # 为每个缺失/截断/幻觉字段执行针对性搜索
            for field_name in fields:
                current_val = getattr(data, field_name, "")
                is_empty = not current_val or not str(current_val).strip()
                is_truncated = _is_truncated(str(current_val))

                # 幻觉字段：有内容但被QA标记为编造，需要清空后重新提取
                if not is_empty and not is_truncated:
                    self._log(f"   🔍 补充搜索(幻觉): {comp_name} 的 {field_name}，清空编造内容后重新提取")
                    if field_name == "pricing_tiers":
                        setattr(data, field_name, [])
                    else:
                        setattr(data, field_name, "")
                elif is_truncated:
                    self._log(f"   🔍 补充搜索(截断): {comp_name} 的 {field_name}")
                else:
                    self._log(f"   🔍 补充搜索(缺失): {comp_name} 的 {field_name}")

                queries = field_queries.get(field_name, [field_name])
                actual_queries = [f"{comp_name} {q}" for q in queries]

                extra_results = self.search_client.batch_search(actual_queries)

                for i, sr in enumerate(extra_results):
                    result = sr.get("result")
                    text = SearchClient.extract_text(result) if result else ""
                    if text:
                        all_extra_text += f"\n--- 补充搜索({field_name}): {sr.get('query', '')} ---\n{text[:1500]}\n"
                    for ref in sr.get("references", []):
                        ref_url = ref.get("url", "")
                        ref_title = ref.get("title", "")
                        if not ref_url and not ref_title:
                            continue
                        extra_cites.append(Citation(
                            id=f"{comp_name}:sup_{field_name}_{i}:r{cite_counter}",
                            title=ref_title,
                            url=ref_url,
                            snippet=ref.get("content", "") or ref.get("summary", ""),
                            site_name=ref.get("site_name", ""),
                            query=sr.get("query", ""),
                            competitor=comp_name,
                        ))
                        cite_counter += 1

            # 用 LLM 从补充搜索结果中提取缺失字段
            if all_extra_text and config.ENABLE_LLM:
                prompts = load_prompts("collection_agent")
                # 在 prompt 末尾追加完整性要求，避免 LLM 再次截断
                extract_prompt = prompts["prompt_collect"].format(
                    product_name=product_name,
                    product_description="",
                    competitor_name=comp_name,
                    search_results=all_extra_text[:8000],
                )
                extract_prompt += "\n\n### 特别重要：本次是补充搜索修复\n上次提取的内容被质检标记为幻觉（编造），本次必须严格遵守以下规则：\n1. 只提取搜索结果中**原文明确写到**的信息\n2. 搜索结果中没有的数字、事实、评价 → 留空\"\"\n3. 不要综合、推断、脑补任何内容\n4. 宁可留空也不要写不确定的内容\n5. 每条文本字段必须以完整句子结尾，禁止截断"

                result = self.ask_llm_json(extract_prompt, max_tokens=8192, temperature=0)
                if result:
                    still_truncated = []
                    for field_name in fields:
                        current_val = getattr(data, field_name, "")
                        is_empty = not current_val or not str(current_val).strip()
                        is_truncated = _is_truncated(str(current_val))

                        if not is_empty and not is_truncated:
                            continue

                        new_val = result.get(field_name, "")
                        if new_val:
                            if isinstance(new_val, list):
                                if field_name == "pricing_tiers":
                                    new_val = [
                                        PricingTier(
                                            tier_name=pt.get("tier_name", ""),
                                            price=pt.get("price", ""),
                                            features=pt.get("features", []),
                                        )
                                        for pt in new_val
                                        if isinstance(pt, dict)
                                    ]
                                setattr(data, field_name, new_val)
                                self._log(f"   ✅ {comp_name}.{field_name} 补充成功")
                            elif isinstance(new_val, str) and len(new_val.strip()) > 5:
                                # 验证新值是否仍然截断
                                if _is_truncated(new_val):
                                    still_truncated.append(field_name)
                                    self._log(f"   ⚠️ {comp_name}.{field_name} 补充后仍截断，保留新值")
                                setattr(data, field_name, new_val)
                                self._log(f"   ✅ {comp_name}.{field_name} 补充成功")

                    # 如果仍有截断，再尝试一次（只处理截断字段）
                    if still_truncated:
                        self._log(f"   🔄 {comp_name} 仍有{len(still_truncated)}个截断字段，二次补充")
                        retry_prompt = extract_prompt + f"\n\n### 特别注意\n以下字段上次提取时被截断，请确保本次输出完整：{', '.join(still_truncated)}"
                        retry_result = self.ask_llm_json(retry_prompt, max_tokens=8192, temperature=0)
                        if retry_result:
                            for field_name in still_truncated:
                                retry_val = retry_result.get(field_name, "")
                                if retry_val and isinstance(retry_val, str) and len(retry_val.strip()) > 5:
                                    setattr(data, field_name, retry_val)
                                    status = "仍截断" if _is_truncated(retry_val) else "已修复"
                                    self._log(f"   ✅ {comp_name}.{field_name} 二次补充{status}")

                    # 补充引用
                    data.citations.extend(extra_cites)

        return competitors_data
