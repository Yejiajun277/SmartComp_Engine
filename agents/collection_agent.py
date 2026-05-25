# -*- coding: utf-8 -*-
"""
agents/collection_agent.py - 结构化证据采集 Agent
"""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlparse

import config
from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from core.search_client import SearchClient
from models.domain import (
    Citation,
    CompetitorData,
    CoverageGap,
    EvidenceBundle,
    ResearchCoverage,
    ResearchEvidence,
    ResearchTask,
)


TOPIC_FIELD_MAP = {
    "product_features": "product_features",
    "pricing_info": "pricing_info",
    "market_share": "market_share",
    "user_reviews": "user_reviews",
    "channels": "channels",
}


class CollectionAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("collection_agent")
        super().__init__(
            agent_id="CollectionAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_collect = prompts["prompt_collect"]
        self.search_client = SearchClient()

    async def run(
        self,
        product_description: str,
        tasks: list[ResearchTask],
        retry_count: int = 0,
    ) -> dict:
        grouped_bundles: dict[str, list[EvidenceBundle]] = defaultdict(list)
        grouped_evidence: dict[str, list[ResearchEvidence]] = defaultdict(list)
        coverage = ResearchCoverage(required_topics=sorted({task.topic for task in tasks}))

        for task in tasks:
            evidence, bundle = self._collect_task(product_description, task, retry_count)
            grouped_evidence[task.competitor].append(evidence)
            grouped_bundles[task.competitor].append(bundle)
            if bundle.coverage_status == "complete":
                coverage.completed_topics.setdefault(task.competitor, []).append(task.topic)
            else:
                coverage.failed_tasks.append(
                    {
                        "competitor": task.competitor,
                        "topic": task.topic,
                        "query": task.query,
                        "error": evidence.error or "evidence_incomplete",
                    }
                )
                coverage.coverage_gaps.append(
                    CoverageGap(
                        competitor=task.competitor,
                        topic=task.topic,
                        reason=evidence.error or "missing_or_weak_evidence",
                    )
                )

        competitors_data = {
            competitor: self._build_competitor_data(competitor, bundles, grouped_evidence[competitor])
            for competitor, bundles in grouped_bundles.items()
        }
        self._log(f"完成证据采集，竞品数={len(competitors_data)}")
        return {
            "competitors_data": competitors_data,
            "research_evidence": dict(grouped_evidence),
            "research_coverage": coverage,
            "evidence_bundles": dict(grouped_bundles),
        }

    def _collect_task(
        self,
        product_description: str,
        task: ResearchTask,
        retry_count: int,
    ) -> tuple[ResearchEvidence, EvidenceBundle]:
        last_error = ""
        result = None
        for _ in range(2):
            try:
                result = self.search_client.search(task.query)
                break
            except Exception as exc:  # pragma: no cover
                last_error = str(exc)

        text = SearchClient.extract_text(result) if result else ""
        refs = SearchClient.extract_references(result) if result else []
        citations = self._build_citations(task, refs)
        summary = self._summarize_task(product_description, task, text)
        key_facts = self._extract_key_facts(summary, text)
        evidence_quotes = self._extract_evidence_quotes(citations)
        source_quality = self._pick_source_quality(citations)
        coverage_status = "complete" if text and citations else "partial"
        error = "" if coverage_status == "complete" else (last_error or "citation_missing")

        evidence = ResearchEvidence(
            competitor=task.competitor,
            topic=task.topic,
            summary=summary,
            source_urls=[citation.url for citation in citations if citation.url],
            raw_text=text[:1500],
            citations=citations,
            error=error,
        )
        bundle = EvidenceBundle(
            competitor=task.competitor,
            topic=task.topic,
            summary=summary,
            citations=citations,
            raw_text=text[:2000],
            key_facts=key_facts,
            evidence_quotes=evidence_quotes,
            source_quality=source_quality,
            coverage_status=coverage_status,
            task_id=task.id,
        )
        return evidence, bundle

    def _summarize_task(self, product_description: str, task: ResearchTask, text: str) -> str:
        trimmed = text[:5000]
        if not trimmed:
            return ""
        if config.ENABLE_LLM:
            prompt = self._prompt_collect.format(
                product_name=product_description,
                product_description=product_description,
                competitor_name=task.competitor,
                search_results=trimmed,
            )
            parsed = self.ask_llm_json(prompt, max_tokens=2048)
            value = parsed.get(TOPIC_FIELD_MAP.get(task.topic, ""), "")
            if value:
                return self._compact_summary(str(value))
        return self._fallback_summary(trimmed)

    @staticmethod
    def _build_citations(task: ResearchTask, refs: list[dict]) -> list[Citation]:
        citations: list[Citation] = []
        for index, item in enumerate(refs[:6], start=1):
            url = str(item.get("url", "")).strip()
            title = str(item.get("title", "")).strip() or f"{task.competitor}-{task.topic}-{index}"
            snippet = str(
                item.get("summary")
                or item.get("content")
                or item.get("snippet")
                or ""
            ).strip()
            citations.append(
                Citation(
                    id=f"{task.id}:citation:{index}",
                    title=title,
                    url=url,
                    snippet=snippet[:280],
                    source_quality=CollectionAgent._infer_source_quality(url, title),
                    confidence=0.82 if CollectionAgent._infer_source_quality(url, title) == "official" else 0.68 if url else 0.4,
                )
            )
        return citations

    def _build_competitor_data(
        self,
        competitor: str,
        bundles: list[EvidenceBundle],
        evidence_items: list[ResearchEvidence],
    ) -> CompetitorData:
        topic_map = {bundle.topic: bundle for bundle in bundles}
        merged_text = " ".join(bundle.summary for bundle in bundles if bundle.summary)
        sources = [citation.url for bundle in bundles for citation in bundle.citations if citation.url]
        empty_bundle = EvidenceBundle(competitor=competitor, topic="")
        strengths = self._extract_competitor_strengths(bundles)
        weaknesses = self._extract_competitor_weaknesses(bundles)
        return CompetitorData(
            name=competitor,
            product_features=topic_map.get("product_features", empty_bundle).summary,
            pricing_info=topic_map.get("pricing_info", empty_bundle).summary,
            market_share=topic_map.get("market_share", empty_bundle).summary,
            user_reviews=topic_map.get("user_reviews", empty_bundle).summary,
            strengths=strengths or self._extract_strengths(merged_text),
            weaknesses=weaknesses or self._extract_weaknesses(merged_text),
            channels=topic_map.get("channels", empty_bundle).summary,
            search_sources=sources,
            research_evidence=evidence_items,
        )

    @staticmethod
    def _compact_summary(text: str) -> str:
        sentences = CollectionAgent._split_sentences(text)
        picked: list[str] = []
        seen: set[str] = set()
        for sentence in sentences:
            normalized = sentence.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            if normalized.startswith(("信息来源", "可引用来源", "http", "来源：", "参考资料")):
                continue
            seen.add(lowered)
            picked.append(CollectionAgent._trim_sentence(normalized))
            if len(picked) >= 4:
                break
        return " ".join(picked)

    @staticmethod
    def _fallback_summary(text: str) -> str:
        cleaned = re.sub(r"#+\s*", "", text or "")
        cleaned = re.sub(r"可引用来源[:：].*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"信息来源[:：].*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        return CollectionAgent._compact_summary(cleaned)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        raw_parts = re.split(r"[\n\r]+|[。！？!?；;]+", text or "")
        return [part.strip(" -•\t") for part in raw_parts if part.strip(" -•\t")]

    @staticmethod
    def _trim_sentence(text: str, max_len: int = 72) -> str:
        compact = re.sub(r"\s+", " ", text).strip(" -•\t")
        if len(compact) <= max_len:
            return compact
        cut = compact[:max_len].rstrip("，,；;：:")
        return f"{cut}..."

    def _extract_key_facts(self, summary: str, raw_text: str) -> list[str]:
        preferred = self._split_sentences(summary)
        if len(preferred) < 3:
            preferred.extend(self._split_sentences(raw_text[:1200]))
        facts: list[str] = []
        for sentence in preferred:
            cleaned = self._trim_sentence(sentence, 86)
            if len(cleaned) < 8:
                continue
            if cleaned not in facts:
                facts.append(cleaned)
            if len(facts) >= 5:
                break
        return facts

    @staticmethod
    def _extract_evidence_quotes(citations: list[Citation]) -> list[str]:
        quotes: list[str] = []
        for citation in citations:
            snippet = CollectionAgent._trim_sentence(citation.snippet, 88)
            if snippet and snippet not in quotes:
                quotes.append(snippet)
            if len(quotes) >= 3:
                break
        return quotes

    @staticmethod
    def _pick_source_quality(citations: list[Citation]) -> str:
        priorities = {"official": 4, "media": 3, "community": 2, "complaint": 1, "aggregator": 0}
        ranked = sorted(
            (citation.source_quality for citation in citations),
            key=lambda item: priorities.get(item, 0),
            reverse=True,
        )
        return ranked[0] if ranked else "aggregator"

    @staticmethod
    def _infer_source_quality(url: str, title: str) -> str:
        host = urlparse(url).netloc.lower()
        title_lower = (title or "").lower()
        if any(token in host for token in ("feishu.cn", "larksuite.com", "weixin.qq.com", "dingtalk.com", "qq.com")):
            return "official"
        if any(token in host for token in ("gov.cn", "edu.cn")):
            return "official"
        if any(token in host for token in ("36kr.com", "iyiou.com", "caixin.com", "guancha.cn", "chinanews.com")):
            return "media"
        if any(token in host for token in ("sohu.com", "163.com", "sina.com", "ifeng.com", "docin.com", "csdn.net")):
            return "aggregator"
        if any(token in host for token in ("zhihu.com", "xiaohongshu.com", "weibo.com")):
            return "community"
        if any(token in host for token in ("315", "tousu", "heimao", "blackcat")) or "投诉" in title_lower:
            return "complaint"
        if host:
            return "media"
        return "aggregator"

    def _extract_competitor_strengths(self, bundles: list[EvidenceBundle]) -> str:
        candidates: list[str] = []
        for bundle in bundles:
            for fact in bundle.key_facts:
                if any(token in fact for token in ("领先", "增长", "支持", "接入", "覆盖", "开放", "协同", "自动化", "ai")):
                    candidates.append(fact)
        return "；".join(candidates[:2])[:120]

    def _extract_competitor_weaknesses(self, bundles: list[EvidenceBundle]) -> str:
        candidates: list[str] = []
        for bundle in bundles:
            for fact in bundle.key_facts + bundle.evidence_quotes:
                if any(token in fact for token in ("复杂", "门槛", "投诉", "退款", "不足", "限制", "成本", "推诿")):
                    candidates.append(fact)
        return "；".join(candidates[:2])[:120]

    @staticmethod
    def _extract_strengths(text: str) -> str:
        parts = re.findall(r"[^。.!?]*(?:领先|优势|强|好评|增长|集成|自动化)[^。.!?]*", text)
        return "；".join(parts[:4])[:400]

    @staticmethod
    def _extract_weaknesses(text: str) -> str:
        parts = re.findall(r"[^。.!?]*(?:不足|问题|投诉|昂贵|复杂|弱|限制)[^。.!?]*", text)
        return "；".join(parts[:4])[:400]
