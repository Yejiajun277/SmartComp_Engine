# -*- coding: utf-8 -*-
"""
agents/collection_agent.py - 结构化证据采集 Agent
"""

from __future__ import annotations

import re
from collections import defaultdict

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
                return str(value)
        return trimmed[:400]

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
                    confidence=0.7 if url else 0.4,
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
        return CompetitorData(
            name=competitor,
            product_features=topic_map.get("product_features", empty_bundle).summary,
            pricing_info=topic_map.get("pricing_info", empty_bundle).summary,
            market_share=topic_map.get("market_share", empty_bundle).summary,
            user_reviews=topic_map.get("user_reviews", empty_bundle).summary,
            strengths=self._extract_strengths(merged_text),
            weaknesses=self._extract_weaknesses(merged_text),
            channels=topic_map.get("channels", empty_bundle).summary,
            search_sources=sources,
            research_evidence=evidence_items,
        )

    @staticmethod
    def _extract_strengths(text: str) -> str:
        parts = re.findall(r"[^。.!?]*(?:领先|优势|强|好评|增长|集成|自动化)[^。.!?]*", text)
        return "；".join(parts[:4])[:400]

    @staticmethod
    def _extract_weaknesses(text: str) -> str:
        parts = re.findall(r"[^。.!?]*(?:不足|问题|投诉|昂贵|复杂|弱|限制)[^。.!?]*", text)
        return "；".join(parts[:4])[:400]
