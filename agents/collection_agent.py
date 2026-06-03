# -*- coding: utf-8 -*-
"""
agents/collection_agent.py - 结构化证据采集 Agent
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path
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

PROFILE_FIELDS = (
    "product_strengths",
    "channel_strengths",
    "reputation_strengths",
    "product_weaknesses",
    "reputation_weaknesses",
)

SYNTHESIS_FIELDS = (
    "product_features",
    "pricing_info",
    "market_share",
    "user_reviews",
    "channels",
    "evidence_digest",
    "evidence_quality_notes",
    "unresolved_conflicts",
)

SOURCE_QUALITY_CONFIDENCE = {
    "official": 0.9,
    "media": 0.76,
    "community": 0.58,
    "complaint": 0.45,
    "aggregator": 0.42,
    "low_quality": 0.28,
}

SOURCE_QUALITY_PRIORITY = {
    "official": 5,
    "media": 4,
    "community": 3,
    "complaint": 2,
    "aggregator": 1,
    "low_quality": 0,
}

QUALITY_LEVELS = ("official", "media", "community", "complaint", "aggregator", "low_quality")

OFFICIAL_HOSTS_BY_COMPETITOR = {
    "钉钉": ("dingtalk.com", "ding.cn"),
    "企业微信": ("wecom.tencent.com", "work.weixin.qq.com"),
    "WPS 365": ("wps.cn", "kingsoft.com"),
    "WPS": ("wps.cn", "kingsoft.com"),
    "飞书": ("feishu.cn", "larksuite.com"),
}
WEAKNESS_TOKENS = ("不足", "问题", "投诉", "限制", "复杂", "门槛", "偏贵", "缺少", "不支持", "续航焦虑")


class CollectionAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("collection_agent")
        super().__init__(
            agent_id="CollectionAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_collect = prompts["prompt_collect"]
        self._prompt_profile = prompts["prompt_profile"]
        self._prompt_synthesis = prompts["prompt_synthesis"]
        self.search_client = SearchClient()
        self._source_quality_profiles = self._load_source_quality_profiles()

    async def run(
        self,
        product_description: str,
        tasks: list[ResearchTask],
        retry_count: int = 0,
    ) -> dict:
        grouped_bundles: dict[str, list[EvidenceBundle]] = defaultdict(list)
        grouped_evidence: dict[str, list[ResearchEvidence]] = defaultdict(list)
        coverage = ResearchCoverage(required_topics=sorted({task.topic for task in tasks}))
        concurrency = max(1, config.COLLECTION_MAX_CONCURRENCY)
        semaphore = asyncio.Semaphore(concurrency)

        async def collect(task: ResearchTask) -> tuple[ResearchTask, ResearchEvidence, EvidenceBundle]:
            async with semaphore:
                evidence, bundle = await asyncio.to_thread(
                    self._collect_task,
                    product_description,
                    task,
                    retry_count,
                )
                return task, evidence, bundle

        for task, evidence, bundle in await asyncio.gather(*(collect(task) for task in tasks)):
            grouped_evidence[task.competitor].append(evidence)
            grouped_bundles[task.competitor].append(bundle)
            if bundle.coverage_status == "complete":
                coverage.completed_topics.setdefault(task.competitor, []).append(task.topic)
                continue

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
        if not config.ENABLE_LLM:
            return self._offline_rule_task(product_description, task)

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
        summary = self._summarize_task(product_description, task, text, citations)
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

    @staticmethod
    def _offline_rule_task(
        product_description: str,
        task: ResearchTask,
    ) -> tuple[ResearchEvidence, EvidenceBundle]:
        summary = (
            f"规则模式未联网采集。该任务用于验证流程结构："
            f"{task.competitor} / {task.topic} / {product_description}。"
        )
        evidence = ResearchEvidence(
            competitor=task.competitor,
            topic=task.topic,
            summary=summary,
            raw_text=summary,
            citations=[],
            error="offline_rule_mode",
        )
        bundle = EvidenceBundle(
            competitor=task.competitor,
            topic=task.topic,
            summary=summary,
            raw_text=summary,
            key_facts=[summary],
            evidence_quotes=[],
            source_quality="low_quality",
            coverage_status="partial",
            task_id=task.id,
        )
        return evidence, bundle

    def _summarize_task(
        self,
        product_description: str,
        task: ResearchTask,
        text: str,
        citations: list[Citation],
    ) -> str:
        trimmed = text[:5000]
        if not trimmed:
            return ""
        if config.ENABLE_LLM:
            prompt = self._prompt_collect.format(
                product_name=product_description,
                product_description=product_description,
                competitor_name=task.competitor,
                search_results=trimmed,
                source_quality_context=self._source_quality_context(citations),
            )
            parsed = self.ask_llm_json(prompt, max_tokens=2048)
            value = parsed.get(TOPIC_FIELD_MAP.get(task.topic, ""), "")
            if value:
                return self._compact_summary(str(value))
        return self._fallback_summary(trimmed)

    def _build_citations(
        self,
        task: ResearchTask,
        refs: list[dict],
    ) -> list[Citation]:
        citations: list[Citation] = []
        for index, item in enumerate(refs[:6], start=1):
            url = str(item.get("url", "")).strip()
            title = str(item.get("title", "")).strip() or f"{task.competitor}-{task.topic}-{index}"
            snippet = str(item.get("summary") or item.get("content") or item.get("snippet") or "").strip()
            quality = self._infer_source_quality(url, title, task.competitor)
            citations.append(
                Citation(
                    id=f"{task.id}:citation:{index}",
                    title=title,
                    url=url,
                    snippet=snippet[:280],
                    source_quality=quality,
                    confidence=SOURCE_QUALITY_CONFIDENCE.get(quality, 0.4 if url else 0.2),
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
        sources = [citation.url for bundle in bundles for citation in bundle.citations if citation.url]
        empty_bundle = EvidenceBundle(competitor=competitor, topic="")
        profile = self._summarize_competitor_profile(competitor, topic_map)
        synthesis = self._synthesize_competitor_data(competitor, topic_map)
        product_strengths = profile.get("product_strengths", "")
        channel_strengths = profile.get("channel_strengths", "")
        reputation_strengths = profile.get("reputation_strengths", "")
        product_weaknesses = profile.get("product_weaknesses", "")
        reputation_weaknesses = profile.get("reputation_weaknesses", "")

        return CompetitorData(
            name=competitor,
            product_features=synthesis.get("product_features") or topic_map.get("product_features", empty_bundle).summary,
            pricing_info=synthesis.get("pricing_info") or topic_map.get("pricing_info", empty_bundle).summary,
            market_share=synthesis.get("market_share") or topic_map.get("market_share", empty_bundle).summary,
            user_reviews=synthesis.get("user_reviews") or topic_map.get("user_reviews", empty_bundle).summary,
            evidence_digest=synthesis.get("evidence_digest", ""),
            evidence_quality_notes=synthesis.get("evidence_quality_notes", ""),
            unresolved_conflicts=synthesis.get("unresolved_conflicts", ""),
            product_strengths=product_strengths,
            channel_strengths=channel_strengths,
            reputation_strengths=reputation_strengths,
            product_weaknesses=product_weaknesses,
            reputation_weaknesses=reputation_weaknesses,
            strengths=product_strengths,
            weaknesses=product_weaknesses or reputation_weaknesses,
            channels=synthesis.get("channels") or topic_map.get("channels", empty_bundle).summary,
            search_sources=sources,
            research_evidence=evidence_items,
        )

    def _synthesize_competitor_data(
        self,
        competitor: str,
        topic_map: dict[str, EvidenceBundle],
    ) -> dict[str, str]:
        fallback = {
            "product_features": self._fallback_topic_summary(topic_map.get("product_features")),
            "pricing_info": self._fallback_topic_summary(topic_map.get("pricing_info")),
            "market_share": self._fallback_topic_summary(topic_map.get("market_share")),
            "user_reviews": self._fallback_topic_summary(topic_map.get("user_reviews")),
            "channels": self._fallback_topic_summary(topic_map.get("channels")),
            "evidence_digest": self._fallback_evidence_digest(topic_map),
            "evidence_quality_notes": self._fallback_quality_notes(topic_map),
            "unresolved_conflicts": "",
        }
        if not config.ENABLE_LLM:
            return fallback

        prompt = self._prompt_synthesis.format(
            competitor_name=competitor,
            topic_evidence_text=self._topic_evidence_text(topic_map),
        )
        parsed = self.ask_llm_json(prompt, max_tokens=2200)
        if not parsed:
            return fallback

        result: dict[str, str] = {}
        for field in SYNTHESIS_FIELDS:
            value = str(parsed.get(field, "")).strip()
            result[field] = self._compact_synthesis_field(value, fallback[field])
        return result

    def _summarize_competitor_profile(
        self,
        competitor: str,
        topic_map: dict[str, EvidenceBundle],
    ) -> dict[str, str]:
        fallback = {
            "product_strengths": self._fallback_topic_summary(topic_map.get("product_features")),
            "channel_strengths": self._fallback_topic_summary(topic_map.get("channels")),
            "reputation_strengths": self._fallback_topic_summary(topic_map.get("user_reviews")),
            "product_weaknesses": self._fallback_topic_weakness(topic_map.get("product_features")),
            "reputation_weaknesses": self._fallback_topic_weakness(topic_map.get("user_reviews")),
        }
        if not config.ENABLE_LLM:
            return fallback

        prompt = self._prompt_profile.format(
            competitor_name=competitor,
            product_features_text=self._bundle_profile_text(topic_map.get("product_features")),
            channels_text=self._bundle_profile_text(topic_map.get("channels")),
            user_reviews_text=self._bundle_profile_text(topic_map.get("user_reviews")),
        )
        parsed = self.ask_llm_json(prompt, max_tokens=1200)
        if not parsed:
            return fallback

        return {
            field: self._compact_profile_field(str(parsed.get(field, "")).strip(), fallback=fallback[field])
            for field in PROFILE_FIELDS
        }

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
    def _compact_synthesis_field(text: str, fallback: str = "") -> str:
        sentences = CollectionAgent._split_sentences(text)
        picked: list[str] = []
        for sentence in sentences:
            cleaned = CollectionAgent._trim_sentence(sentence, 120)
            if cleaned and cleaned not in picked:
                picked.append(cleaned)
            if len(picked) >= 5:
                break
        return " ".join(picked) or fallback

    @staticmethod
    def _fallback_summary(text: str) -> str:
        cleaned = re.sub(r"#+\s*", "", text or "")
        cleaned = re.sub(r"可引用来源[:：].*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"信息来源[:：].*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        return CollectionAgent._compact_summary(cleaned)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        raw_parts = re.split(r"[\n\r]+|[。！？；;]+", text or "")
        return [part.strip(" -\t") for part in raw_parts if part.strip(" -\t")]

    @staticmethod
    def _trim_sentence(text: str, max_len: int = 72) -> str:
        compact = re.sub(r"\s+", " ", text).strip(" -\t")
        if len(compact) <= max_len:
            return compact
        cut = compact[:max_len].rstrip("，、；:：")
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
        ranked = sorted(
            (citation.source_quality for citation in citations),
            key=lambda item: SOURCE_QUALITY_PRIORITY.get(item, 0),
            reverse=True,
        )
        return ranked[0] if ranked else "aggregator"

    def _infer_source_quality(self, url: str, title: str, competitor: str = "") -> str:
        host = urlparse(url).netloc.lower()
        title_lower = (title or "").lower()
        default_profile = self._source_quality_profiles.get("default", {})

        if self._is_competitor_official_host(host, competitor):
            if any(token in host for token in ("forum.", "bbs.", "community", "blog.")):
                return "community"
            return "official"

        for quality in ("low_quality", "complaint", "community", "aggregator", "media"):
            tokens = default_profile.get(quality) or []
            if self._match_host_tokens(host, tokens):
                return quality

        if any(token in host for token in ("gov.cn", "edu.cn")):
            return "media"
        if any(token in host for token in ("zhihu.com", "xiaohongshu.com", "weibo.com", "reddit.com")):
            return "community"
        if any(token in host for token in ("315", "tousu", "heimao", "blackcat")) or "投诉" in title_lower:
            return "complaint"
        if any(token in host for token in ("sina.com", "sina.cn", "sohu.com", "163.com", "ifeng.com", "docin.com", "csdn.net")):
            return "aggregator"
        if host:
            return "media"
        return "aggregator"

    @staticmethod
    def _match_host_tokens(host: str, tokens: list[str]) -> bool:
        return any(token and token in host for token in tokens)

    @staticmethod
    def _is_competitor_official_host(host: str, competitor: str) -> bool:
        for name, tokens in OFFICIAL_HOSTS_BY_COMPETITOR.items():
            if name in competitor:
                return any(token in host for token in tokens)
        return False

    @staticmethod
    def _load_source_quality_profiles() -> dict[str, dict[str, list[str]]]:
        file_path = Path(__file__).resolve().parents[1] / "source_quality_profiles.json"
        if not file_path.is_file():
            return {}
        with file_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def _bundle_profile_text(bundle: EvidenceBundle | None) -> str:
        if not bundle:
            return ""
        facts = "；".join(bundle.key_facts[:3])
        quotes = "；".join(bundle.evidence_quotes[:2])
        parts = [bundle.summary, facts, quotes]
        return "\n".join(part for part in parts if part)

    def _fallback_topic_summary(self, bundle: EvidenceBundle | None) -> str:
        if not bundle:
            return ""
        candidates = bundle.key_facts + self._split_sentences(bundle.summary)
        for sentence in candidates:
            cleaned = self._compact_profile_field(sentence)
            if cleaned:
                return cleaned
        return ""

    def _fallback_topic_weakness(self, bundle: EvidenceBundle | None) -> str:
        if not bundle:
            return ""
        candidates = bundle.key_facts + bundle.evidence_quotes + self._split_sentences(bundle.summary)
        for sentence in candidates:
            lowered = sentence.lower()
            if any(token in sentence or token in lowered for token in WEAKNESS_TOKENS):
                cleaned = self._compact_profile_field(sentence)
                if cleaned:
                    return cleaned
        return ""

    def _compact_profile_field(self, text: str, fallback: str = "") -> str:
        cleaned = self._trim_sentence((text or "").strip(), 80)
        if not cleaned:
            return fallback
        if cleaned in {"暂无数据", "待验证"}:
            return cleaned
        return cleaned

    @staticmethod
    def _source_quality_context(citations: list[Citation]) -> str:
        if not citations:
            return "无可用来源。"
        lines = []
        for citation in citations[:6]:
            lines.append(
                f"- [{citation.id}] quality={citation.source_quality}, confidence={citation.confidence:.2f}, "
                f"title={citation.title}, snippet={citation.snippet[:120]}"
            )
        return "\n".join(lines)

    @staticmethod
    def _topic_evidence_text(topic_map: dict[str, EvidenceBundle]) -> str:
        lines: list[str] = []
        for topic in TOPIC_FIELD_MAP:
            bundle = topic_map.get(topic)
            if not bundle:
                lines.append(f"## {topic}\n暂无数据")
                continue
            lines.append(f"## {topic}")
            lines.append(f"summary: {bundle.summary}")
            if bundle.key_facts:
                lines.append("key_facts: " + "；".join(bundle.key_facts[:5]))
            if bundle.evidence_quotes:
                lines.append("quotes: " + "；".join(bundle.evidence_quotes[:3]))
            source_lines = [
                f"[{citation.id}] {citation.source_quality}/{citation.confidence:.2f} {citation.title}: {citation.snippet[:160]}"
                for citation in bundle.citations[:5]
            ]
            if source_lines:
                lines.append("sources:\n" + "\n".join(source_lines))
        return "\n".join(lines)[:9000]

    def _fallback_evidence_digest(self, topic_map: dict[str, EvidenceBundle]) -> str:
        parts = []
        for topic in TOPIC_FIELD_MAP:
            summary = self._fallback_topic_summary(topic_map.get(topic))
            if summary:
                parts.append(f"{topic}: {summary}")
        return " ".join(parts)

    @staticmethod
    def _fallback_quality_notes(topic_map: dict[str, EvidenceBundle]) -> str:
        qualities = []
        for topic, bundle in topic_map.items():
            if bundle:
                qualities.append(f"{topic}={bundle.source_quality}")
        return "；".join(qualities)
