from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from models.domain import (
    CompetitorData,
    CompetitorList,
    EvidenceBundle,
    MarketAnalysis,
    PricingAnalysis,
    ProductAnalysis,
    QAIssue,
    ResearchCoverage,
    ResearchEvidence,
    ResearchTask,
    StrategyReport,
)


class AnalysisState(TypedDict, total=False):
    run_id: str
    status: str
    product_description: str
    max_competitors: int
    focus_topics: list[str]
    use_llm: bool
    run_started_at: float
    qa_round: int
    retry_count: int
    qa_decision: str
    qa_issue_count: int
    competitor_list: CompetitorList | None
    research_tasks: list[ResearchTask]
    research_coverage: ResearchCoverage | None
    research_evidence: dict[str, list[ResearchEvidence]]
    evidence_bundles: dict[str, list[EvidenceBundle]]
    competitors_data: dict[str, CompetitorData]
    product_analysis: ProductAnalysis | None
    pricing_analysis: PricingAnalysis | None
    market_analysis: MarketAnalysis | None
    report: StrategyReport | None
    qa_issues: list[QAIssue]
    report_paths: dict[str, str]
    trace_summary: dict[str, Any]
    timings: dict[str, float]
    timing_records: Annotated[list[dict[str, float | str]], operator.add]
    logs: Annotated[list[dict[str, Any]], operator.add]
    llm_logs: list[dict[str, Any]]
    error: str | None
