from __future__ import annotations

from typing import TYPE_CHECKING, Any

import config
from workflow.nodes import WorkflowNodes, create_workflow_agents
from workflow.state import AnalysisState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph
else:
    CompiledStateGraph = Any


def build_analysis_graph() -> CompiledStateGraph:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时触发
        raise ImportError("未安装 langgraph，请先执行 `pip install -r requirements.txt`。") from exc

    agents = create_workflow_agents()
    nodes = WorkflowNodes(agents)

    graph = StateGraph(AnalysisState)
    graph.add_node("init_context", nodes.init_context)
    graph.add_node("discover_competitors", nodes.discover_competitors)
    graph.add_node("plan_research", nodes.plan_research)
    graph.add_node("collect_competitor_data", nodes.collect_competitor_data)
    graph.add_node("analyze_product", nodes.analyze_product)
    graph.add_node("analyze_pricing", nodes.analyze_pricing)
    graph.add_node("analyze_market", nodes.analyze_market)
    graph.add_node("quality_gate", nodes.quality_gate)
    graph.add_node("redo_analysis", nodes.redo_analysis)
    graph.add_node("build_strategy_report", nodes.build_strategy_report)
    graph.add_node("build_empty_report", nodes.build_empty_report)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "init_context")
    graph.add_edge("init_context", "discover_competitors")
    graph.add_conditional_edges(
        "discover_competitors",
        nodes.route_after_discovery,
        {
            "plan_research": "plan_research",
            "build_empty_report": "build_empty_report",
        },
    )
    graph.add_edge("plan_research", "collect_competitor_data")
    graph.add_edge("collect_competitor_data", "analyze_product")
    graph.add_edge("collect_competitor_data", "analyze_pricing")
    graph.add_edge("collect_competitor_data", "analyze_market")
    graph.add_edge("analyze_product", "quality_gate")
    graph.add_edge("analyze_pricing", "quality_gate")
    graph.add_edge("analyze_market", "quality_gate")
    graph.add_conditional_edges(
        "quality_gate",
        nodes.route_after_quality,
        {
            "plan_research": "plan_research",
            "redo_analysis": "redo_analysis",
            "build_strategy_report": "build_strategy_report",
        },
    )
    graph.add_edge("redo_analysis", "quality_gate")
    graph.add_edge("build_strategy_report", "finalize")
    graph.add_edge("build_empty_report", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


async def run_analysis_graph(
    product_description: str,
    max_competitors: int,
    use_llm: bool,
    focus_topics: list[str] | None = None,
) -> AnalysisState:
    config.ENABLE_LLM = use_llm
    graph = build_analysis_graph()
    state: AnalysisState = {
        "product_description": product_description,
        "max_competitors": max_competitors,
        "focus_topics": focus_topics or [],
        "use_llm": use_llm,
        "competitors_data": {},
        "logs": [],
        "timing_records": [],
    }
    return await graph.ainvoke(state)
