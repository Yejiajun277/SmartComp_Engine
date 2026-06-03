# -*- coding: utf-8 -*-
"""
models/domain.py - 竞品分析领域模型
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RelevanceLevel(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Priority(Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass
class Citation:
    id: str
    title: str = ""
    url: str = ""
    snippet: str = ""
    source_type: str = "web"
    source_quality: str = "aggregator"
    collected_at: str = field(default_factory=now_iso)
    confidence: float = 0.6


@dataclass
class CompetitorInfo:
    name: str
    brief: str = ""
    relevance: str = RelevanceLevel.HIGH.value


@dataclass
class CompetitorList:
    product_name: str
    product_category: str = ""
    competitors: list[CompetitorInfo] = field(default_factory=list)
    search_keywords_used: list[str] = field(default_factory=list)


@dataclass
class ResearchTask:
    id: str
    competitor: str
    topic: str
    query: str
    priority: str = Priority.P1.value
    retry_count: int = 0


@dataclass
class ResearchEvidence:
    competitor: str
    topic: str
    summary: str = ""
    source_urls: list[str] = field(default_factory=list)
    raw_text: str = ""
    citations: list[Citation] = field(default_factory=list)
    error: str = ""


@dataclass
class CoverageGap:
    competitor: str
    topic: str
    reason: str


@dataclass
class ResearchCoverage:
    required_topics: list[str] = field(default_factory=list)
    completed_topics: dict[str, list[str]] = field(default_factory=dict)
    failed_tasks: list[dict[str, str]] = field(default_factory=list)
    coverage_gaps: list[CoverageGap] = field(default_factory=list)


@dataclass
class EvidenceBundle:
    competitor: str
    topic: str
    summary: str = ""
    citations: list[Citation] = field(default_factory=list)
    raw_text: str = ""
    key_facts: list[str] = field(default_factory=list)
    evidence_quotes: list[str] = field(default_factory=list)
    source_quality: str = "aggregator"
    coverage_status: str = "complete"
    extracted_at: str = field(default_factory=now_iso)
    task_id: str = ""


@dataclass
class CompetitorData:
    name: str
    product_features: str = ""
    pricing_info: str = ""
    market_share: str = ""
    user_reviews: str = ""
    evidence_digest: str = ""
    evidence_quality_notes: str = ""
    unresolved_conflicts: str = ""
    product_strengths: str = ""
    channel_strengths: str = ""
    reputation_strengths: str = ""
    product_weaknesses: str = ""
    reputation_weaknesses: str = ""
    strengths: str = ""
    weaknesses: str = ""
    channels: str = ""
    search_sources: list[str] = field(default_factory=list)
    research_evidence: list[ResearchEvidence] = field(default_factory=list)


@dataclass
class FeatureNode:
    name: str
    description: str = ""
    supported_competitors: list[str] = field(default_factory=list)
    children: list["FeatureNode"] = field(default_factory=list)


@dataclass
class FeatureComparison:
    feature: str
    values: dict[str, str] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)
    competitor_citations: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class CompetitiveAdvantage:
    competitor: str
    our_advantage: str = ""
    their_advantage: str = ""
    their_strength: str = ""
    their_weakness: str = ""
    recommended_countermove: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class PricingModel:
    competitor: str
    model: str = ""
    free_tier: str = ""
    paid_tier: str = ""
    billing_basis: str = ""
    entry_offer: str = ""
    upgrade_trigger: str = ""
    pricing_signal: str = ""
    pricing_risk: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class PricingItem:
    competitor: str
    free_tier: str = ""
    paid_tier: str = ""
    pricing_model: str = ""
    entry_offer: str = ""
    upgrade_trigger: str = ""
    billing_unit: str = ""
    pricing_signal: str = ""
    pricing_risk: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class MarketShareItem:
    competitor: str
    share_estimate: str = ""
    trend: str = ""
    market_position: str = ""
    growth_signal: str = ""
    channel_motion: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class UserReputation:
    score: str = ""
    keywords: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


@dataclass
class UserPersona:
    name: str
    segment: str = ""
    needs: list[str] = field(default_factory=list)
    complaints: list[str] = field(default_factory=list)
    preferred_channels: list[str] = field(default_factory=list)
    persona_summary: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class ConclusionItem:
    id: str
    dimension: str
    statement: str
    citations: list[str] = field(default_factory=list)
    confidence: float = 0.6
    evidence_topics: list[str] = field(default_factory=list)


@dataclass
class MessageEnvelope:
    task_id: str
    agent_role: str
    payload_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    retry_count: int = 0


@dataclass
class AnalysisBundle:
    dimension: str
    findings: list[ConclusionItem] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.6
    message: MessageEnvelope | None = None


@dataclass
class ProductAnalysis:
    feature_matrix: list[FeatureComparison] = field(default_factory=list)
    competitive_advantages: list[CompetitiveAdvantage] = field(default_factory=list)
    differentiation_points: list[str] = field(default_factory=list)
    feature_tree: list[FeatureNode] = field(default_factory=list)
    conclusions: list[ConclusionItem] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    message: MessageEnvelope | None = None
    summary: str = ""


@dataclass
class PricingAnalysis:
    pricing_comparison: list[PricingItem] = field(default_factory=list)
    pricing_strategy_analysis: str = ""
    value_ranking: list[str] = field(default_factory=list)
    pricing_models: list[PricingModel] = field(default_factory=list)
    conclusions: list[ConclusionItem] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    message: MessageEnvelope | None = None
    summary: str = ""


@dataclass
class MarketAnalysis:
    market_share_data: list[MarketShareItem] = field(default_factory=list)
    growth_trends: str = ""
    user_reputation: dict[str, UserReputation] = field(default_factory=dict)
    channel_analysis: str = ""
    user_personas: list[UserPersona] = field(default_factory=list)
    conclusions: list[ConclusionItem] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    message: MessageEnvelope | None = None
    summary: str = ""


@dataclass
class QAIssue:
    issue_type: str
    severity: str
    target_agent: str
    reason: str
    required_fix: str
    related_ids: list[str] = field(default_factory=list)


@dataclass
class ActionItem:
    priority: str
    action: str
    timeline: str = ""
    expected_impact: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class TraceEvent:
    node: str
    status: str
    started_at: str
    ended_at: str
    latency_seconds: float
    prompt: str = ""
    input_summary: str = ""
    output_summary: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)
    error: str = ""
    decision: str = ""
    version: str = "v2"


@dataclass
class StrategyReport:
    product_name: str
    competitor_count: int = 0
    overall_positioning: str = ""
    differentiation_strategy: dict[str, Any] = field(default_factory=dict)
    action_plan: list[ActionItem] = field(default_factory=list)
    risk_assessment: str = ""
    product_analysis_summary: str = ""
    pricing_analysis_summary: str = ""
    market_analysis_summary: str = ""
    coverage_gaps: list[CoverageGap] = field(default_factory=list)
    qa_issues: list[QAIssue] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    summary: str = ""
    status: str = "success"
    run_id: str = ""
    raw_llm_logs: list[dict[str, Any]] = field(default_factory=list)


def to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_dict(item) for key, item in value.items()}
    return value
