# -*- coding: utf-8 -*-
"""Market evidence projection with entity-local sources and bounded recovery."""
from dataclasses import asdict
import json
import re

from agents.base_agent import BaseAgent
from models.domain import CompetitorData, MarketAnalysis, MarketShareItem, UserReputation, UserProfile
from core.prompt_loader import load as load_prompts
import config


class MarketAgent(BaseAgent):
    """Select source bindings; numerical conclusions remain saved collection facts."""

    _SOURCE_FIELDS = {"market_share", "user_reviews", "channels"}

    def __init__(self):
        prompts = load_prompts("market_agent")
        super().__init__(agent_id="MarketAgent", system_prompt=prompts["system_prompt"])
        self._prompt_analyze = prompts["prompt_analyze"]

    @staticmethod
    def _entities(product_name, competitors_data, target_product_data=None):
        entities = {}
        if target_product_data is not None:
            if product_name in competitors_data:
                raise ValueError("Target and rival identities must be distinct")
            entities[product_name] = target_product_data
        entities.update(competitors_data)
        return entities

    @staticmethod
    def _source_catalog(name, data):
        return {cite.id: cite for cite in data.citations if cite.id and cite.snippet.strip()
                and cite.competitor in ("", name, data.name)}

    def _build_competitors_text(self, product_name: str, competitors_data: dict[str, CompetitorData],
                                target_product_data: CompetitorData | None = None) -> str:
        """Keep full fields and source metadata; do not duplicate raw search_sources."""
        records = {}
        for name, data in self._entities(product_name, competitors_data, target_product_data).items():
            records[name] = asdict(data)
            records[name].pop("search_sources", None)
        return json.dumps(records, ensure_ascii=False, indent=2)

    @classmethod
    def _valid_selection(cls, result, entities):
        if not isinstance(result, dict) or not isinstance(result.get("entity_sources"), dict):
            return False
        if set(result["entity_sources"]) != set(entities):
            return False
        for name, fields in result["entity_sources"].items():
            if (not isinstance(name, str) or not isinstance(fields, dict)
                    or set(fields) != cls._SOURCE_FIELDS):
                return False
            catalog = cls._source_catalog(name, entities[name])
            for field, refs in fields.items():
                if field not in cls._SOURCE_FIELDS or not isinstance(refs, list) or any(
                        not isinstance(cid, str) or cid not in catalog for cid in refs):
                    return False
        return True

    async def _request_selection(self, product_name, competitors_data, target_product_data, feedback):
        text = self._build_competitors_text(product_name, competitors_data, target_product_data)
        if feedback:
            text += "\n\n### 完整质检反馈（不是事实来源）\n" + feedback
        prompt = self._prompt_analyze.format(product_name=product_name, competitors_text=text)
        log_count = len(self.llm_logs)
        result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=8192)
        response = self.llm_logs[-1] if len(self.llm_logs) > log_count else {}
        complete = (not truncated and response.get("finish_reason") == "stop"
                    and response.get("success") is True and not response.get("parse_error")
                    and self._valid_selection(result, self._entities(
                        product_name, competitors_data, target_product_data)))
        # Parseable length/content-filter responses are not completed selections.
        return (result, False) if complete else ({}, True)

    async def run(self, product_name: str, competitors_data: dict[str, CompetitorData],
                  target_product_data: CompetitorData | None = None, feedback: str = "") -> MarketAnalysis:
        self._log("📈 开始市场事实与来源核对...")
        if config.ENABLE_LLM:
            result, incomplete = await self._request_selection(
                product_name, competitors_data, target_product_data, feedback)
            if incomplete and len(competitors_data) >= 2:
                return await self._run_chunked(product_name, competitors_data, target_product_data, feedback)
            if result:
                analysis = self._parse_market_analysis(result, product_name, competitors_data, target_product_data)
                return self._mark_source_review(analysis, dict.fromkeys(
                    self._entities(product_name, competitors_data, target_product_data), True))
            analysis = self._parse_market_analysis({}, product_name, competitors_data, target_product_data)
            return self._mark_source_review(analysis, dict.fromkeys(
                self._entities(product_name, competitors_data, target_product_data), False))
        return self._rule_analyze(product_name, competitors_data, target_product_data)

    @staticmethod
    def _mark_source_review(analysis, states):
        """Persist a readable evidence gap; transient states serve nested merges."""
        finished = [name for name, value in states.items() if value is True]
        unfinished = [name for name, value in states.items() if value is False]
        unrequested = [name for name, value in states.items() if value is None]
        if unfinished:
            note = "来源对应核对未完成：" + "、".join(unfinished) + "。"
            if finished:
                note += "已完成：" + "、".join(finished) + "。"
            note += "未完成部分仅保留已采集原文供复核。"
        elif unrequested:
            note = "尚未进行来源对应核对；以下仅保留已采集原文供复核。"
        else:
            note = "来源对应核对已完成；原采集事实及其限制仍逐项保留。"
        analysis.summary = note + "\n" + analysis.summary
        analysis._source_review_states = dict(states)
        return analysis

    async def _run_chunked(self, product_name: str, competitors_data: dict[str, CompetitorData],
                           target_product_data: CompetitorData | None, feedback: str) -> MarketAnalysis:
        """At most 2*N-1 requests including the initial call; failed leaves retain facts."""
        names = list(competitors_data)
        if len(names) < 2:
            analysis = self._parse_market_analysis({}, product_name, competitors_data, target_product_data)
            return self._mark_source_review(analysis, dict.fromkeys(
                self._entities(product_name, competitors_data, target_product_data), False))
        analyses = []
        mid = len(names) // 2
        for subset in (names[:mid], names[mid:]):
            chunk = {name: competitors_data[name] for name in subset}
            result, incomplete = await self._request_selection(product_name, chunk, target_product_data, feedback)
            if incomplete and len(chunk) >= 2:
                analysis = await self._run_chunked(product_name, chunk, target_product_data, feedback)
            else:
                analysis = self._parse_market_analysis(result, product_name, chunk, target_product_data)
                self._mark_source_review(analysis, dict.fromkeys(
                    self._entities(product_name, chunk, target_product_data), not incomplete))
            analyses.append(analysis)
        merged = self._parse_market_analysis({}, product_name, competitors_data, target_product_data)
        # Rebuild from the full immutable map, then merge only checked source
        # IDs. Target duplication and chunk-generated statistics cannot survive.
        for row in merged.market_share_data:
            row.citations = list(dict.fromkeys(cid for analysis in analyses
                for part in analysis.market_share_data if part.competitor == row.competitor for cid in part.citations))
        for name, reputation in merged.user_reputation.items():
            reputation.citations = list(dict.fromkeys(cid for analysis in analyses
                if name in analysis.user_reputation for cid in analysis.user_reputation[name].citations))
        merged.citations = list(dict.fromkeys([*merged.citations,
            *(cid for analysis in analyses for cid in analysis.citations)]))
        states = dict.fromkeys(self._entities(product_name, competitors_data, target_product_data), False)
        for analysis in analyses:
            for name, completed in analysis._source_review_states.items():
                # The target snapshot is identical in every branch: one real
                # completed source review suffices; a failed sibling cannot
                # discard that completed review or claim an unchecked rival.
                states[name] = states[name] or completed
        return self._mark_source_review(merged, states)

    @staticmethod
    def _normalize_trend(trend) -> str:
        """No default stability and no direction inferred from a substring/negation."""
        return {"上升": "上升", "增长": "上升", "下降": "下降", "稳定": "稳定"}.get(
            trend.strip() if isinstance(trend, str) else "", "未知")

    @staticmethod
    def _literal(text):
        return re.sub(r"\s+", "", text)

    @classmethod
    def _rating_evidence(cls, name, data):
        """Retain a source-bound native rating; never synthesize a unified score.

        The whole saved statement, not just a matching numeral, must occur in
        one entity-owned snippet. A translated/paraphrased statement that cannot
        be bound this way remains fully visible in source_text; unknown here
        does not mean the underlying source has no rating.
        """
        text = data.user_reviews
        if not re.search(r"评分|評分|星级|星級|\brating\b|\brated\b|\bscore\b", text, re.I):
            return "未知", []
        if re.search(r"(?:未(?:披露|提供|公开)?|没有|无|no\s+(?:public\s+)?)\s*(?:评分|評分|rating|score)", text, re.I):
            return "未知", []
        if re.search(r"估计|估算|推测|推算|预测|假设|模拟|estimated|assumed|predicted|synthetic|hypothetical", text, re.I):
            return "未知", []
        ratings = []
        for match in re.finditer(r"(?<![\d./])(\d+(?:\.\d+)?)\s*(?:/|out\s+of)\s*(\d+(?:\.\d+)?)(?![\d./])", text, re.I):
            value, scale = map(float, match.groups())
            if scale in (5, 10, 100) and 0 <= value <= scale:
                ratings.append(match.group(0))
        if len(ratings) != 1:
            return "未知", []
        normalized = cls._literal(text)
        refs = [cid for cid, cite in cls._source_catalog(name, data).items()
                if normalized and normalized in cls._literal(cite.snippet)]
        return (ratings[0], refs) if refs else ("未知", [])

    def _parse_market_analysis(self, result: dict, product_name: str = "",
                               competitors_data: dict[str, CompetitorData] | None = None,
                               target_product_data: CompetitorData | None = None) -> MarketAnalysis:
        """Project authoritative saved fields; model output supplies source IDs only."""
        entities = self._entities(product_name, competitors_data or {}, target_product_data)
        selections = result.get("entity_sources", {}) if isinstance(result, dict) else {}
        selections = selections if isinstance(selections, dict) else {}
        analysis = MarketAnalysis()
        all_refs = []
        for name, data in entities.items():
            catalog = self._source_catalog(name, data)
            selected = selections.get(name, {})
            selected = selected if isinstance(selected, dict) else {}

            def refs(field):
                values = selected.get(field, [])
                values = values if isinstance(values, list) else []
                return list(dict.fromkeys(cid for cid in values if isinstance(cid, str) and cid in catalog))

            share_refs = refs("market_share")
            analysis.market_share_data.append(MarketShareItem(name, data.market_share or "未知", "未知", share_refs))
            score, score_refs = self._rating_evidence(name, data)
            review_refs = list(dict.fromkeys([*score_refs, *refs("user_reviews")]))
            analysis.user_reputation[name] = UserReputation(score=score, citations=review_refs, source_text=data.user_reviews)
            # No separately collected demographic/trend facts exist in the
            # current schema. Do not turn review/spec text into ages, occupations,
            # user proportions, growth, or default stability.
            analysis.user_profiles[name] = UserProfile(target_audience="未知", age_range="未知")
            all_refs.extend([*share_refs, *review_refs, *refs("channels")])
        analysis.growth_trends = "未合并不同主体、年份或统计口径；趋势未知。\n" + "\n".join(
            f"{name}｜采集市场记录：{data.market_share or '未知'}" for name, data in entities.items())
        analysis.channel_analysis = "\n".join(f"{name}｜{data.channels or '未知'}" for name, data in entities.items())
        analysis.summary = "按实体保留采集原文与适用范围，不估算缺失的份额、评分或人群统计。\n" + "\n".join(
            f"{row.competitor}｜市场记录：{row.share_estimate}；趋势：未知；可直接绑定评分：{analysis.user_reputation[row.competitor].score}"
            for row in analysis.market_share_data)
        analysis.citations = list(dict.fromkeys(all_refs))
        return analysis

    def _rule_analyze(self, product_name: str, competitors_data: dict[str, CompetitorData],
                       target_product_data: CompetitorData | None = None) -> MarketAnalysis:
        analysis = self._parse_market_analysis({}, product_name, competitors_data, target_product_data)
        return self._mark_source_review(analysis, dict.fromkeys(
            self._entities(product_name, competitors_data, target_product_data), None))
