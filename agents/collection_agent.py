# -*- coding: utf-8 -*-
"""
agents/collection_agent.py — 数据采集Agent

职责：对每个竞品，采集产品功能、定价、用户评价、市场份额等信息
LLM调用：1+N次（维度拆解 + 逐竞品汇总）
外部工具：百度AI搜索
提示词来源：prompts/collection_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import (
    CompetitorList,
    CompetitorData,
    Citation,
    FeatureItem,
    PricingTier,
    normalize_text_value,
)
from core.prompt_loader import load as load_prompts
from core.search_client import SearchClient
import config
import json
import re
from itertools import zip_longest
from copy import deepcopy
from dataclasses import asdict


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
        self._repair_outcomes: list[dict] = []

    @staticmethod
    def _normalize_competitor_text_fields(result: dict) -> dict:
        """Normalize LLM text fields before any string-only operation."""
        if not isinstance(result, dict):
            return {}
        normalized = dict(result)
        for field_name in CompetitorData.TEXT_FIELDS:
            if field_name in normalized:
                normalized[field_name] = normalize_text_value(normalized[field_name])
        return normalized

    def get_search_texts(self) -> dict[str, str]:
        """返回每个竞品的原始搜索文本（供幻觉检测使用）"""
        return self._last_search_texts

    def restore_source_snapshot(self, source_texts: dict[str, str]):
        self._last_search_texts = deepcopy(source_texts)

    def get_repair_outcomes(self) -> list[dict]:
        return deepcopy(self._repair_outcomes)

    @staticmethod
    def _valid_extraction(result: dict, fields: list[str]) -> bool:
        """Missing fields are a failed response; explicit unknowns are valid facts."""
        if not isinstance(result, dict) or any(field not in result for field in fields):
            return False
        for field in fields:
            value = result[field]
            if field in ("product_features", "pricing_tiers"):
                if not isinstance(value, list):
                    return False
                required = ("name", "description") if field == "product_features" else ("tier_name", "price")
                for item in value:
                    if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in required):
                        return False
                    if "citations" in item and (not isinstance(item["citations"], list)
                            or any(not isinstance(cid, str) for cid in item["citations"])):
                        return False
                    if field == "pricing_tiers" and (not isinstance(item.get("features", []), list)
                            or any(not isinstance(feature, str) for feature in item.get("features", []))):
                        return False
            elif field not in CompetitorData.TEXT_FIELDS or not isinstance(value, str):
                return False
        return True

    def _apply_extraction(self, original: CompetitorData, result: dict,
                          fields: list[str], visible_ids: set[str]) -> CompetitorData:
        candidate = deepcopy(original)
        for field in fields:
            if field == "product_features":
                value = self._parse_features(result[field], visible_ids)
            elif field == "pricing_tiers":
                value = self._parse_prices(result[field], visible_ids)
            else:
                value = result[field]
            setattr(candidate, field, value)
        return candidate

    @staticmethod
    def _repair_prompt(entity: str, fields: list[str], context: str, feedback: str = "") -> str:
        schema = {}
        for field in fields:
            if field == "product_features":
                schema[field] = [{"name": "", "description": "", "citations": []}]
            elif field == "pricing_tiers":
                schema[field] = [{"tier_name": "", "price": "", "features": [], "citations": []}]
            else:
                schema[field] = ""
        return (f"请仅从以下真实来源重新提取 {entity} 的指定字段。只输出完整JSON，不要输出其他字段。\n"
                "保留原文的统计主体、市场、时间、地区、型号、计价单位和促销条件，"
                "不能将集团/子品牌/地区的范围扩大为当前实体。缺失范围保持未知；"
                "不支持的断言删除或留空，不能猜测数字或补全截断原文。"
                "每个字段都必须输出，未知文本用空字符串，未知数组用空数组。"
                "条目仅绑定本次目录展示的精确来源ID，不能盲填全部ID。\n"
                f"### 真实来源（仅使用以下ID和原文）\n{context}\n"
                f"### 输出结构\n{json.dumps(schema, ensure_ascii=False)}\n"
                f"### 完整质检反馈（不是事实来源）\n{feedback}")

    async def async_reextract_saved_sources(self, product_name: str, product_description: str,
                                             competitors_data: dict[str, CompetitorData],
                                             original_search_texts: dict[str, str],
                                             feedback: str = "") -> dict[str, CompetitorData]:
        """Repair against the same immutable evidence; never search or auto-supplement."""
        self._repair_outcomes = []
        self._last_search_texts = deepcopy(original_search_texts)
        updated = deepcopy(competitors_data)
        fields = ["product_features", "pricing_tiers", *CompetitorData.TEXT_FIELDS]
        for name, original in competitors_data.items():
            source_text = original_search_texts.get(name, "")
            has_evidence = source_text.strip() or any(c.snippet.strip() for c in original.citations)
            outcome = {"entity": name, "status": "failed", "reason": "missing_saved_sources"}
            self._repair_outcomes.append(outcome)
            if not has_evidence or not config.ENABLE_LLM:
                if not config.ENABLE_LLM:
                    outcome["reason"] = "llm_disabled"
                continue
            context, visible_ids = self._source_context(original.citations, source_text)
            prompt = self._repair_prompt(name, fields, context, feedback)
            prompt += "\n来源来自已保存快照，本轮没有重新联网搜索。"
            prompt += f"\n### 当前产品背景（非来源证据）\n{product_name}\n{product_description}"
            result, reason = await self.async_ask_llm_json_with_reason(prompt, max_tokens=8192, temperature=0)
            if reason != "success" or not self._valid_extraction(result, fields):
                outcome["reason"] = reason if reason != "success" else "incomplete_or_invalid_schema"
                continue
            candidate = self._apply_extraction(original, result, fields, visible_ids)
            self._validate_against_source(candidate, source_text + "\n" + "\n".join(c.snippet for c in original.citations))
            updated[name] = candidate
            outcome.update(status="accepted", reason="complete_json_from_saved_sources")
        return updated

    @staticmethod
    def _field_search_terms(field_name: str) -> list[str]:
        """Field intent is shared across product categories, without SaaS tiers."""
        return {
            "product_features": ["产品功能 服务内容 规格 使用条件", "官方参数 配套功能 适用范围"],
            "pricing_tiers": ["定价 价格 收费标准 规格 套餐", "官方报价 计价单位 适用条件"],
            "strengths": ["竞争优势 核心优势 行业地位", "优势 领先 竞争力"],
            "weaknesses": ["劣势 不足 用户吐槽 差评", "问题 缺点 改进"],
            "channels": ["渠道策略 推广方式 合作伙伴 生态", "分发 合作 生态布局"],
            "market_share": ["市场份额 规模 统计口径", "行业排名 市场占有率"],
            "user_reviews": ["用户评价 口碑 评分 好评 差评", "用户反馈 评测"],
        }.get(field_name, [field_name])

    @staticmethod
    def _source_context(citations: list[Citation], fallback_text: str,
                        max_chars: int = 16000) -> tuple[str, set[str]]:
        """Bound whole source records, round-robin across searches, with real IDs."""
        heading = ("以下是本轮真实来源ID与原文摘录。只引用已显示的ID，不根据平台名猜ID。"
                   "excerpt_truncated=true表示摘录被截断，未显示的单位、条件或事实保持未知。\n")
        if not citations:
            notice = "没有可绑定的来源ID；搜索文字仅供提取，不能伪造引用。\n"
            return notice + fallback_text[:max(0, max_chars - len(notice))], set()
        groups = {}
        for citation in citations:
            groups.setdefault(citation.query, []).append(citation)
        rows, visible_ids = [], set()
        used = len(heading)
        for group in zip_longest(*groups.values()):
            for citation in group:
                if citation is None or citation.id in visible_ids:
                    continue
                snippet = citation.snippet or ""
                record = json.dumps({
                    "id": citation.id, "title": citation.title, "url": citation.url,
                    "excerpt": snippet[:700], "excerpt_truncated": len(snippet) > 700,
                }, ensure_ascii=False)
                if used + len(record) + 1 > max_chars:
                    return heading + "\n".join(rows), visible_ids
                rows.append(record)
                visible_ids.add(citation.id)
                used += len(record) + 1
        return heading + "\n".join(rows), visible_ids

    def _item_citations(self, item: dict, allowed_ids: set[str]) -> list[str]:
        # Exact IDs only. Missing IDs stay missing; platform names and the
        # presence of entity-level sources do not prove an item binding.
        return [cid for cid in self.extract_citation_ids(item) if cid in allowed_ids]

    def _parse_features(self, items: object, allowed_ids: set[str]) -> list[FeatureItem]:
        result = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                result.append(FeatureItem(
                    name=normalize_text_value(item.get("name", "")),
                    description=normalize_text_value(item.get("description", "")),
                    citations=self._item_citations(item, allowed_ids),
                ))
            elif isinstance(item, str):
                result.append(FeatureItem(item, item))
        return result

    def _parse_prices(self, items: object, allowed_ids: set[str]) -> list[PricingTier]:
        return [PricingTier(
            tier_name=normalize_text_value(item.get("tier_name", "")),
            price=normalize_text_value(item.get("price", "")),
            features=item.get("features", []) if isinstance(item.get("features", []), list) else [],
            citations=self._item_citations(item, allowed_ids),
        ) for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def _record_supplement_sources(self, entity_name: str, context: str, *, create: bool = False):
        if create or entity_name in self._last_search_texts:
            self._last_search_texts[entity_name] = (self._last_search_texts.get(entity_name, "")
                                                   + "\n\n补充来源资料：\n" + context)

    @staticmethod
    def _validate_against_source(data: 'CompetitorData', search_text: str,
                                 field_names: set[str] | None = None) -> list[str]:
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
            if field_names is not None and field_name not in field_names:
                continue
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

    async def async_collect_target_product(self, product_description: str,
                                           product_name: str,
                                           feedback: str = "") -> CompetitorData:
        """异步采集目标产品自身信息"""
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
        return await self._async_collect_entity(
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
            data = await self._async_collect_competitor(product_name, product_description, comp.name, feedback)
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

    async def _async_collect_competitor(self, product_name: str,
                                        product_description: str,
                                        competitor_name: str,
                                        feedback: str = "") -> CompetitorData:
        """异步采集单个竞品数据，同时构建结构化引用"""
        queries = [
            f"{competitor_name} 产品功能介绍",
            f"{competitor_name} 定价 价格 收费标准",
            f"{competitor_name} 市场份额 用户量 评测",
            f"{competitor_name} vs {product_name} 对比",
            f"{competitor_name} 竞争优势 核心优势 行业地位",
            f"{competitor_name} 劣势 不足 用户吐槽",
            f"{competitor_name} 渠道策略 推广方式 生态布局",
        ]
        return await self._async_collect_entity(
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
        source_context, visible_ids = self._source_context(citations, all_text)
        if cache_search_text and (all_text.strip() or citations):
            self._last_search_texts[entity_name] = all_text + "\n" + source_context

        # LLM汇总提取
        if config.ENABLE_LLM and all_text:
            prompt = self._prompt_collect.format(
                product_name=product_name,
                product_description=product_description,
                competitor_name=entity_name,
                search_results=source_context,
            )
            if feedback:
                prompt += "\n\n### 本轮质检反馈（不是来源事实，请逐项修复）\n" + feedback
            result, truncated = self.ask_llm_json_with_truncation_check(prompt, max_tokens=8192, temperature=0)
            result = self._normalize_competitor_text_fields(result)
            if truncated and result:
                # 检测到截断：对文本字段进行补充提取
                self._log(f"   ⚠️ 采集输出被截断，补充提取文本字段...")
                result = self._supplement_text_fields(
                    result, product_name, product_description, entity_name, source_context, feedback=feedback
                )
            if result:
                # 解析结构化产品功能
                product_features = self._parse_features(result.get("product_features"), visible_ids)
                pricing_tiers = self._parse_prices(result.get("pricing_tiers"), visible_ids)

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
                self._validate_against_source(data, all_text + "\n" + source_context + "\n" + "\n".join(c.snippet for c in extra_cites1 + extra_cites2))
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

    async def _async_collect_entity(self, product_name: str,
                                    product_description: str,
                                    entity_name: str,
                                    queries: list[str],
                                    feedback: str = "",
                                    cache_search_text: bool = True) -> CompetitorData:
        """异步采集单个实体数据，同时构建结构化引用"""
        search_results = await self.search_client.async_batch_search(queries)

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

        source_context, visible_ids = self._source_context(citations, all_text)
        if cache_search_text and (all_text.strip() or citations):
            self._last_search_texts[entity_name] = all_text + "\n" + source_context

        if config.ENABLE_LLM and all_text:
            prompt = self._prompt_collect.format(
                product_name=product_name,
                product_description=product_description,
                competitor_name=entity_name,
                search_results=source_context,
            )
            if feedback:
                prompt += "\n\n### 本轮质检反馈（不是来源事实，请逐项修复）\n" + feedback
            # 使用截断检测，与同步版本保持一致的max_tokens
            result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=8192, temperature=0)
            result = self._normalize_competitor_text_fields(result)
            if truncated and result:
                # 检测到截断：对文本字段进行补充提取（与同步版本逻辑一致）
                self._log(f"   ⚠️ 异步采集输出被截断，补充提取文本字段...")
                result = self._supplement_text_fields(
                    result, product_name, product_description, entity_name, source_context, feedback=feedback
                )
            if result:
                product_features = self._parse_features(result.get("product_features"), visible_ids)
                pricing_tiers = self._parse_prices(result.get("pricing_tiers"), visible_ids)

                pricing_tiers, extra_cites1 = await self._async_supplement_pricing(
                    entity_name, product_name, pricing_tiers, citations
                )
                market_share = result.get("market_share", "")
                market_share, extra_cites2 = await self._async_supplement_market_share(
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
                self._validate_against_source(data, all_text + "\n" + source_context + "\n" + "\n".join(c.snippet for c in extra_cites1 + extra_cites2))
                return data
            self._log(f"   ⚠️ {entity_name} LLM汇总失败，降级到规则引擎")

        return CompetitorData(
            name=entity_name,
            product_features=[FeatureItem(name="数据采集失败", description=all_text[:500] if all_text else "")],
            search_sources=sources,
            citations=citations,
        )

    def _supplement_text_fields(self, result: dict,
                                product_name: str, product_description: str,
                                entity_name: str, all_text: str, feedback: str = "") -> dict:
        """
        当首次采集被截断时，对文本字段进行补充提取。
        检查 market_share, user_reviews, strengths, weaknesses, channels 是否被截断，
        如果是，发起第二次 LLM 调用只提取这些字段。
        """
        result = self._normalize_competitor_text_fields(result)

        # 检查哪些文本字段可能被截断（以句号/分号结尾的不算截断）
        text_fields = ["market_share", "user_reviews", "strengths", "weaknesses", "channels"]
        truncated_fields = []
        for field in text_fields:
            value = result.get(field, "")
            if value and len(value) > 20:
                # 如果文本很长但没有正常结尾标点，可能是截断
                if not value.rstrip().endswith(("。", "；", ".", ";", "！", "!", "）", ")")):
                    truncated_fields.append(field)

        if not truncated_fields:
            return result

        self._log(f"   📝 检测到截断字段: {truncated_fields}")

        # 构建补充提取 prompt
        supplement_prompt = f"""请从以下搜索结果中补充提取竞品 {entity_name} 的以下字段信息。

