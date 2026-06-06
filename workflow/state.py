# -*- coding: utf-8 -*-
"""State definitions for the LangGraph orchestration layer."""

from typing import Annotated, Literal, TypedDict

from models.domain import (
    CompetitorData,
    CompetitorList,
    DimensionConfig,
    MarketAnalysis,
    PricingAnalysis,
    ProductAnalysis,
    QualityCheckResult,
    StrategyReport,
)


RunStatus = Literal[
    "running",
    "stopped_no_competitors",
    "completed",
    "completed_degraded",
    "failed",
]


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """LangGraph reducer for dictionary state fields."""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def keep_latest(left, right):
    """LangGraph reducer for branch outputs where the newest value wins."""
    return right if right is not None else left


class AnalysisState(TypedDict, total=False):
    """Serializable business state passed between graph nodes."""

    product_description: str
    max_competitors: int
    fail_on_quality_exhausted: bool

    status: RunStatus
    error: str
    failure: Annotated[dict, merge_dicts]
    run_dir: str
    timings: Annotated[dict[str, float], merge_dicts]
    started_perf_counter: float
    parallel_started_perf_counter: float
    qa_started_perf_counter: float

    product_name: str
    competitor_list: CompetitorList
    target_product_data: CompetitorData
    competitors_data: dict[str, CompetitorData]
    original_search_texts: dict[str, str]
    dimension_config: DimensionConfig
    product_sub_dims_text: str
    pricing_sub_dims_text: str
    degradation_warning: str

    product_analysis: Annotated[ProductAnalysis, keep_latest]
    pricing_analysis: Annotated[PricingAnalysis, keep_latest]
    market_analysis: Annotated[MarketAnalysis, keep_latest]

    report: StrategyReport
    raw_llm_logs: list[dict]

    qa_collection: QualityCheckResult
    qa_product: Annotated[QualityCheckResult, keep_latest]
    qa_pricing: Annotated[QualityCheckResult, keep_latest]
    qa_market: Annotated[QualityCheckResult, keep_latest]
    qa_strategy: QualityCheckResult
    qa_checks: list[QualityCheckResult]

    collection_feedback: str
    product_feedback: str
    pricing_feedback: str
    market_feedback: str
    strategy_feedback: str
    latest_feedback: str

    collection_retry_count: int
    product_retry_count: int
    pricing_retry_count: int
    market_retry_count: int
    strategy_retry_count: int

    quality_exhausted: Annotated[dict[str, bool], merge_dicts]


def initial_analysis_state(
    product_description: str,
    max_competitors: int,
    *,
    fail_on_quality_exhausted: bool = True,
) -> AnalysisState:
    """Create the initial state for a graph run."""
    return {
        "product_description": product_description,
        "max_competitors": max_competitors,
        "fail_on_quality_exhausted": fail_on_quality_exhausted,
        "status": "running",
        "error": "",
        "failure": {},
        "timings": {},
        "qa_checks": [],
        "collection_feedback": "",
        "product_feedback": "",
        "pricing_feedback": "",
        "market_feedback": "",
        "strategy_feedback": "",
        "latest_feedback": "",
        "collection_retry_count": 0,
        "product_retry_count": 0,
        "pricing_retry_count": 0,
        "market_retry_count": 0,
        "strategy_retry_count": 0,
        "quality_exhausted": {},
    }
