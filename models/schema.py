# -*- coding: utf-8 -*-
"""Strict schemas for agent-to-agent messages and competitive knowledge payloads."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from models.domain import now_iso, to_dict


class StrictSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class RelevanceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AgentRole(str, Enum):
    DiscoveryAgent = "DiscoveryAgent"
    ResearchPlannerAgent = "ResearchPlannerAgent"
    CollectionAgent = "CollectionAgent"
    ProductAgent = "ProductAgent"
    PricingAgent = "PricingAgent"
    MarketAgent = "MarketAgent"
    QualityAgent = "QualityAgent"
    StrategyAgent = "StrategyAgent"
    Orchestrator = "Orchestrator"
    SchemaValidator = "SchemaValidator"


class PayloadType(str, Enum):
    COMPETITOR_LIST = "competitor_list"
    RESEARCH_TASKS = "research_tasks"
    RESEARCH_COVERAGE = "research_coverage"
    RESEARCH_EVIDENCE = "research_evidence"
    EVIDENCE_BUNDLES = "evidence_bundles"
    COMPETITORS_DATA = "competitors_data"
    PRODUCT_ANALYSIS = "product_analysis"
    PRICING_ANALYSIS = "pricing_analysis"
    MARKET_ANALYSIS = "market_analysis"
    QA_ISSUES = "qa_issues"
    QA_RESULT = "qa_result"
    STRATEGY_REPORT = "strategy_report"
    VALIDATION_ERROR = "validation_error"


class CitationSchema(StrictSchema):
    id: StrictStr = Field(min_length=1)
    title: StrictStr = ""
    url: StrictStr = ""
    snippet: StrictStr = ""
    source_type: StrictStr = "web"
    source_quality: Literal["official", "media", "community", "complaint", "aggregator", "low_quality"] = "aggregator"
    collected_at: StrictStr = Field(default_factory=now_iso)
    confidence: StrictFloat = Field(default=0.6, ge=0.0, le=1.0)


class CompetitorInfoSchema(StrictSchema):
    name: StrictStr = Field(min_length=1)
    brief: StrictStr = ""
    relevance: RelevanceLevel = RelevanceLevel.HIGH


class CompetitorListSchema(StrictSchema):
    product_name: StrictStr = Field(min_length=1)
    product_category: StrictStr = ""
    competitors: list[CompetitorInfoSchema] = Field(min_length=1)
    search_keywords_used: list[StrictStr] = Field(default_factory=list)


class ResearchTaskSchema(StrictSchema):
    id: StrictStr = Field(min_length=1)
    competitor: StrictStr = Field(min_length=1)
    topic: StrictStr = Field(min_length=1)
    query: StrictStr = Field(min_length=1)
    priority: Priority = Priority.P1
    retry_count: StrictInt = Field(default=0, ge=0)


class ResearchEvidenceSchema(StrictSchema):
    competitor: StrictStr = Field(min_length=1)
    topic: StrictStr = Field(min_length=1)
    summary: StrictStr = ""
    source_urls: list[StrictStr] = Field(default_factory=list)
    raw_text: StrictStr = ""
    citations: list[CitationSchema] = Field(default_factory=list)
    error: StrictStr = ""


class CoverageGapSchema(StrictSchema):
    competitor: StrictStr = Field(min_length=1)
    topic: StrictStr = Field(min_length=1)
    reason: StrictStr = Field(min_length=1)


class ResearchCoverageSchema(StrictSchema):
    required_topics: list[StrictStr] = Field(default_factory=list)
    completed_topics: dict[StrictStr, list[StrictStr]] = Field(default_factory=dict)
    failed_tasks: list[dict[StrictStr, StrictStr]] = Field(default_factory=list)
    coverage_gaps: list[CoverageGapSchema] = Field(default_factory=list)


class EvidenceBundleSchema(StrictSchema):
    competitor: StrictStr = Field(min_length=1)
    topic: StrictStr = Field(min_length=1)
    summary: StrictStr = ""
    citations: list[CitationSchema] = Field(default_factory=list)
    raw_text: StrictStr = ""
    key_facts: list[StrictStr] = Field(default_factory=list)
    evidence_quotes: list[StrictStr] = Field(default_factory=list)
    source_quality: Literal["official", "media", "community", "complaint", "aggregator", "low_quality"] = "aggregator"
    coverage_status: Literal["complete", "partial", "failed"] = "complete"
    extracted_at: StrictStr = Field(default_factory=now_iso)
    task_id: StrictStr = ""


class CompetitorDataSchema(StrictSchema):
    name: StrictStr = Field(min_length=1)
    product_features: StrictStr = ""
    pricing_info: StrictStr = ""
    market_share: StrictStr = ""
    user_reviews: StrictStr = ""
    evidence_digest: StrictStr = ""
    evidence_quality_notes: StrictStr = ""
    unresolved_conflicts: StrictStr = ""
    product_strengths: StrictStr = ""
    channel_strengths: StrictStr = ""
    reputation_strengths: StrictStr = ""
    product_weaknesses: StrictStr = ""
    reputation_weaknesses: StrictStr = ""
    strengths: StrictStr = ""
    weaknesses: StrictStr = ""
    channels: StrictStr = ""
    search_sources: list[StrictStr] = Field(default_factory=list)
    research_evidence: list[ResearchEvidenceSchema] = Field(default_factory=list)


class FeatureNodeSchema(StrictSchema):
    name: StrictStr = Field(min_length=1)
    description: StrictStr = ""
    supported_competitors: list[StrictStr] = Field(default_factory=list)
    children: list["FeatureNodeSchema"] = Field(default_factory=list)


class FeatureComparisonSchema(StrictSchema):
    feature: StrictStr = Field(min_length=1)
    values: dict[StrictStr, StrictStr] = Field(min_length=1)
    citations: list[StrictStr] = Field(default_factory=list)
    competitor_citations: dict[StrictStr, list[StrictStr]] = Field(default_factory=dict)


class CompetitiveAdvantageSchema(StrictSchema):
    competitor: StrictStr = Field(min_length=1)
    our_advantage: StrictStr = ""
    their_advantage: StrictStr = ""
    their_strength: StrictStr = ""
    their_weakness: StrictStr = ""
    recommended_countermove: StrictStr = ""
    citations: list[StrictStr] = Field(default_factory=list)


class PricingModelSchema(StrictSchema):
    competitor: StrictStr = Field(min_length=1)
    model: StrictStr = Field(min_length=1)
    free_tier: StrictStr = ""
    paid_tier: StrictStr = ""
    billing_basis: StrictStr = ""
    entry_offer: StrictStr = ""
    upgrade_trigger: StrictStr = ""
    pricing_signal: StrictStr = ""
    pricing_risk: StrictStr = ""
    citations: list[StrictStr] = Field(default_factory=list)


class PricingItemSchema(StrictSchema):
    competitor: StrictStr = Field(min_length=1)
    free_tier: StrictStr = ""
    paid_tier: StrictStr = ""
    pricing_model: StrictStr = Field(min_length=1)
    entry_offer: StrictStr = ""
    upgrade_trigger: StrictStr = ""
    billing_unit: StrictStr = ""
    pricing_signal: StrictStr = ""
    pricing_risk: StrictStr = ""
    citations: list[StrictStr] = Field(default_factory=list)


class MarketShareItemSchema(StrictSchema):
    competitor: StrictStr = Field(min_length=1)
    share_estimate: StrictStr = Field(min_length=1)
    trend: StrictStr = ""
    market_position: StrictStr = ""
    growth_signal: StrictStr = ""
    channel_motion: StrictStr = ""
    citations: list[StrictStr] = Field(default_factory=list)


class UserReputationSchema(StrictSchema):
    score: StrictStr = ""
    keywords: list[StrictStr] = Field(default_factory=list)
    highlights: list[StrictStr] = Field(default_factory=list)
    risks: list[StrictStr] = Field(default_factory=list)
    citations: list[StrictStr] = Field(default_factory=list)


class UserPersonaSchema(StrictSchema):
    name: StrictStr = Field(min_length=1)
    segment: StrictStr = Field(min_length=1)
    needs: list[StrictStr] = Field(min_length=1)
    complaints: list[StrictStr] = Field(default_factory=list)
    preferred_channels: list[StrictStr] = Field(default_factory=list)
    persona_summary: StrictStr = Field(min_length=1)
    citations: list[StrictStr] = Field(default_factory=list)


class ConclusionItemSchema(StrictSchema):
    id: StrictStr = Field(min_length=1)
    dimension: Literal["product", "pricing", "market", "strategy"]
    statement: StrictStr = Field(min_length=1)
    citations: list[StrictStr] = Field(default_factory=list)
    confidence: StrictFloat = Field(default=0.6, ge=0.0, le=1.0)
    evidence_topics: list[StrictStr] = Field(default_factory=list)


class ProductAnalysisSchema(StrictSchema):
    feature_matrix: list[FeatureComparisonSchema] = Field(min_length=1)
    competitive_advantages: list[CompetitiveAdvantageSchema] = Field(default_factory=list)
    differentiation_points: list[StrictStr] = Field(default_factory=list)
    feature_tree: list[FeatureNodeSchema] = Field(min_length=1)
    conclusions: list[ConclusionItemSchema] = Field(min_length=1)
    citations: list[CitationSchema] = Field(default_factory=list)
    summary: StrictStr = Field(min_length=1)


class PricingAnalysisSchema(StrictSchema):
    pricing_comparison: list[PricingItemSchema] = Field(min_length=1)
    pricing_strategy_analysis: StrictStr = Field(min_length=1)
    value_ranking: list[StrictStr] = Field(default_factory=list)
    pricing_models: list[PricingModelSchema] = Field(min_length=1)
    conclusions: list[ConclusionItemSchema] = Field(min_length=1)
    citations: list[CitationSchema] = Field(default_factory=list)
    summary: StrictStr = Field(min_length=1)


class MarketAnalysisSchema(StrictSchema):
    market_share_data: list[MarketShareItemSchema] = Field(min_length=1)
    growth_trends: StrictStr = Field(min_length=1)
    user_reputation: dict[StrictStr, UserReputationSchema] = Field(default_factory=dict)
    channel_analysis: StrictStr = Field(min_length=1)
    user_personas: list[UserPersonaSchema] = Field(min_length=1)
    conclusions: list[ConclusionItemSchema] = Field(min_length=1)
    citations: list[CitationSchema] = Field(default_factory=list)
    summary: StrictStr = Field(min_length=1)


class QAIssueSchema(StrictSchema):
    issue_type: StrictStr = Field(min_length=1)
    severity: Literal["high", "medium", "low"]
    target_agent: AgentRole
    reason: StrictStr = Field(min_length=1)
    required_fix: StrictStr = Field(min_length=1)
    related_ids: list[StrictStr] = Field(default_factory=list)


class QAResultSchema(StrictSchema):
    issues: list[QAIssueSchema] = Field(default_factory=list)
    next_action: Literal["redo_collection", "redo_analysis", "pass"]


class ActionItemSchema(StrictSchema):
    priority: Priority
    action: StrictStr = Field(min_length=1)
    timeline: StrictStr = ""
    expected_impact: StrictStr = ""
    citations: list[StrictStr] = Field(default_factory=list)


class StrategyReportSchema(StrictSchema):
    product_name: StrictStr = Field(min_length=1)
    competitor_count: StrictInt = Field(ge=0)
    overall_positioning: StrictStr = ""
    differentiation_strategy: dict[StrictStr, Any] = Field(default_factory=dict)
    action_plan: list[ActionItemSchema] = Field(default_factory=list)
    risk_assessment: StrictStr = ""
    product_analysis_summary: StrictStr = ""
    pricing_analysis_summary: StrictStr = ""
    market_analysis_summary: StrictStr = ""
    coverage_gaps: list[CoverageGapSchema] = Field(default_factory=list)
    qa_issues: list[QAIssueSchema] = Field(default_factory=list)
    citations: list[CitationSchema] = Field(default_factory=list)
    summary: StrictStr = ""
    status: Literal["success", "degraded", "empty", "failed"] = "success"
    run_id: StrictStr = ""
    raw_llm_logs: list[dict[StrictStr, Any]] = Field(default_factory=list)


class ValidationErrorPayloadSchema(StrictSchema):
    target_payload_type: PayloadType
    errors: list[dict[StrictStr, Any]] = Field(min_length=1)
    retryable: bool = True


class ResearchTasksPayload(RootModel[list[ResearchTaskSchema]]):
    pass


class ResearchEvidencePayload(RootModel[dict[StrictStr, list[ResearchEvidenceSchema]]]):
    pass


class EvidenceBundlesPayload(RootModel[dict[StrictStr, list[EvidenceBundleSchema]]]):
    pass


class CompetitorsDataPayload(RootModel[dict[StrictStr, CompetitorDataSchema]]):
    pass


class QAIssuesPayload(RootModel[list[QAIssueSchema]]):
    pass


PAYLOAD_SCHEMA_REGISTRY: dict[PayloadType, type[BaseModel]] = {
    PayloadType.COMPETITOR_LIST: CompetitorListSchema,
    PayloadType.RESEARCH_TASKS: ResearchTasksPayload,
    PayloadType.RESEARCH_COVERAGE: ResearchCoverageSchema,
    PayloadType.RESEARCH_EVIDENCE: ResearchEvidencePayload,
    PayloadType.EVIDENCE_BUNDLES: EvidenceBundlesPayload,
    PayloadType.COMPETITORS_DATA: CompetitorsDataPayload,
    PayloadType.PRODUCT_ANALYSIS: ProductAnalysisSchema,
    PayloadType.PRICING_ANALYSIS: PricingAnalysisSchema,
    PayloadType.MARKET_ANALYSIS: MarketAnalysisSchema,
    PayloadType.QA_ISSUES: QAIssuesPayload,
    PayloadType.QA_RESULT: QAResultSchema,
    PayloadType.STRATEGY_REPORT: StrategyReportSchema,
    PayloadType.VALIDATION_ERROR: ValidationErrorPayloadSchema,
}


def _payload_adapter(payload_type: PayloadType | str) -> TypeAdapter[Any]:
    normalized = PayloadType(payload_type)
    schema = PAYLOAD_SCHEMA_REGISTRY[normalized]
    return TypeAdapter(schema)


def validate_payload(payload_type: PayloadType | str, payload: Any) -> Any:
    """Validate and return the strict payload object for a payload type."""
    return _payload_adapter(payload_type).validate_python(payload)


def dump_payload(payload_type: PayloadType | str, payload: Any) -> Any:
    """Validate and return a JSON-serializable payload."""
    validated = validate_payload(payload_type, payload)
    if isinstance(validated, RootModel):
        return validated.model_dump(mode="json")
    return validated.model_dump(mode="json")


def domain_payload(payload: Any) -> Any:
    """Convert legacy dataclass payloads into strict-schema input payloads."""
    return _strip_legacy_message(to_dict(payload))


def _strip_legacy_message(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_legacy_message(item)
            for key, item in value.items()
            if key != "message"
        }
    if isinstance(value, list):
        return [_strip_legacy_message(item) for item in value]
    return value


class AgentMessageSchema(StrictSchema):
    message_id: StrictStr = Field(default_factory=lambda: uuid4().hex, min_length=1)
    run_id: StrictStr = Field(min_length=1)
    sender: AgentRole
    receiver: AgentRole
    payload_type: PayloadType
    schema_version: Literal["v1"] = "v1"
    retry_count: StrictInt = Field(default=0, ge=0)
    payload: Any
    citations: list[StrictStr] = Field(default_factory=list)
    quality_flags: list[StrictStr] = Field(default_factory=list)
    created_at: StrictStr = Field(default_factory=now_iso)

    @field_validator("payload")
    @classmethod
    def payload_must_not_be_plain_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            raise ValueError("payload must be a schema object, not plain text")
        return value

    @model_validator(mode="after")
    def payload_must_match_type(self) -> "AgentMessageSchema":
        object.__setattr__(self, "payload", dump_payload(self.payload_type, self.payload))
        return self


def build_agent_message(
    *,
    run_id: str,
    sender: AgentRole | str,
    receiver: AgentRole | str,
    payload_type: PayloadType | str,
    payload: Any,
    retry_count: int = 0,
    citations: list[str] | None = None,
    quality_flags: list[str] | None = None,
) -> AgentMessageSchema:
    """Create a validated agent message; raises ValidationError on schema drift."""
    return AgentMessageSchema(
        run_id=run_id,
        sender=sender,
        receiver=receiver,
        payload_type=payload_type,
        retry_count=retry_count,
        payload=payload,
        citations=citations or [],
        quality_flags=quality_flags or [],
    )


def build_agent_message_from_domain(
    *,
    run_id: str,
    sender: AgentRole | str,
    receiver: AgentRole | str,
    payload_type: PayloadType | str,
    payload: Any,
    retry_count: int = 0,
    citations: list[str] | None = None,
    quality_flags: list[str] | None = None,
) -> AgentMessageSchema:
    return build_agent_message(
        run_id=run_id,
        sender=sender,
        receiver=receiver,
        payload_type=payload_type,
        payload=domain_payload(payload),
        retry_count=retry_count,
        citations=citations,
        quality_flags=quality_flags,
    )


def validate_agent_message(message: Any) -> AgentMessageSchema:
    return AgentMessageSchema.model_validate(message)
