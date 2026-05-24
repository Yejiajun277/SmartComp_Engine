from __future__ import annotations

from typing import TYPE_CHECKING, Any

import config
try:
    from langchain_core.messages import AIMessage, BaseMessage
except ImportError:  # pragma: no cover - 测试环境兼容
    class BaseMessage:  # type: ignore[override]
        type = ""

        def __init__(self, content=""):
            self.content = content

    class AIMessage(BaseMessage):  # type: ignore[override]
        type = "ai"

from workflow.graph import run_analysis_graph
from workflow.platform_state import PlatformAssistantState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph
else:
    CompiledStateGraph = Any


ASK_FOR_INPUT_MESSAGE = "请输入要分析的产品或项目描述，例如：分析飞书，关注定位、定价和市场机会。"


def build_platform_assistant_graph() -> CompiledStateGraph:
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(PlatformAssistantState)
    graph.add_node("parse_user_request", parse_user_request)
    graph.add_node("ask_for_user_input", ask_for_user_input)
    graph.add_node("run_competitive_analysis", run_competitive_analysis)
    graph.add_node("format_assistant_response", format_assistant_response)

    graph.add_edge(START, "parse_user_request")
    graph.add_conditional_edges(
        "parse_user_request",
        route_after_parse_user_request,
        {
            "ask_for_user_input": "ask_for_user_input",
            "run_competitive_analysis": "run_competitive_analysis",
        },
    )
    graph.add_edge("ask_for_user_input", END)
    graph.add_edge("run_competitive_analysis", "format_assistant_response")
    graph.add_edge("format_assistant_response", END)
    return graph.compile()


def parse_user_request(state: PlatformAssistantState) -> dict[str, Any]:
    messages = state.get("messages", [])
    last_user_message = _get_last_user_message(messages)
    product_description = last_user_message or state.get("product_description", "").strip()
    if not product_description:
        return {
            "should_ask_for_input": True,
            "logs": [{"node": "parse_user_request", "status": "waiting_for_input"}],
        }

    return {
        "product_description": product_description,
        "max_competitors": config.DEFAULT_COMPETITOR_COUNT,
        "focus_topics": [],
        "use_llm": True,
        "should_ask_for_input": False,
        "logs": [
            {
                "node": "parse_user_request",
                "status": "success",
                "product_description": product_description,
            }
        ],
    }


def route_after_parse_user_request(state: PlatformAssistantState) -> str:
    if state.get("should_ask_for_input"):
        return "ask_for_user_input"
    return "run_competitive_analysis"


def ask_for_user_input(state: PlatformAssistantState) -> dict[str, Any]:
    return {
        "messages": [AIMessage(content=ASK_FOR_INPUT_MESSAGE)],
        "logs": state.get("logs", []),
    }


async def run_competitive_analysis(state: PlatformAssistantState) -> dict[str, Any]:
    analysis_state = await run_analysis_graph(
        product_description=state["product_description"],
        max_competitors=state.get("max_competitors", config.DEFAULT_COMPETITOR_COUNT),
        use_llm=state.get("use_llm", True),
        focus_topics=state.get("focus_topics", []),
    )
    return {
        "run_id": analysis_state.get("run_id", ""),
        "status": analysis_state.get("status", "success"),
        "report": analysis_state.get("report"),
        "report_paths": analysis_state.get("report_paths", {}),
        "trace_summary": analysis_state.get("trace_summary", {}),
        "timings": analysis_state.get("timings", {}),
        "logs": analysis_state.get("logs", []),
    }


def format_assistant_response(state: PlatformAssistantState) -> dict[str, Any]:
    report = state.get("report")
    if report is None:
        raise ValueError("assistant 入口未生成 report")

    lines = [
        f"分析目标: {report.product_name}",
        f"运行 ID: {state.get('run_id', '')}",
        f"状态: {state.get('status', report.status)}",
        f"竞品数量: {report.competitor_count}",
        f"整体定位: {report.overall_positioning or '暂无'}",
    ]
    if report.action_plan:
        lines.append("行动建议:")
        for item in report.action_plan[:3]:
            lines.append(f"- [{item.priority}] {item.action}")
    if state.get("report_paths", {}).get("html"):
        lines.append(f"HTML输出: {state['report_paths']['html']}")
    if state.get("report_paths", {}).get("json"):
        lines.append(f"JSON输出: {state['report_paths']['json']}")

    return {
        "messages": [AIMessage(content="\n".join(lines))],
        "logs": state.get("logs", []),
        "report_paths": state.get("report_paths", {}),
        "trace_summary": state.get("trace_summary", {}),
        "timings": state.get("timings", {}),
    }


def _get_last_user_message(messages: list[Any]) -> str:
    for message in reversed(messages):
        if _is_user_message(message):
            content = _extract_message_content(message)
            if content:
                return content
    return ""


def _is_user_message(message: Any) -> bool:
    if isinstance(message, BaseMessage):
        return getattr(message, "type", "") == "human"
    if isinstance(message, dict):
        role = str(message.get("role", "")).lower()
        message_type = str(message.get("type", "")).lower()
        return role == "user" or message_type == "human"
    return False


def _extract_message_content(message: Any) -> str:
    if isinstance(message, BaseMessage):
        return _extract_text_content(message.content)
    if isinstance(message, dict):
        return _extract_text_content(message.get("content", ""))
    return ""


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append(text)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content") or ""
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""