### 搜索结果
{all_text}

### 需要补充的字段
{chr(10).join(f'- {field}' for field in truncated_fields)}

### 要求
- 只提取搜索结果中明确提及的内容
- 每个字段独立提取，不要遗漏
- 输出完整句子，不要截断

### 输出格式
```json
{{{chr(10)}    {','.join(f'"{field}": "完整内容"' for field in truncated_fields)}{chr(10)}}}
```"""

        if feedback:
            supplement_prompt += "\n\n### 本轮质检反馈（不是来源事实）\n" + feedback
        supplement_result = self.ask_llm_json(supplement_prompt, max_tokens=4096, temperature=0)
        supplement_result = self._normalize_competitor_text_fields(supplement_result)
        if supplement_result:
            for field in truncated_fields:
                new_value = supplement_result.get(field, "")
                if new_value and len(new_value) > len(result.get(field, "")):
                    result[field] = new_value
                    self._log(f"   ✅ {entity_name}.{field} 补充成功")

        return result

    def _supplement_pricing(self, entity_name: str, product_name: str,
                            pricing_tiers: list, existing_cites: list) -> tuple:
        """如果定价数据缺失，执行补充搜索"""
        if pricing_tiers and any(pt.price for pt in pricing_tiers):
            return pricing_tiers, []

        self._log(f"   📝 {entity_name} 定价数据缺失，执行补充搜索")
        extra_queries = [f"{entity_name} {term}" for term in self._field_search_terms("pricing_tiers")]
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

        source_context, visible_ids = self._source_context(extra_cites, extra_text)
        self._record_supplement_sources(entity_name, source_context)

        if extra_text and config.ENABLE_LLM:
            prompts = load_prompts("collection_agent")
            prompt = prompts["prompt_collect"].format(
                product_name=product_name,
                product_description="",
                competitor_name=entity_name,
                search_results=source_context,
            )
            result = self.ask_llm_json(prompt, max_tokens=2048, temperature=0)
            if result:
                pricing_tiers.extend(tier for tier in self._parse_prices(result.get("pricing_tiers"), visible_ids) if tier.price)

        return pricing_tiers, extra_cites

    def _supplement_market_share(self, entity_name: str,
                                  market_share: str,
                                  existing_cites: list) -> tuple:
        """如果市场份额数据缺失，执行补充搜索"""
        market_share = normalize_text_value(market_share)
        if market_share and len(market_share.strip()) > 5:
            return market_share, []

        self._log(f"   📝 {entity_name} 市场份额数据缺失，执行补充搜索")
        extra_queries = [f"{entity_name} {term}" for term in self._field_search_terms("market_share")]
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

        source_context, visible_ids = self._source_context(extra_cites, extra_text)
        self._record_supplement_sources(entity_name, source_context)

        if extra_text and config.ENABLE_LLM:
            prompts = load_prompts("collection_agent")
            prompt = prompts["prompt_collect"].format(
                product_name=entity_name,
                product_description="",
                competitor_name=entity_name,
                search_results=source_context,
            )
            result = self.ask_llm_json(prompt, max_tokens=2048, temperature=0)
            if result and result.get("market_share"):
                market_share = normalize_text_value(result["market_share"])

        return market_share, extra_cites

    async def _async_supplement_pricing(self, entity_name: str, product_name: str,
                                        pricing_tiers: list, existing_cites: list) -> tuple:
        """如果定价数据缺失，异步执行补充搜索"""
        if pricing_tiers and any(pt.price for pt in pricing_tiers):
            return pricing_tiers, []

        self._log(f"   📝 {entity_name} 定价数据缺失，执行补充搜索")
        extra_queries = [f"{entity_name} {term}" for term in self._field_search_terms("pricing_tiers")]
        extra_results = await self.search_client.async_batch_search(extra_queries)
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

        source_context, visible_ids = self._source_context(extra_cites, extra_text)
        self._record_supplement_sources(entity_name, source_context)

        if extra_text and config.ENABLE_LLM:
            prompts = load_prompts("collection_agent")
            prompt = prompts["prompt_collect"].format(
                product_name=product_name,
                product_description="",
                competitor_name=entity_name,
                search_results=source_context,
            )
            result = await self.async_ask_llm_json(prompt, max_tokens=2048, temperature=0)
            if result:
                pricing_tiers.extend(tier for tier in self._parse_prices(result.get("pricing_tiers"), visible_ids) if tier.price)

        return pricing_tiers, extra_cites

    async def _async_supplement_market_share(self, entity_name: str,
                                             market_share: str,
                                             existing_cites: list) -> tuple:
        """如果市场份额数据缺失，异步执行补充搜索"""
        market_share = normalize_text_value(market_share)
        if market_share and len(market_share.strip()) > 5:
            return market_share, []

        self._log(f"   📝 {entity_name} 市场份额数据缺失，执行补充搜索")
        extra_queries = [f"{entity_name} {term}" for term in self._field_search_terms("market_share")]
        extra_results = await self.search_client.async_batch_search(extra_queries)
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

        source_context, visible_ids = self._source_context(extra_cites, extra_text)
        self._record_supplement_sources(entity_name, source_context)

        if extra_text and config.ENABLE_LLM:
            prompts = load_prompts("collection_agent")
            prompt = prompts["prompt_collect"].format(
                product_name=entity_name,
                product_description="",
                competitor_name=entity_name,
                search_results=source_context,
            )
            result = await self.async_ask_llm_json(prompt, max_tokens=2048, temperature=0)
            if result and result.get("market_share"):
                market_share = normalize_text_value(result["market_share"])

        return market_share, extra_cites

    def _prepare_field_repair(self, name: str, original: CompetitorData,
                              fields: list[str], batches: list[tuple[str, list[dict]]]):
        """Stage acquisitions separately; failed extraction never mutates saved facts."""
        text, citations, errors = "", [], []
        counter = len(original.citations)
        for field, rows in batches:
            for i, row in enumerate(rows):
                if row.get("error"):
                    errors.append({"query": row.get("query", ""), "error": str(row["error"])[:200]})
                extracted = SearchClient.extract_text(row.get("result"))
                if extracted:
                    text += f"\n--- 补充搜索({field}): {row.get('query', '')} ---\n{extracted[:1500]}\n"
                for ref in row.get("references", []):
                    if not ref.get("url") and not ref.get("title"):
                        continue
                    citations.append(Citation(
                        id=f"{name}:sup_{field}_{i}:r{counter}", title=ref.get("title", ""),
                        url=ref.get("url", ""), snippet=ref.get("content", "") or ref.get("summary", ""),
                        site_name=ref.get("site_name", ""), query=row.get("query", ""), competitor=name))
                    counter += 1
        context, visible_ids = self._source_context(citations, text)
        outcome = {"entity": name, "status": "failed", "reason": "no_usable_search_results",
                   "acquired_citations": [asdict(c) for c in citations],
                   "acquired_source_text": text, "search_errors": errors}
        self._repair_outcomes.append(outcome)
        prompt = self._repair_prompt(name, fields, context)
        return prompt, outcome, citations, text, context, visible_ids

    def _commit_field_repair(self, name: str, original: CompetitorData, fields: list[str],
                             prepared, result: dict, reason: str) -> CompetitorData:
        _, outcome, citations, text, context, visible_ids = prepared
        if reason != "success" or not self._valid_extraction(result, fields):
            outcome["reason"] = reason if reason != "success" else "incomplete_or_invalid_schema"
            return deepcopy(original)
        candidate = self._apply_extraction(original, result, fields, visible_ids)
        candidate.citations.extend(citations)
        self._validate_against_source(candidate, self._last_search_texts.get(name, "") + "\n" + text
                                      + "\n" + "\n".join(c.snippet for c in original.citations + citations), field_names=set(fields))
        self._record_supplement_sources(name, context, create=True)
        outcome.update(status="accepted", reason="complete_json_from_supplement_sources")
        return candidate

    def supplement_missing_fields(self, product_name: str,
                                  competitors_data: dict[str, CompetitorData],
                                  missing_fields: dict[str, list[str]]) -> dict[str, CompetitorData]:
        """Stage a targeted search and commit only a complete typed response."""
        self._repair_outcomes = []
        updated = deepcopy(competitors_data)
        for name, fields in missing_fields.items():
            if name not in competitors_data:
                continue
            batches = [(field, self.search_client.batch_search(
                [f"{name} {term}" for term in self._field_search_terms(field)])) for field in fields]
            prepared = self._prepare_field_repair(name, competitors_data[name], fields, batches)
            if not config.ENABLE_LLM or not (prepared[3].strip() or prepared[2]):
                continue
            result, reason = self.ask_llm_json_with_reason(prepared[0], max_tokens=8192, temperature=0)
            updated[name] = self._commit_field_repair(name, competitors_data[name], fields, prepared, result, reason)
        return updated

    async def async_supplement_missing_fields(self, product_name: str,
                                              competitors_data: dict[str, CompetitorData],
                                              missing_fields: dict[str, list[str]]) -> dict[str, CompetitorData]:
        """Async equivalent of the same transactional supplement contract."""
        self._repair_outcomes = []
        updated = deepcopy(competitors_data)
        for name, fields in missing_fields.items():
            if name not in competitors_data:
                continue
            batches = []
            for field in fields:
                queries = [f"{name} {term}" for term in self._field_search_terms(field)]
                batches.append((field, await self.search_client.async_batch_search(queries)))
            prepared = self._prepare_field_repair(name, competitors_data[name], fields, batches)
            if not config.ENABLE_LLM or not (prepared[3].strip() or prepared[2]):
                continue
            result, reason = await self.async_ask_llm_json_with_reason(prepared[0], max_tokens=8192, temperature=0)
            updated[name] = self._commit_field_repair(name, competitors_data[name], fields, prepared, result, reason)
        return updated
