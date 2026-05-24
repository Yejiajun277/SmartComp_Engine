from __future__ import annotations

from typing import Annotated, Any, TypedDict

try:
    from langchain_core.messages import AnyMessage
except ImportError:  # pragma: no cover - 测试环境兼容
    AnyMessage = Any

try:
    from langgraph.graph.message import add_messages
except ImportError:  # pragma: no cover - 测试环境兼容
    def add_messages(left, right):
        return (left or []) + (right or [])

from models.domain import StrategyReport


class PlatformAssistantState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    run_id: str
    status: str
    product_description: str
    max_competitors: int
    focus_topics: list[str]
    use_llm: bool
    should_ask_for_input: bool
    report: StrategyReport | None
    report_paths: dict[str, str]
    trace_summary: dict[str, Any]
    timings: dict[str, float]
    logs: list[dict[str, Any]]
