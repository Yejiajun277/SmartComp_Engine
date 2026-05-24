# -*- coding: utf-8 -*-
"""
core/orchestrator.py - LangGraph 兼容包装层
"""

from __future__ import annotations

import config
from agents.strategy_agent import StrategyAgent
from core.llm_client import get_llm_stats
from models.domain import CompetitorList, ProductAnalysis, StrategyReport
from workflow.graph import run_analysis_graph
from workflow.state import AnalysisState


class Orchestrator:
    """保留原有 Orchestrator 接口，内部转调 LangGraph。"""

    def __init__(self):
        self.strategy_agent = StrategyAgent()
        self.timings: dict[str, float] = {}
        self._last_state: AnalysisState = {}
        self._last_product_analysis = None
        self._last_pricing_analysis = None
        self._last_market_analysis = None
        self._last_competitor_list = None
        self._last_competitors_data = None

    async def analyze(
        self,
        product_description: str,
        max_competitors: int = config.DEFAULT_COMPETITOR_COUNT,
    ) -> StrategyReport:
        state = await run_analysis_graph(
            product_description=product_description,
            max_competitors=max_competitors,
            use_llm=config.ENABLE_LLM,
        )
        self._apply_state(state)

        report = state.get("report")
        if report is None:
            raise ValueError("分析流程未生成 report")
        return report

    def _apply_state(self, state: AnalysisState) -> None:
        self._last_state = state
        self.timings = state.get("timings", {}).copy()
        self._last_product_analysis = state.get("product_analysis")
        self._last_pricing_analysis = state.get("pricing_analysis")
        self._last_market_analysis = state.get("market_analysis")
        self._last_competitor_list = state.get("competitor_list")
        self._last_competitors_data = state.get("competitors_data")

    def get_timings(self) -> dict[str, float]:
        return self.timings.copy()

    def print_stats(self):
        print_analysis_stats(self.timings)


def print_analysis_stats(timings: dict[str, float]):
    print("\n" + "─" * 65)
    print("  分析统计")
    print("─" * 65)
    print("  各阶段耗时:")
    for name, duration in timings.items():
        print(f"    - {name}: {duration:.2f}s")

    if config.ENABLE_LLM:
        stats = get_llm_stats()
        print("\n  LLM调用统计:")
        print(f"    - 总调用: {stats['total']}")
        print(f"    - 成功: {stats['success']}")
        print(f"    - 降级: {stats['fallback']}")
        if stats["total"] > 0:
            rate = stats["success"] / stats["total"] * 100
            print(f"    - 成功率: {rate:.0f}%")


def print_feature_matrix(
    product_name: str,
    product_analysis: ProductAnalysis | None,
    competitor_list: CompetitorList | None,
):
    if product_analysis is None or competitor_list is None:
        return
    if not product_analysis.feature_matrix:
        return

    print("\n\n" + "─" * 65)
    print("  功能对比矩阵")
    print("─" * 65)

    names = [c.name for c in competitor_list.competitors]
    if product_name not in names:
        names.insert(0, product_name)

    header = f"{'功能':<12}"
    for name in names:
        header += f" {name:<12}"
    print(header)
    print("─" * len(header))

    for feature_item in product_analysis.feature_matrix:
        row = f"{feature_item.feature:<12}"
        for name in names:
            row += f" {_find_feature_value(feature_item.values, name, product_name):<12}"
        print(row)


def _find_feature_value(values_dict: dict, target_name: str, product_name: str) -> str:
    if not values_dict:
        return "×"
    if target_name in values_dict:
        return values_dict[target_name]
    for key in values_dict:
        if key.startswith(target_name) and target_name in key:
            return values_dict[key]
    if target_name == product_name:
        for key in values_dict:
            if product_name in key:
                return values_dict[key]
    for key in values_dict:
        if target_name in key or key in target_name:
            return values_dict[key]
    return "×"
