# -*- coding: utf-8 -*-
"""Node wrappers for the future LangGraph StateGraph.

The wrappers call the existing agents and Orchestrator helpers without changing
business behavior. They are intentionally framework-light so they can be unit
tested before the graph is introduced.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, is_dataclass
from typing import Awaitable, Callable, TypeVar

from agents.quality_agent import QualityAgent
import config
from models.domain import (
    MarketAnalysis,
    PricingAnalysis,
    ProductAnalysis,
    QATimeline,
    QualityCheckResult,
    StrategyReport,
)
from workflow.state import AnalysisState

# Event system imports (optional, for web UI)
try:
    from server.models import EventType, WorkflowEvent
    from server.services.event_bus import EventBus
except ImportError:
    EventType = None
    WorkflowEvent = None
    EventBus = None


T = TypeVar("T")


class AnalysisGraphNodes:
    """Bound node methods for the analysis graph.

    Args:
        orchestrator: Existing Orchestrator instance that owns agents and
            artifact/timing helpers.
        node_retries: Number of node-level retries for transient exceptions.
            This is separate from QualityAgent semantic retries.
    """

    def __init__(self, orchestrator, node_retries: int = 2, event_bus=None, task_id: str = ""):
        self.orchestrator = orchestrator
        self.node_retries = node_retries
        self.event_bus = event_bus
        self.task_id = task_id

    async def _retry_node(self, name: str, fn: Callable[[], Awaitable[T]]) -> T:
        last_error: Exception | None = None
        for attempt in range(self.node_retries + 1):
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001 - node boundary records all failures
                last_error = exc
                if attempt >= self.node_retries:
                    break
                await asyncio.sleep(min(0.2 * (attempt + 1), 1.0))
        assert last_error is not None
        raise RuntimeError(f"node '{name}' failed after {self.node_retries + 1} attempts") from last_error

    async def _emit(self, state: AnalysisState, event_type, agent: str, phase: str,
                    progress: float = 0.0, message: str = "", data: dict = None) -> None:
        """Emit a workflow event to the event bus (no-op if event_bus is None)."""
        if not self.event_bus or not WorkflowEvent:
            return
        try:
            event = WorkflowEvent(
                type=event_type,
                task_id=self.task_id,
                agent=agent,
                phase=phase,
                status="running" if "started" in event_type.value else "completed",
                progress=progress,
                message=message,
                data=data,
            )
            await self.event_bus.emit(self.task_id, event)
        except Exception:
            pass  # never let event emission break the pipeline

    @staticmethod
    def _merge_timing(state: AnalysisState, name: str, duration: float) -> dict[str, float]:
        timings = dict(state.get("timings", {}))
        timings[name] = duration
        return timings

    @staticmethod
    def _append_qa(state: AnalysisState, result: QualityCheckResult) -> list[QualityCheckResult]:
        checks = list(state.get("qa_checks", []))
        checks.append(result)
        return checks

    @staticmethod
    def _mark_exhausted(state: AnalysisState, phase: str) -> dict[str, bool]:
        exhausted = dict(state.get("quality_exhausted", {}))
        exhausted[phase] = True
        return exhausted

    @staticmethod
    def _qa_event_payload(result: QualityCheckResult) -> dict:
        """把 QA 结果压成前端可直接展示的轻量 dict。"""
        payload = asdict(result) if is_dataclass(result) else dict(result)
        payload["issues"] = [
            asdict(issue) if is_dataclass(issue) else issue
            for issue in getattr(result, "issues", payload.get("issues", []))
        ]
        return payload

    @staticmethod
    def _failure_payload(
        state: AnalysisState,
        phase: str,
        qa_result: QualityCheckResult | None,
        feedback: str,
    ) -> dict:
        issues = []
        if qa_result:
            for issue in qa_result.issues:
                issues.append(asdict(issue) if is_dataclass(issue) else issue)
        return {
            "phase": phase,
            "target_agent": qa_result.target_agent if qa_result else "",
            "score": qa_result.score if qa_result else 0,
            "attempt": qa_result.attempt if qa_result else 0,
            "feedback": feedback,
            "issues": issues,
            "qa_checks": [
                {
                    "phase": check.phase,
                    "target_agent": check.target_agent,
                    "passed": check.passed,
                    "score": check.score,
                    "attempt": check.attempt,
                    "degraded": check.degraded,
                }
                for check in state.get("qa_checks", [])
            ],
        }

    async def initialize_run(self, state: AnalysisState) -> AnalysisState:
        started = time.perf_counter()
        self.orchestrator._start_artifacts(
            state["product_description"], state["max_competitors"]
        )
        await self._emit(
            state,
            EventType.PROGRESS_UPDATE,
            "Orchestrator",
            "init",
            progress=0.02,
            message="运行归档已创建",
            data={"run_dir": self.orchestrator.run_dir},
        )
        return {
            "status": "running",
            "run_dir": self.orchestrator.run_dir,
            "timings": {},
            "started_perf_counter": started,
            "qa_checks": [],
            "collection_retry_count": 0,
            "product_retry_count": 0,
            "pricing_retry_count": 0,
            "market_retry_count": 0,
            "strategy_retry_count": 0,
            "collection_supplemented": False,
            "product_prev_score": 0,
            "pricing_prev_score": 0,
            "market_prev_score": 0,
            "quality_exhausted": {},
            "collection_feedback": "",
            "product_feedback": "",
            "pricing_feedback": "",
            "market_feedback": "",
            "strategy_feedback": "",
            "latest_feedback": "",
        }

    async def discover_competitors(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.AGENT_STARTED, "DiscoveryAgent", "discovery",
                         progress=0.05, message="正在生成搜索关键词...")

        async def call():
            return await self.orchestrator.discovery_agent.run(
                state["product_description"], state["max_competitors"]
            )

        start = time.perf_counter()
        competitors = await self._retry_node("discover_competitors", call)
        timings = self._merge_timing(state, "discovery", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("01_competitor_list.json", competitors)

        await self._emit(state, EventType.AGENT_COMPLETED, "DiscoveryAgent", "discovery",
                         progress=0.15, message=f"发现 {len(competitors.competitors)} 个竞品",
                         data={"competitors": [c.name for c in competitors.competitors]})
        return {
            "competitor_list": competitors,
            "product_name": competitors.product_name,
            "timings": timings,
        }

    async def finalize_no_competitors(self, state: AnalysisState) -> AnalysisState:
        report = StrategyReport(product_name=state["competitor_list"].product_name)
        timings = self._merge_timing(
            state,
            "total",
            time.perf_counter() - state.get("started_perf_counter", time.perf_counter()),
        )
        self.orchestrator.timings = timings
        report.raw_llm_logs = self.orchestrator._collect_llm_logs()
        self.orchestrator._save_artifact_json("07_strategy_report.json", report)
        self.orchestrator._save_artifact_json("llm_logs.json", report.raw_llm_logs)
        self.orchestrator._finalize_artifacts(
            status="stopped_no_competitors",
            product_name=report.product_name,
            competitor_count=0,
        )
        return {
            "status": "stopped_no_competitors",
            "report": report,
            "raw_llm_logs": report.raw_llm_logs,
            "timings": timings,
        }

    async def collect_target_product(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.AGENT_STARTED, "CollectionAgent", "collection",
                         progress=0.15, message="正在采集目标产品数据...")

        async def call():
            return await self.orchestrator.collection_agent.async_collect_target_product(
                state["product_description"], state["product_name"]
            )

        start = time.perf_counter()
        data = await self._retry_node("collect_target_product", call)
        timings = self._merge_timing(state, "target_collection", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("00_target_product_data.json", data)

        await self._emit(state, EventType.AGENT_COMPLETED, "CollectionAgent", "collection",
                         progress=0.20, message="目标产品数据采集完成")
        return {"target_product_data": data, "timings": timings}

    async def collect_competitors(self, state: AnalysisState) -> AnalysisState:
        n = len(state["competitor_list"].competitors)
        await self._emit(state, EventType.AGENT_STARTED, "CollectionAgent", "collection",
                         progress=0.20, message=f"正在采集 {n} 个竞品数据...")

        async def call():
            return await self.orchestrator.collection_agent.run(
                state["product_description"],
                state["competitor_list"],
                feedback=state.get("collection_feedback", ""),
            )

        start = time.perf_counter()
        data = await self._retry_node("collect_competitors", call)
        timings = self._merge_timing(state, "collection", time.perf_counter() - start)
        self.orchestrator.timings = timings
        search_texts = self.orchestrator.collection_agent.get_search_texts()
        if not data and state.get("competitors_data"):
            data = state["competitors_data"]
        if not search_texts and state.get("original_search_texts"):
            search_texts = state["original_search_texts"]
        self.orchestrator._save_artifact_json("02_competitors_data.json", data)
        self.orchestrator._save_artifact_json("02_search_texts.json", search_texts)
        await self._emit(state, EventType.AGENT_COMPLETED, "CollectionAgent", "collection",
                         progress=0.35, message=f"竞品数据采集完成，共 {len(data)} 个")
        return {
            "competitors_data": data,
            "original_search_texts": search_texts,
            "timings": timings,
        }

    async def check_collection_quality(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.QA_CHECK_STARTED, "QualityAgent", "collection",
                         progress=0.37, message="正在检查采集数据质量...",
                         data={
                             "phase": "collection",
                             "target_agent": "CollectionAgent",
                             "attempt": state.get("collection_retry_count", 0) + 1,
                         })
        attempt = state.get("collection_retry_count", 0) + 1

        # Always save collection artifacts regardless of QA mode
        self.orchestrator._save_artifact_json("02_competitors_data.json", state["competitors_data"])
        self.orchestrator._save_artifact_json("02_search_texts.json", state["original_search_texts"])

        if config.SKIP_QA:
            result = QualityCheckResult(
                phase="collection", target_agent="CollectionAgent",
                passed=True, score=100.0, hallucination_status="skipped",
            )
            self.orchestrator.quality_agent.timeline.add_check(result)
            self.orchestrator._save_artifact_json("qa_timeline.json", self.orchestrator.quality_agent.timeline)
            await self._emit(state, EventType.QA_CHECK_PASSED, "QualityAgent", "collection",
                             progress=0.38,
                             message="采集质检通过 (分数: 100)",
                             data={
                                 "score": result.score,
                                 "passed": result.passed,
                                 "degraded": result.degraded,
                                 "qa_result": self._qa_event_payload(result),
                             })
            return {
                "qa_collection": result,
                "qa_checks": self._append_qa(state, result),
                "timings": self._merge_timing(state, "qa_collection", 0),
            }

        async def call():
            return await self.orchestrator.quality_agent.check_collection(
                state["competitors_data"],
                state["original_search_texts"],
                competitor_list=state["competitor_list"],
                attempt=attempt,
            )

        start = time.perf_counter()
        result = await self._retry_node("check_collection_quality", call)
        # 「仅幻觉」短路通过：已至少重试 1 轮且未通过，但无缺失字段、无 critical completeness 问题
        # 新增：检查幻觉问题数量，过多幻觉不应通过
        if not result.passed and state.get("collection_retry_count", 0) >= 1:
            missing_fields = self.orchestrator.quality_agent.extract_missing_fields(
                result, state["competitors_data"]
            )
            has_critical_completeness = any(
                issue.severity == "critical" and issue.category == "completeness"
                for issue in result.issues
            )
            # 统计幻觉问题数量和严重程度
            hallucination_issues = [
                issue for issue in result.issues
                if issue.category == "hallucination"
            ]
            critical_hallucinations = [
                issue for issue in hallucination_issues
                if issue.severity == "critical"
            ]
            # 如果有超过3个幻觉问题或任何critical幻觉，不应通过
            has_excessive_hallucinations = (
                len(hallucination_issues) > 3 or len(critical_hallucinations) > 0
            )
            if not missing_fields and not has_critical_completeness and not has_excessive_hallucinations:
                result.passed = True
            elif has_excessive_hallucinations:
                # 记录为什么没有通过
                await self._emit(
                    state,
                    EventType.QA_CHECK_FAILED,
                    "QualityAgent",
                    "collection",
                    progress=0.38,
                    message=(
                        f"降级通过被阻止：发现{len(hallucination_issues)}个幻觉问题"
                        + (f"，其中{len(critical_hallucinations)}个为critical级别" if critical_hallucinations else "")
                    ),
                )
        # 重试后设置修正率：上轮缺失字段数即为本轮修正数
        if state.get("collection_retry_count", 0) > 0:
            result.correction_count = state.get("collection_pending_fields", 0)
        self.orchestrator.quality_agent.timeline.add_check(result)
        timings = self._merge_timing(state, "qa_collection", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("qa_timeline.json", self.orchestrator.quality_agent.timeline)

        qa_type = EventType.QA_CHECK_PASSED if result.passed else EventType.QA_CHECK_FAILED
        await self._emit(state, qa_type, "QualityAgent", "collection",
                         progress=0.38,
                         message=f"采集质检{'通过' if result.passed else '未通过'} (分数: {result.score:.0f})",
                         data={
                             "score": result.score,
                             "passed": result.passed,
                             "degraded": result.degraded,
                             "qa_result": self._qa_event_payload(result),
                         })
        # QA 通过后同步更新采集节点状态为 completed
        if result.passed or result.degraded:
            await self._emit(state, EventType.AGENT_COMPLETED, "CollectionAgent", "collection",
                             progress=0.39,
                             message=f"数据采集完成（经过 {state.get('collection_retry_count', 0) + 1} 轮质检）")
        return {
            "qa_collection": result,
            "qa_checks": self._append_qa(state, result),
            "timings": timings,
        }

    async def prepare_collection_retry(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.QA_RETRYING, "CollectionAgent", "collection",
                         progress=0.35,
                         message="正在准备采集数据重做...",
                         data={
                             "retry_count": state.get("collection_retry_count", 0) + 1,
                         })
        quality_agent = self.orchestrator.quality_agent
        collection_agent = self.orchestrator.collection_agent
        missing_fields = quality_agent.extract_missing_fields(
            state["qa_collection"], state.get("competitors_data")
        )
        # 计算本轮缺失字段总数（用于修正率）
        pending_count = sum(len(fields) for fields in missing_fields.values())
        if missing_fields:
            # 定向补充搜索：仅针对缺失/截断字段补搜，不整体重跑采集
            supplemented = await collection_agent.async_supplement_missing_fields(
                state["product_name"],
                state["competitors_data"],
                missing_fields,
            )
            search_texts = collection_agent.get_search_texts() or state.get(
                "original_search_texts", {}
            )
            feedback = quality_agent.build_supplement_feedback(missing_fields)
            return {
                "competitors_data": supplemented,
                "original_search_texts": search_texts,
                "collection_supplemented": True,
                "collection_feedback": "",
                "latest_feedback": feedback,
                "collection_retry_count": state.get("collection_retry_count", 0) + 1,
                "collection_pending_fields": pending_count,
            }

        # 无缺失字段：保持整体重跑路径
        feedback = await quality_agent.async_build_feedback(state["qa_collection"])
        return {
            "collection_supplemented": False,
            "collection_feedback": feedback,
            "latest_feedback": feedback,
            "collection_retry_count": state.get("collection_retry_count", 0) + 1,
            "collection_pending_fields": pending_count,
        }

    async def mark_collection_degraded(self, state: AnalysisState) -> AnalysisState:
        result = state["qa_collection"]
        result.degraded = True
        feedback = await self.orchestrator.quality_agent.async_build_feedback(result)
        await self._emit(state, EventType.QA_CHECK_PASSED, "QualityAgent", "collection",
                         progress=0.39,
                         message=f"采集质检降级通过 (分数: {result.score:.0f})",
                         data={
                             "score": result.score,
                             "passed": result.passed,
                             "degraded": result.degraded,
                             "qa_result": self._qa_event_payload(result),
                         })
        return {
            "qa_collection": result,
            "latest_feedback": feedback,
            "quality_exhausted": self._mark_exhausted(state, "collection"),
        }

    async def generate_dimensions(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.AGENT_STARTED, "DimensionAgent", "dimension",
                         progress=0.40, message="正在生成分析维度配置...")

        async def call():
            return await self.orchestrator.dimension_agent.run(
                state["product_description"], state["competitor_list"]
            )

        start = time.perf_counter()
        config = await self._retry_node("generate_dimensions", call)
        timings = self._merge_timing(state, "dimension", time.perf_counter() - start)
        self.orchestrator.timings = timings
        product_dims = self.orchestrator._format_sub_dimensions(config.product_sub_dimensions)
        pricing_dims = self.orchestrator._format_sub_dimensions(config.pricing_sub_dimensions)
        self.orchestrator._save_artifact_json("03_dimension_config.json", config)

        await self._emit(state, EventType.AGENT_COMPLETED, "DimensionAgent", "dimension",
                         progress=0.45, message="维度配置生成完成")
        return {
            "dimension_config": config,
            "product_sub_dims_text": product_dims,
            "pricing_sub_dims_text": pricing_dims,
            "timings": timings,
        }

    async def build_degradation_warning(self, state: AnalysisState) -> AnalysisState:
        warning = ""
        qa_collection = state.get("qa_collection")
        if qa_collection and qa_collection.degraded:
            critical_hallucinations = [
                i for i in qa_collection.issues
                if i.severity == "critical" and i.category == "hallucination"
            ]
            if critical_hallucinations:
                warning = "⚠️ 上游采集数据存在以下幻觉嫌疑，请在分析时谨慎引用，优先使用有明确来源支撑的数据：\n"
                for issue in critical_hallucinations[:5]:
                    warning += f"- {issue.field}: {issue.description}\n"
        return {
            "degradation_warning": warning,
            "parallel_started_perf_counter": time.perf_counter(),
        }

    async def run_product_analysis(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.AGENT_STARTED, "ProductAgent", "product_analysis",
                         progress=0.45, message="正在进行功能对比分析...")

        async def call():
            return await self.orchestrator.product_agent.run(
                state["product_name"],
                state["competitors_data"],
                target_product_data=state.get("target_product_data"),
                sub_dimensions=state.get("product_sub_dims_text", ""),
                feedback=state.get("product_feedback") or state.get("degradation_warning", ""),
            )

        start = time.perf_counter()
        analysis = await self._retry_node("run_product_analysis", call)
        timings = self._merge_timing(state, "product_analysis", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("04_product_analysis.json", analysis)

        await self._emit(state, EventType.AGENT_COMPLETED, "ProductAgent", "product_analysis",
                         progress=0.55, message="功能对比分析完成")
        return {"product_analysis": analysis, "timings": timings}

    async def run_pricing_analysis(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.AGENT_STARTED, "PricingAgent", "pricing_analysis",
                         progress=0.55, message="正在进行定价分析...")

        async def call():
            return await self.orchestrator.pricing_agent.run(
                state["product_name"],
                state["competitors_data"],
                target_product_data=state.get("target_product_data"),
                sub_dimensions=state.get("pricing_sub_dims_text", ""),
                feedback=state.get("pricing_feedback") or state.get("degradation_warning", ""),
            )

        start = time.perf_counter()
        analysis = await self._retry_node("run_pricing_analysis", call)
        timings = self._merge_timing(state, "pricing_analysis", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("05_pricing_analysis.json", analysis)

        await self._emit(state, EventType.AGENT_COMPLETED, "PricingAgent", "pricing_analysis",
                         progress=0.65, message="定价分析完成")
        return {"pricing_analysis": analysis, "timings": timings}

    async def run_market_analysis(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.AGENT_STARTED, "MarketAgent", "market_analysis",
                         progress=0.65, message="正在进行市场分析...")

        async def call():
            return await self.orchestrator.market_agent.run(
                state["product_name"],
                state["competitors_data"],
                target_product_data=state.get("target_product_data"),
                feedback=state.get("market_feedback") or state.get("degradation_warning", ""),
            )

        start = time.perf_counter()
        analysis = await self._retry_node("run_market_analysis", call)
        timings = self._merge_timing(state, "market_analysis", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("06_market_analysis.json", analysis)

        await self._emit(state, EventType.AGENT_COMPLETED, "MarketAgent", "market_analysis",
                         progress=0.75, message="市场分析完成")
        return {"market_analysis": analysis, "timings": timings}

    async def join_parallel_analysis(self, state: AnalysisState) -> AnalysisState:
        timings = self._merge_timing(
            state,
            "parallel_analysis",
            time.perf_counter() - state.get("parallel_started_perf_counter", time.perf_counter()),
        )
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("04_product_analysis.json", state["product_analysis"])
        self.orchestrator._save_artifact_json("05_pricing_analysis.json", state["pricing_analysis"])
        self.orchestrator._save_artifact_json("06_market_analysis.json", state["market_analysis"])
        return {"timings": timings, "qa_started_perf_counter": time.perf_counter()}

    async def check_product_quality(self, state: AnalysisState) -> AnalysisState:
        return await self._check_analysis_quality(state, "product", state["product_analysis"])

    async def check_pricing_quality(self, state: AnalysisState) -> AnalysisState:
        return await self._check_analysis_quality(state, "pricing", state["pricing_analysis"])

    async def check_market_quality(self, state: AnalysisState) -> AnalysisState:
        return await self._check_analysis_quality(state, "market", state["market_analysis"])

    async def _check_analysis_quality(
        self,
        state: AnalysisState,
        analysis_type: str,
        analysis: ProductAnalysis | PricingAnalysis | MarketAnalysis,
    ) -> AnalysisState:
        retry_key = f"{analysis_type}_retry_count"
        attempt = state.get(retry_key, 0) + 1
        agent_name = {"product": "ProductAgent", "pricing": "PricingAgent", "market": "MarketAgent"}[analysis_type]

        await self._emit(state, EventType.QA_CHECK_STARTED, "QualityAgent", analysis_type,
                         progress=state.get("progress", 0.75),
                         message=f"正在检查{analysis_type}分析质量...",
                         data={
                             "phase": analysis_type,
                             "target_agent": agent_name,
                             "attempt": attempt,
                         })

        if config.SKIP_QA:
            result = QualityCheckResult(
                phase=analysis_type, target_agent=agent_name,
                passed=True, score=100.0, hallucination_status="skipped",
            )
            await self._emit(state, EventType.QA_CHECK_PASSED, "QualityAgent", analysis_type,
                             progress=state.get("progress", 0.75),
                             message=f"{analysis_type}分析质检通过 (分数: 100)",
                             data={
                                 "score": result.score,
                                 "passed": result.passed,
                                 "degraded": result.degraded,
                                 "qa_result": self._qa_event_payload(result),
                             })
            return {f"qa_{analysis_type}": result}

        async def call():
            return await self.orchestrator.quality_agent.check_analysis(
                analysis_type,
                analysis,
                state["competitors_data"],
                attempt=attempt,
            )

        result = await self._retry_node(f"check_{analysis_type}_quality", call)
        # 分数未提升即通过：处于重试态且新分数未高于上一轮，判定为误报通过
        if (
            not result.passed
            and state.get(retry_key, 0) > 0
            and result.score <= state.get(f"{analysis_type}_prev_score", 0)
        ):
            result.passed = True
        # 重试后设置修正率
        if state.get(retry_key, 0) > 0:
            result.correction_count = state.get("analysis_pending_fields", 0)
        qa_type = EventType.QA_CHECK_PASSED if result.passed else EventType.QA_CHECK_FAILED
        await self._emit(state, qa_type, "QualityAgent", analysis_type,
                         progress=state.get("progress", 0.75),
                         message=f"{analysis_type}分析质检{'通过' if result.passed else '未通过'} (分数: {result.score:.0f})",
                         data={
                             "score": result.score,
                             "passed": result.passed,
                             "degraded": result.degraded,
                             "qa_result": self._qa_event_payload(result),
                         })
        # QA 通过后同步更新分析节点状态为 completed
        if result.passed or result.degraded:
            phase_key = f"{analysis_type}_analysis"
            await self._emit(state, EventType.AGENT_COMPLETED, agent_name, phase_key,
                             progress=state.get("progress", 0.75),
                             message=f"{analysis_type}分析完成（经过 {state.get(retry_key, 0) + 1} 轮质检）")
        return {f"qa_{analysis_type}": result}

    async def join_analysis_quality(self, state: AnalysisState) -> AnalysisState:
        checks = list(state.get("qa_checks", []))
        for key in ("qa_product", "qa_pricing", "qa_market"):
            result = state.get(key)
            if result and result not in checks:
                checks.append(result)
                self.orchestrator.quality_agent.timeline.add_check(result)
        timings = self._merge_timing(
            state,
            "qa_analysis",
            time.perf_counter() - state.get("qa_started_perf_counter", time.perf_counter()),
        )
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("qa_timeline.json", self.orchestrator.quality_agent.timeline)
        return {"qa_checks": checks, "timings": timings}

    async def prepare_product_retry(self, state: AnalysisState) -> AnalysisState:
        return await self._prepare_analysis_retry(state, "product")

    async def prepare_pricing_retry(self, state: AnalysisState) -> AnalysisState:
        return await self._prepare_analysis_retry(state, "pricing")

    async def prepare_market_retry(self, state: AnalysisState) -> AnalysisState:
        return await self._prepare_analysis_retry(state, "market")

    async def _prepare_analysis_retry(self, state: AnalysisState, analysis_type: str) -> AnalysisState:
        await self._emit(state, EventType.QA_RETRYING, "QualityAgent", analysis_type,
                         progress=state.get("progress", 0.75),
                         message=f"正在准备{analysis_type}分析重做...",
                         data={
                             "retry_count": state.get(f"{analysis_type}_retry_count", 0) + 1,
                         })
        qa = state[f"qa_{analysis_type}"]
        feedback = await self.orchestrator.quality_agent.async_build_feedback(qa)
        retry_key = f"{analysis_type}_retry_count"
        feedback_key = f"{analysis_type}_feedback"
        prev_score_key = f"{analysis_type}_prev_score"
        # 计算本轮缺失字段数（critical completeness issues 数量）
        pending = sum(1 for i in qa.issues if i.severity == "critical" and i.category == "completeness")
        return {
            feedback_key: feedback,
            "latest_feedback": feedback,
            retry_key: state.get(retry_key, 0) + 1,
            prev_score_key: qa.score,
            "qa_started_perf_counter": time.perf_counter(),
            "analysis_pending_fields": state.get("analysis_pending_fields", 0) + pending,
        }

    async def mark_analysis_degraded(self, state: AnalysisState) -> AnalysisState:
        updates: AnalysisState = {"quality_exhausted": dict(state.get("quality_exhausted", {}))}
        latest_feedback = ""
        for analysis_type in ("product", "pricing", "market"):
            key = f"qa_{analysis_type}"
            result = state.get(key)
            if result and not result.passed:
                result.degraded = True
                updates[key] = result
                updates["quality_exhausted"][analysis_type] = True
                await self._emit(state, EventType.QA_CHECK_PASSED, "QualityAgent", analysis_type,
                                 progress=0.75,
                                 message=f"{analysis_type}分析质检降级通过 (分数: {result.score:.0f})",
                                 data={
                                     "score": result.score,
                                     "passed": result.passed,
                                     "degraded": result.degraded,
                                     "qa_result": self._qa_event_payload(result),
                                 })
                if not latest_feedback:
                    latest_feedback = await self.orchestrator.quality_agent.async_build_feedback(result)
                    updates[f"{analysis_type}_feedback"] = latest_feedback
        if latest_feedback:
            updates["latest_feedback"] = latest_feedback
        return updates

    async def generate_strategy(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.AGENT_STARTED, "StrategyAgent", "strategy",
                         progress=0.75, message="正在生成战略建议报告...")

        async def call():
            return await self.orchestrator.strategy_agent.run(
                state["product_name"],
                len(state["competitor_list"].competitors),
                state["product_analysis"],
                state["pricing_analysis"],
                state["market_analysis"],
                target_product_data=state.get("target_product_data"),
                competitors_data=state.get("competitors_data"),
                feedback=state.get("strategy_feedback", ""),
            )

        start = time.perf_counter()
        report = await self._retry_node("generate_strategy", call)
        timings = self._merge_timing(state, "strategy", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("07_strategy_report.json", report)

        await self._emit(state, EventType.AGENT_COMPLETED, "StrategyAgent", "strategy",
                         progress=0.90, message="战略建议报告生成完成")
        return {"report": report, "timings": timings}

    async def check_strategy_quality(self, state: AnalysisState) -> AnalysisState:
        attempt = state.get("strategy_retry_count", 0) + 1
        await self._emit(state, EventType.QA_CHECK_STARTED, "QualityAgent", "strategy",
                         progress=0.92,
                         message="正在检查战略建议报告质量...",
                         data={
                             "phase": "strategy",
                             "target_agent": "StrategyAgent",
                             "attempt": attempt,
                         })

        if config.SKIP_QA:
            result = QualityCheckResult(
                phase="strategy", target_agent="StrategyAgent",
                passed=True, score=100.0, hallucination_status="skipped",
            )
            self.orchestrator.quality_agent.timeline.add_check(result)
            await self._emit(state, EventType.QA_CHECK_PASSED, "QualityAgent", "strategy",
                             progress=0.93,
                             message="策略报告质检通过 (分数: 100)",
                             data={
                                 "score": result.score,
                                 "passed": result.passed,
                                 "degraded": result.degraded,
                                 "qa_result": self._qa_event_payload(result),
                             })
            return {
                "qa_strategy": result,
                "qa_checks": self._append_qa(state, result),
                "timings": self._merge_timing(state, "qa_strategy", 0),
            }

        async def call():
            return await self.orchestrator.quality_agent.check_strategy(
                state["report"],
                state["product_analysis"],
                state["pricing_analysis"],
                state["market_analysis"],
                attempt=attempt,
            )

        start = time.perf_counter()
        result = await self._retry_node("check_strategy_quality", call)
        # 重试后设置修正率
        if state.get("strategy_retry_count", 0) > 0:
            result.correction_count = state.get("analysis_pending_fields", 0)
        self.orchestrator.quality_agent.timeline.add_check(result)
        timings = self._merge_timing(state, "qa_strategy", time.perf_counter() - start)
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("qa_timeline.json", self.orchestrator.quality_agent.timeline)
        qa_type = EventType.QA_CHECK_PASSED if result.passed else EventType.QA_CHECK_FAILED
        await self._emit(state, qa_type, "QualityAgent", "strategy",
                         progress=0.93,
                         message=f"策略报告质检{'通过' if result.passed else '未通过'} (分数: {result.score:.0f})",
                         data={
                             "score": result.score,
                             "passed": result.passed,
                             "degraded": result.degraded,
                             "qa_result": self._qa_event_payload(result),
                         })
        # QA 通过后同步更新策略节点状态为 completed
        if result.passed or result.degraded:
            await self._emit(state, EventType.AGENT_COMPLETED, "StrategyAgent", "strategy",
                             progress=0.95,
                             message=f"策略报告完成（经过 {state.get('strategy_retry_count', 0) + 1} 轮质检）")
        return {
            "qa_strategy": result,
            "qa_checks": self._append_qa(state, result),
            "timings": timings,
        }

    async def prepare_strategy_retry(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.QA_RETRYING, "StrategyAgent", "strategy",
                         progress=0.91,
                         message="正在准备策略报告重做...",
                         data={
                             "retry_count": state.get("strategy_retry_count", 0) + 1,
                         })
        qa = state["qa_strategy"]
        feedback = await self.orchestrator.quality_agent.async_build_feedback(qa)
        pending = sum(1 for i in qa.issues if i.severity == "critical" and i.category == "completeness")
        return {
            "strategy_feedback": feedback,
            "latest_feedback": feedback,
            "strategy_retry_count": state.get("strategy_retry_count", 0) + 1,
            "analysis_pending_fields": state.get("analysis_pending_fields", 0) + pending,
        }

    async def mark_strategy_degraded(self, state: AnalysisState) -> AnalysisState:
        result = state["qa_strategy"]
        result.degraded = True
        feedback = await self.orchestrator.quality_agent.async_build_feedback(result)
        await self._emit(state, EventType.QA_CHECK_PASSED, "QualityAgent", "strategy",
                         progress=0.94,
                         message=f"策略报告质检降级通过 (分数: {result.score:.0f})",
                         data={
                             "score": result.score,
                             "passed": result.passed,
                             "degraded": result.degraded,
                             "qa_result": self._qa_event_payload(result),
                         })
        return {
            "qa_strategy": result,
            "strategy_feedback": feedback,
            "latest_feedback": feedback,
            "quality_exhausted": self._mark_exhausted(state, "strategy"),
        }

    async def finalize_report(self, state: AnalysisState) -> AnalysisState:
        await self._emit(state, EventType.PROGRESS_UPDATE, "Orchestrator", "finalize",
                         progress=0.95, message="正在整理最终报告...")

        report = state["report"]
        report.qa_timeline = self.orchestrator.quality_agent.timeline
        report.raw_llm_logs = self.orchestrator._collect_llm_logs()

        timings = self._merge_timing(
            state,
            "total",
            time.perf_counter() - state.get("started_perf_counter", time.perf_counter()),
        )
        self.orchestrator.timings = timings
        self.orchestrator._save_artifact_json("07_strategy_report.json", report)
        self.orchestrator._save_artifact_json("qa_timeline.json", report.qa_timeline)
        self.orchestrator._save_artifact_json("llm_logs.json", report.raw_llm_logs)

        # 保存 Token 用量汇总
        token_summary = self.orchestrator._build_token_summary(report.raw_llm_logs)
        self.orchestrator._save_artifact_json("token_summary.json", token_summary)

        # 保存业务闭环指标
        qa = report.qa_timeline
        per_phase = {}
        for c in qa._last_attempt_per_phase():
            per_phase[c.phase] = {
                "accuracy_rate": c.accuracy_rate,
                "coverage_rate": c.coverage_rate,
                "correction_count": c.correction_count,
                "total_fields": c.total_fields,
            }
        total_fields = sum(c.total_fields for c in qa._last_attempt_per_phase())
        corrected_fields = sum(c.correction_count for c in qa._last_attempt_per_phase())
        business_metrics = {
            "accuracy_rate": qa.get_accuracy_rate(),
            "coverage_rate": qa.get_coverage_rate(),
            "correction_rate": qa.get_correction_rate(),
            "detail": {
                "per_phase": per_phase,
                "total_fields": total_fields,
                "corrected_fields": corrected_fields,
            },
        }
        self.orchestrator._save_artifact_json("business_metrics.json", business_metrics)

        # 保存 DAG 可视化
        if self.orchestrator.artifact_store:
            try:
                from workflow.graph import save_graph_visualization
                save_graph_visualization(self.orchestrator.artifact_store)
            except Exception as e:
                print(f"  ⚠️ DAG可视化导出失败: {e}")

        status = "completed_degraded" if state.get("quality_exhausted") else "completed"
        self.orchestrator._finalize_artifacts(
            status=status,
            product_name=report.product_name,
            competitor_count=report.competitor_count,
        )

        self.orchestrator._last_product_analysis = state.get("product_analysis")
        self.orchestrator._last_pricing_analysis = state.get("pricing_analysis")
        self.orchestrator._last_market_analysis = state.get("market_analysis")
        self.orchestrator._last_competitor_list = state.get("competitor_list")
        self.orchestrator._last_competitors_data = state.get("competitors_data")
        self.orchestrator._last_target_product_data = state.get("target_product_data")

        return {
            "status": status,
            "report": report,
            "raw_llm_logs": report.raw_llm_logs,
            "timings": timings,
        }

    async def fail_run(self, state: AnalysisState) -> AnalysisState:
        phase = self._first_failed_phase(state)
        qa = state.get(f"qa_{phase}") if phase else None
        feedback = state.get("latest_feedback", "")
        failure = self._failure_payload(state, phase or "unknown", qa, feedback)
        report = state.get("report") or StrategyReport(product_name=state.get("product_name", ""))
        report.qa_timeline = self.orchestrator.quality_agent.timeline
        report.raw_llm_logs = self.orchestrator._collect_llm_logs()
        self.orchestrator._save_artifact_json("failed_state.json", failure)
        self.orchestrator._save_artifact_json("qa_timeline.json", report.qa_timeline)
        self.orchestrator._save_artifact_json("llm_logs.json", report.raw_llm_logs)

        # 保存 Token 用量汇总（即使失败也记录消耗）
        token_summary = self.orchestrator._build_token_summary(report.raw_llm_logs)
        self.orchestrator._save_artifact_json("token_summary.json", token_summary)

        self.orchestrator._finalize_artifacts(
            status="failed",
            product_name=report.product_name,
            competitor_count=report.competitor_count,
        )
        return {
            "status": "failed",
            "error": f"quality_exhausted:{failure['phase']}",
            "failure": failure,
            "report": report,
            "raw_llm_logs": report.raw_llm_logs,
        }

    @staticmethod
    def _first_failed_phase(state: AnalysisState) -> str:
        for phase in ("collection", "product", "pricing", "market", "strategy"):
            result = state.get(f"qa_{phase}")
            if result and not result.passed:
                return phase
        exhausted = state.get("quality_exhausted", {})
        for phase, value in exhausted.items():
            if value:
                return phase
        return ""
