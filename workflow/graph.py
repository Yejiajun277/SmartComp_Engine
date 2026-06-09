# -*- coding: utf-8 -*-
"""LangGraph StateGraph construction for the analysis workflow."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

import config
from agents.quality_agent import QualityAgent
from workflow.nodes import AnalysisGraphNodes
from workflow.state import AnalysisState, initial_analysis_state


def route_after_discovery(state: AnalysisState) -> str:
    competitors = state.get("competitor_list")
    if not competitors or not competitors.competitors:
        return "no_competitors"
    return "has_competitors"


def route_collection_quality(state: AnalysisState) -> str:
    result = state.get("qa_collection")
    if result and result.passed:
        return "passed"
    if state.get("collection_retry_count", 0) < QualityAgent.MAX_RETRIES:
        return "retry"
    return "exhausted"


def route_after_collection_retry(state: AnalysisState) -> str:
    if state.get("collection_supplemented"):
        return "recheck"
    return "recollect"


def route_after_collection_degraded(state: AnalysisState) -> str:
    competitors = state.get("competitor_list")
    competitors_data = state.get("competitors_data") or {}
    target_data = state.get("target_product_data")
    if competitors and competitors.competitors and competitors_data and target_data:
        return "continue_degraded"
    return "hard_failure"


def route_analysis_quality(state: AnalysisState) -> str:
    for analysis_type in ("product", "pricing", "market"):
        result = state.get(f"qa_{analysis_type}")
        if result and not result.passed:
            if state.get(f"{analysis_type}_retry_count", 0) < QualityAgent.MAX_RETRIES:
                return f"retry_{analysis_type}"
            return "exhausted"
    if all(state.get(f"qa_{analysis_type}") for analysis_type in ("product", "pricing", "market")):
        return "passed"
    return "exhausted"


def route_strategy_quality(state: AnalysisState) -> str:
    result = state.get("qa_strategy")
    if result and result.passed:
        return "passed"
    if state.get("strategy_retry_count", 0) < QualityAgent.MAX_RETRIES:
        return "retry"
    return "exhausted"


def build_analysis_graph(orchestrator, *, node_retries: int = 2):
    """Build and compile the LangGraph workflow.

    The graph uses fixed edges for the happy path and conditional edges for
    QA pass/retry/exhausted routing.
    """
    nodes = AnalysisGraphNodes(orchestrator, node_retries=node_retries)
    graph = StateGraph(AnalysisState)

    graph.add_node("initialize_run", nodes.initialize_run)
    graph.add_node("discover_competitors", nodes.discover_competitors)
    graph.add_node("finalize_no_competitors", nodes.finalize_no_competitors)
    graph.add_node("collect_target_product", nodes.collect_target_product)
    graph.add_node("collect_competitors", nodes.collect_competitors)
    graph.add_node("check_collection_quality", nodes.check_collection_quality)
    graph.add_node("prepare_collection_retry", nodes.prepare_collection_retry)
    graph.add_node("mark_collection_degraded", nodes.mark_collection_degraded)
    graph.add_node("generate_dimensions", nodes.generate_dimensions)
    graph.add_node("build_degradation_warning", nodes.build_degradation_warning)
    graph.add_node("run_product_analysis", nodes.run_product_analysis)
    graph.add_node("run_pricing_analysis", nodes.run_pricing_analysis)
    graph.add_node("run_market_analysis", nodes.run_market_analysis)
    graph.add_node("rerun_product_analysis", nodes.run_product_analysis)
    graph.add_node("rerun_pricing_analysis", nodes.run_pricing_analysis)
    graph.add_node("rerun_market_analysis", nodes.run_market_analysis)
    graph.add_node("join_parallel_analysis", nodes.join_parallel_analysis)
    graph.add_node("check_product_quality", nodes.check_product_quality)
    graph.add_node("check_pricing_quality", nodes.check_pricing_quality)
    graph.add_node("check_market_quality", nodes.check_market_quality)
    graph.add_node("join_analysis_quality", nodes.join_analysis_quality)
    graph.add_node("prepare_product_retry", nodes.prepare_product_retry)
    graph.add_node("prepare_pricing_retry", nodes.prepare_pricing_retry)
    graph.add_node("prepare_market_retry", nodes.prepare_market_retry)
    graph.add_node("mark_analysis_degraded", nodes.mark_analysis_degraded)
    graph.add_node("generate_strategy", nodes.generate_strategy)
    graph.add_node("check_strategy_quality", nodes.check_strategy_quality)
    graph.add_node("prepare_strategy_retry", nodes.prepare_strategy_retry)
    graph.add_node("mark_strategy_degraded", nodes.mark_strategy_degraded)
    graph.add_node("finalize_report", nodes.finalize_report)
    graph.add_node("fail_run", nodes.fail_run)

    graph.add_edge(START, "initialize_run")
    graph.add_edge("initialize_run", "discover_competitors")
    graph.add_conditional_edges(
        "discover_competitors",
        route_after_discovery,
        {
            "no_competitors": "finalize_no_competitors",
            "has_competitors": "collect_target_product",
        },
    )
    graph.add_edge("finalize_no_competitors", END)

    graph.add_edge("collect_target_product", "collect_competitors")
    graph.add_edge("collect_competitors", "check_collection_quality")
    graph.add_conditional_edges(
        "check_collection_quality",
        route_collection_quality,
        {
            "passed": "generate_dimensions",
            "retry": "prepare_collection_retry",
            "exhausted": "mark_collection_degraded",
        },
    )
    graph.add_conditional_edges(
        "prepare_collection_retry",
        route_after_collection_retry,
        {
            "recheck": "check_collection_quality",
            "recollect": "collect_competitors",
        },
    )
    graph.add_conditional_edges(
        "mark_collection_degraded",
        route_after_collection_degraded,
        {
            "continue_degraded": "generate_dimensions",
            "hard_failure": "fail_run",
        },
    )

    graph.add_edge("generate_dimensions", "build_degradation_warning")
    graph.add_edge("build_degradation_warning", "run_product_analysis")
    graph.add_edge("build_degradation_warning", "run_pricing_analysis")
    graph.add_edge("build_degradation_warning", "run_market_analysis")
    graph.add_edge("run_product_analysis", "join_parallel_analysis")
    graph.add_edge("run_pricing_analysis", "join_parallel_analysis")
    graph.add_edge("run_market_analysis", "join_parallel_analysis")

    graph.add_edge("join_parallel_analysis", "check_product_quality")
    graph.add_edge("join_parallel_analysis", "check_pricing_quality")
    graph.add_edge("join_parallel_analysis", "check_market_quality")
    graph.add_edge("check_product_quality", "join_analysis_quality")
    graph.add_edge("check_pricing_quality", "join_analysis_quality")
    graph.add_edge("check_market_quality", "join_analysis_quality")
    graph.add_conditional_edges(
        "join_analysis_quality",
        route_analysis_quality,
        {
            "passed": "generate_strategy",
            "retry_product": "prepare_product_retry",
            "retry_pricing": "prepare_pricing_retry",
            "retry_market": "prepare_market_retry",
            "exhausted": "mark_analysis_degraded",
        },
    )
    graph.add_edge("prepare_product_retry", "rerun_product_analysis")
    graph.add_edge("rerun_product_analysis", "check_product_quality")
    graph.add_edge("prepare_pricing_retry", "rerun_pricing_analysis")
    graph.add_edge("rerun_pricing_analysis", "check_pricing_quality")
    graph.add_edge("prepare_market_retry", "rerun_market_analysis")
    graph.add_edge("rerun_market_analysis", "check_market_quality")
    graph.add_edge("mark_analysis_degraded", "generate_strategy")

    graph.add_edge("generate_strategy", "check_strategy_quality")
    graph.add_conditional_edges(
        "check_strategy_quality",
        route_strategy_quality,
        {
            "passed": "finalize_report",
            "retry": "prepare_strategy_retry",
            "exhausted": "mark_strategy_degraded",
        },
    )
    graph.add_edge("prepare_strategy_retry", "generate_strategy")
    graph.add_edge("mark_strategy_degraded", "finalize_report")
    graph.add_edge("finalize_report", END)
    graph.add_edge("fail_run", END)

    return graph.compile()


def export_graph_mermaid(node_retries: int = 2) -> str:
    """导出 LangGraph DAG 为 Mermaid 格式（可嵌入 Markdown 或渲染为图片）。

    使用方式：
      1. 直接嵌入 README.md: ```mermaid\\n{output}\\n```
      2. 用 mermaid-cli 渲染: mmdc -i graph.mmd -o graph.png
    """
    # 构建一个轻量 graph 只用于导出（不执行）
    from unittest.mock import MagicMock
    mock_orch = MagicMock()
    graph = build_analysis_graph(mock_orch, node_retries=node_retries)
    compiled = graph

    # LangGraph 内置 Mermaid 导出
    try:
        mermaid_str = compiled.get_graph().draw_mermaid()
        return mermaid_str
    except Exception:
        # 降级：手动生成 Mermaid
        return _manual_mermaid_fallback()


def _manual_mermaid_fallback() -> str:
    """手动生成 DAG 的 Mermaid 表示（降级方案）。"""
    lines = [
        "graph TD",
        "    START([START]) --> initialize_run",
        "    initialize_run --> discover_competitors",
        "    discover_competitors -->|有竞品| collect_target_product",
        "    discover_competitors -->|无竞品| finalize_no_competitors --> END2([END])",
        "    collect_target_product --> collect_competitors",
        "    collect_competitors --> check_collection_quality",
        "    check_collection_quality -->|通过| generate_dimensions",
        "    check_collection_quality -->|重试| prepare_collection_retry",
        "    check_collection_quality -->|耗尽| mark_collection_degraded",
        "    prepare_collection_retry -->|补充数据| check_collection_quality",
        "    prepare_collection_retry -->|重新采集| collect_competitors",
        "    mark_collection_degraded -->|继续降级| generate_dimensions",
        "    mark_collection_degraded -->|严重失败| fail_run --> END3([END])",
        "    generate_dimensions --> build_degradation_warning",
        "    build_degradation_warning --> run_product_analysis",
        "    build_degradation_warning --> run_pricing_analysis",
        "    build_degradation_warning --> run_market_analysis",
        "    run_product_analysis --> join_parallel_analysis",
        "    run_pricing_analysis --> join_parallel_analysis",
        "    run_market_analysis --> join_parallel_analysis",
        "    join_parallel_analysis --> check_product_quality",
        "    join_parallel_analysis --> check_pricing_quality",
        "    join_parallel_analysis --> check_market_quality",
        "    check_product_quality --> join_analysis_quality",
        "    check_pricing_quality --> join_analysis_quality",
        "    check_market_quality --> join_analysis_quality",
        "    join_analysis_quality -->|通过| generate_strategy",
        "    join_analysis_quality -->|产品重试| prepare_product_retry",
        "    join_analysis_quality -->|定价重试| prepare_pricing_retry",
        "    join_analysis_quality -->|市场重试| prepare_market_retry",
        "    join_analysis_quality -->|耗尽| mark_analysis_degraded",
        "    prepare_product_retry --> rerun_product_analysis --> check_product_quality",
        "    prepare_pricing_retry --> rerun_pricing_analysis --> check_pricing_quality",
        "    prepare_market_retry --> rerun_market_analysis --> check_market_quality",
        "    mark_analysis_degraded --> generate_strategy",
        "    generate_strategy --> check_strategy_quality",
        "    check_strategy_quality -->|通过| finalize_report --> END4([END])",
        "    check_strategy_quality -->|重试| prepare_strategy_retry",
        "    check_strategy_quality -->|耗尽| mark_strategy_degraded",
        "    prepare_strategy_retry --> generate_strategy",
        "    mark_strategy_degraded --> finalize_report",
    ]
    return "\n".join(lines)


def save_graph_visualization(artifact_store, node_retries: int = 2):
    """将 DAG 可视化保存到 artifact_store。

    保存文件：
      - workflow_dag.mmd: Mermaid 源文件
      - workflow_dag.md: 可直接嵌入 README 的 Mermaid 代码块
    """
    mermaid_str = export_graph_mermaid(node_retries=node_retries)

    # 保存原始 Mermaid 文件
    artifact_store.save_text("workflow_dag.mmd", mermaid_str)

    # 保存为可嵌入 README 的格式
    md_content = f"## 工作流 DAG\n\n```mermaid\n{mermaid_str}\n```\n"
    artifact_store.save_text("workflow_dag.md", md_content)

    return mermaid_str


async def run_analysis_graph(
    orchestrator,
    product_description: str,
    max_competitors: int = config.DEFAULT_COMPETITOR_COUNT,
    *,
    fail_on_quality_exhausted: bool = True,
    node_retries: int = 2,
) -> AnalysisState:
    """Run the compiled analysis graph and return the final state."""
    graph = build_analysis_graph(orchestrator, node_retries=node_retries)
    state = initial_analysis_state(
        product_description,
        max_competitors,
        fail_on_quality_exhausted=fail_on_quality_exhausted,
    )
    return await graph.ainvoke(state)
