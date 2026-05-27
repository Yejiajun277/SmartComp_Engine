from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from agents.collection_agent import CollectionAgent
from agents.discovery_agent import DiscoveryAgent
from agents.market_agent import MarketAgent
from agents.pricing_agent import PricingAgent
from agents.product_agent import ProductAgent
from agents.quality_agent import QualityAgent
from agents.research_planner_agent import DEFAULT_TOPICS, ResearchPlannerAgent
from agents.strategy_agent import StrategyAgent
from core.run_store import ensure_run_dirs, new_run_id, write_artifact, write_report_files, write_trace
from models.domain import (
    CompetitorList,
    CompetitorData,
    EvidenceBundle,
    MessageEnvelope,
    QAIssue,
    ResearchCoverage,
    ResearchEvidence,
    StrategyReport,
    now_iso,
    to_dict,
)
from workflow.state import AnalysisState


DEFAULT_FOCUS_TOPICS = list(DEFAULT_TOPICS.keys())


@dataclass
class WorkflowAgents:
    discovery_agent: DiscoveryAgent
    research_planner_agent: ResearchPlannerAgent
    collection_agent: CollectionAgent
    product_agent: ProductAgent
    pricing_agent: PricingAgent
    market_agent: MarketAgent
    quality_agent: QualityAgent
    strategy_agent: StrategyAgent

    def all_agents(self) -> list[Any]:
        return [
            self.discovery_agent,
            self.research_planner_agent,
            self.collection_agent,
            self.product_agent,
            self.pricing_agent,
            self.market_agent,
            self.quality_agent,
            self.strategy_agent,
        ]


def create_workflow_agents() -> WorkflowAgents:
    return WorkflowAgents(
        discovery_agent=DiscoveryAgent(),
        research_planner_agent=ResearchPlannerAgent(),
        collection_agent=CollectionAgent(),
        product_agent=ProductAgent(),
        pricing_agent=PricingAgent(),
        market_agent=MarketAgent(),
        quality_agent=QualityAgent(),
        strategy_agent=StrategyAgent(),
    )


class WorkflowNodes:
    def __init__(self, agents: WorkflowAgents):
        self.agents = agents

    async def init_context(self, state: AnalysisState) -> dict[str, Any]:
        started_at = time.time()
        run_id = state.get("run_id") or new_run_id()
        dirs = ensure_run_dirs(run_id)
        payload = {
            "run_id": run_id,
            "status": "running",
            "run_started_at": started_at,
            "qa_round": 0,
            "retry_count": 0,
            "qa_decision": "pending",
            "qa_issue_count": 0,
            "focus_topics": state.get("focus_topics") or DEFAULT_FOCUS_TOPICS,
            "competitor_list": None,
            "research_tasks": [],
            "research_coverage": None,
            "research_evidence": {},
            "evidence_bundles": {},
            "competitors_data": {},
            "product_analysis": None,
            "pricing_analysis": None,
            "market_analysis": None,
            "report": None,
            "qa_issues": [],
            "report_paths": {},
            "trace_summary": {
                "run_id": run_id,
                "root": str(dirs["root"]),
                "trace_dir": str(dirs["trace"]),
                "artifact_dir": str(dirs["artifacts"]),
                "report_dir": str(dirs["report"]),
            },
            "timings": {},
            "llm_logs": [],
            "error": None,
            "logs": [{"node": "init_context", "status": "success", "run_id": run_id}],
        }
        self._persist_trace(
            run_id=run_id,
            node="init_context",
            started_at=started_at,
            input_summary="初始化运行上下文",
            output_summary=f"run_id={run_id}",
            decision="pass",
            attempt=1,
        )
        return payload

    async def discover_competitors(self, state: AnalysisState) -> dict[str, Any]:
        start = time.time()
        competitor_list = await self.agents.discovery_agent.run(
            state["product_description"],
            state["max_competitors"],
        )
        write_artifact(state["run_id"], "competitor_list", to_dict(competitor_list))
        self._persist_trace(
            run_id=state["run_id"],
            node="discover_competitors",
            started_at=start,
            input_summary=state["product_description"],
            output_summary=f"competitors={len(competitor_list.competitors)}",
            decision="collect" if competitor_list.competitors else "empty_report",
            attempt=state.get("qa_round", 0) + 1,
            llm_logs=self.agents.discovery_agent.llm_logs,
        )
        return {
            "competitor_list": competitor_list,
            "timing_records": [{"name": "discovery", "duration": time.time() - start}],
            "logs": [
                {
                    "node": "discover_competitors",
                    "status": "success",
                    "competitor_count": len(competitor_list.competitors),
                }
            ],
        }

    def route_after_discovery(self, state: AnalysisState) -> str:
        competitor_list = state.get("competitor_list")
        if competitor_list and competitor_list.competitors:
            return "plan_research"
        return "build_empty_report"

    async def plan_research(self, state: AnalysisState) -> dict[str, Any]:
        start = time.time()
        competitor_list = state.get("competitor_list")
        if competitor_list is None:
            raise ValueError("plan_research 缺少 competitor_list")
        tasks = await self.agents.research_planner_agent.run(
            product_description=state["product_description"],
            competitor_list=competitor_list,
            focus_topics=state.get("focus_topics"),
            qa_issues=state.get("qa_issues", []),
            retry_count=state.get("retry_count", 0),
        )
        tasks = self._filter_retry_tasks(tasks, state.get("qa_issues", []), state.get("retry_count", 0))
        write_artifact(state["run_id"], "research_tasks", to_dict(tasks))
        self._persist_trace(
            run_id=state["run_id"],
            node="plan_research",
            started_at=start,
            input_summary=f"competitors={len(competitor_list.competitors)}",
            output_summary=f"tasks={len(tasks)}",
            decision="collect",
            attempt=state.get("qa_round", 0) + 1,
            llm_logs=self.agents.research_planner_agent.llm_logs,
        )
        return {
            "research_tasks": tasks,
            "timing_records": [{"name": "research_plan", "duration": time.time() - start}],
            "logs": [{"node": "plan_research", "status": "success", "task_count": len(tasks)}],
        }

    async def collect_competitor_data(self, state: AnalysisState) -> dict[str, Any]:
        start = time.time()
        tasks = state.get("research_tasks", [])
        if not tasks:
            raise ValueError("collect_competitor_data 缺少 research_tasks")
        result = await self.agents.collection_agent.run(
            product_description=state["product_description"],
            tasks=tasks,
            retry_count=state.get("retry_count", 0),
        )
        if state.get("retry_count", 0) > 0:
            result = self._merge_collection_result(state, result)
        write_artifact(state["run_id"], "competitors_data", to_dict(result["competitors_data"]))
        write_artifact(state["run_id"], "evidence_bundles", to_dict(result["evidence_bundles"]))
        write_artifact(state["run_id"], "research_coverage", to_dict(result["research_coverage"]))
        self._persist_trace(
            run_id=state["run_id"],
            node="collect_competitor_data",
            started_at=start,
            input_summary=f"tasks={len(tasks)}",
            output_summary=f"competitors={len(result['competitors_data'])}",
            decision="analyze",
            attempt=state.get("qa_round", 0) + 1,
            llm_logs=self.agents.collection_agent.llm_logs,
        )
        return {
            "competitors_data": result["competitors_data"],
            "research_evidence": result["research_evidence"],
            "research_coverage": result["research_coverage"],
            "evidence_bundles": result["evidence_bundles"],
            "timing_records": [{"name": "collection", "duration": time.time() - start}],
            "logs": [
                {
                    "node": "collect_competitor_data",
                    "status": "success",
                    "competitor_count": len(result["competitors_data"]),
                }
            ],
        }

    async def analyze_product(self, state: AnalysisState) -> dict[str, Any]:
        return await self._run_analysis_node(
            state=state,
            node_name="analyze_product",
            timing_name="product_analysis",
            agent=self.agents.product_agent,
            dimension="product",
        )

    async def analyze_pricing(self, state: AnalysisState) -> dict[str, Any]:
        return await self._run_analysis_node(
            state=state,
            node_name="analyze_pricing",
            timing_name="pricing_analysis",
            agent=self.agents.pricing_agent,
            dimension="pricing",
        )

    async def analyze_market(self, state: AnalysisState) -> dict[str, Any]:
        return await self._run_analysis_node(
            state=state,
            node_name="analyze_market",
            timing_name="market_analysis",
            agent=self.agents.market_agent,
            dimension="market",
        )

    async def quality_gate(self, state: AnalysisState) -> dict[str, Any]:
        start = time.time()
        result = await self.agents.quality_agent.run(
            product_analysis=state.get("product_analysis"),
            pricing_analysis=state.get("pricing_analysis"),
            market_analysis=state.get("market_analysis"),
            coverage=state.get("research_coverage"),
            qa_round=state.get("qa_round", 0),
            product_name=self._resolve_product_name(state),
            competitor_count=len(state.get("competitor_list").competitors) if state.get("competitor_list") else 0,
            competitor_names=self._competitor_names(state),
            evidence_bundles=state.get("evidence_bundles", {}),
        )
        issues = result["issues"]
        decision = result["next_action"]
        qa_round = state.get("qa_round", 0)
        retry_count = state.get("retry_count", 0)
        current_round = qa_round + 1
        write_artifact(state["run_id"], f"qa_issues_round_{current_round}", to_dict(issues))
        if decision in {"redo_collection", "redo_analysis"}:
            qa_round += 1
            retry_count += 1
        self._persist_trace(
            run_id=state["run_id"],
            node="quality_gate",
            started_at=start,
            input_summary=(
                f"product={state.get('product_analysis') is not None}, "
                f"pricing={state.get('pricing_analysis') is not None}, "
                f"market={state.get('market_analysis') is not None}"
            ),
            output_summary=f"issues={len(issues)}",
            decision=decision,
            attempt=current_round,
            llm_logs=self.agents.quality_agent.llm_logs,
        )
        return {
            "qa_issues": issues,
            "qa_decision": decision,
            "qa_issue_count": len(issues),
            "qa_round": qa_round,
            "retry_count": retry_count,
            "timing_records": [{"name": "quality_gate", "duration": time.time() - start}],
            "logs": [{"node": "quality_gate", "status": "success", "decision": decision, "issue_count": len(issues)}],
        }

    def route_after_quality(self, state: AnalysisState) -> str:
        decision = state.get("qa_decision", "pass")
        if decision == "redo_collection":
            return "plan_research"
        if decision == "redo_analysis":
            return "redo_analysis"
        return "build_strategy_report"

    async def redo_analysis(self, state: AnalysisState) -> dict[str, Any]:
        start = time.time()
        issues = state.get("qa_issues", [])
        targets = {issue.target_agent for issue in issues}
        payload: dict[str, Any] = {"logs": []}
        if "ProductAgent" in targets:
            payload["product_analysis"] = await self.agents.product_agent.run(
                self._resolve_product_name(state),
                state.get("evidence_bundles", {}),
                state.get("competitors_data", {}),
            )
            payload["product_analysis"] = self._sanitize_analysis("product", payload["product_analysis"], state)
        if "PricingAgent" in targets:
            payload["pricing_analysis"] = await self.agents.pricing_agent.run(
                self._resolve_product_name(state),
                state.get("evidence_bundles", {}),
                state.get("competitors_data", {}),
            )
            payload["pricing_analysis"] = self._sanitize_analysis("pricing", payload["pricing_analysis"], state)
        if "MarketAgent" in targets:
            payload["market_analysis"] = await self.agents.market_agent.run(
                self._resolve_product_name(state),
                state.get("evidence_bundles", {}),
                state.get("competitors_data", {}),
            )
            payload["market_analysis"] = self._sanitize_analysis("market", payload["market_analysis"], state)
        self._persist_trace(
            run_id=state["run_id"],
            node="redo_analysis",
            started_at=start,
            input_summary=",".join(sorted(targets)),
            output_summary=f"rerun={len(targets)}",
            decision="quality_gate",
            attempt=state.get("qa_round", 0) + 1,
        )
        payload["timing_records"] = [{"name": "redo_analysis", "duration": time.time() - start}]
        payload["logs"] = [{"node": "redo_analysis", "status": "success", "targets": sorted(targets)}]
        return payload

    async def build_strategy_report(self, state: AnalysisState) -> dict[str, Any]:
        start = time.time()
        competitor_list = state.get("competitor_list")
        product_analysis = state.get("product_analysis")
        pricing_analysis = state.get("pricing_analysis")
        market_analysis = state.get("market_analysis")
        if competitor_list is None:
            raise ValueError("build_strategy_report 缺少 competitor_list")
        if product_analysis is None:
            raise ValueError("build_strategy_report 缺少 product_analysis")
        if pricing_analysis is None:
            raise ValueError("build_strategy_report 缺少 pricing_analysis")
        if market_analysis is None:
            raise ValueError("build_strategy_report 缺少 market_analysis")

        report = await self.agents.strategy_agent.run(
            competitor_list.product_name,
            len(competitor_list.competitors),
            product_analysis,
            pricing_analysis,
            market_analysis,
            state.get("evidence_bundles", {}),
        )
        report.run_id = state["run_id"]
        report.qa_issues = [
            *state.get("qa_issues", []),
            *self._strategy_quality_issues(report, state.get("evidence_bundles", {})),
        ]
        if state.get("research_coverage") is not None:
            report.coverage_gaps = state["research_coverage"].coverage_gaps
        if report.qa_issues:
            report.status = "degraded"
        write_artifact(state["run_id"], "strategy_report", to_dict(report))
        self._persist_trace(
            run_id=state["run_id"],
            node="build_strategy_report",
            started_at=start,
            input_summary=f"qa_issues={len(report.qa_issues)}",
            output_summary=f"status={report.status}",
            decision="finalize",
            attempt=state.get("qa_round", 0) + 1,
            llm_logs=self.agents.strategy_agent.llm_logs,
        )
        return {
            "report": report,
            "status": report.status,
            "timing_records": [{"name": "strategy", "duration": time.time() - start}],
            "logs": [{"node": "build_strategy_report", "status": "success"}],
        }

    @staticmethod
    def _strategy_quality_issues(
        report: StrategyReport,
        evidence_bundles: dict[str, list[EvidenceBundle]] | None = None,
    ) -> list[QAIssue]:
        issues: list[QAIssue] = []
        if len(report.action_plan) < 3:
            issues.append(
                QAIssue(
                    issue_type="thin_action_plan",
                    severity="high",
                    target_agent="StrategyAgent",
                    reason=f"行动方案不足 3 条，当前仅 {len(report.action_plan)} 条。",
                    required_fix="补足至少 3 条按优先级排列、带时间线和预期效果的行动方案。",
                    related_ids=["strategy:action_plan"],
                )
            )
        generic_terms = ("重写为什么现在应该选你", "把最核心的 1-2 个高频场景", "继续做一份泛化对标")
        joined_actions = " ".join(item.action for item in report.action_plan)
        if any(term in report.summary or term in joined_actions for term in generic_terms):
            issues.append(
                QAIssue(
                    issue_type="template_strategy",
                    severity="medium",
                    target_agent="StrategyAgent",
                    reason="策略建议仍存在模板化表达。",
                    required_fix="用具体产品、竞品、功能、价格或市场机会替换泛化表达。",
                    related_ids=["strategy:summary"],
                )
            )
        known_citations = {
            citation.id
            for bundles in (evidence_bundles or {}).values()
            for bundle in bundles
            for citation in bundle.citations
            if citation.id
        }
        for index, item in enumerate(report.action_plan, start=1):
            if not item.citations:
                issues.append(
                    QAIssue(
                        issue_type="missing_citation",
                        severity="high",
                        target_agent="StrategyAgent",
                        reason=f"第 {index} 条策略行动未挂 citation。",
                        required_fix="每条策略行动必须挂至少 1 个可回溯 citation。",
                        related_ids=[f"strategy:action_plan:{index}"],
                    )
                )
            else:
                if known_citations and any(citation_id not in known_citations for citation_id in item.citations):
                    issues.append(
                        QAIssue(
                            issue_type="unknown_citation",
                            severity="high",
                            target_agent="StrategyAgent",
                            reason=f"第 {index} 条策略行动包含无法回溯的 citation。",
                            required_fix="删除无效 citation，或重新采集对应证据。",
                            related_ids=[f"strategy:action_plan:{index}"],
                        )
                    )
                citation_competitors = {
                    citation_id.split(":", 1)[0]
                    for citation_id in item.citations
                    if ":" in citation_id
                }
                if len(citation_competitors) == 1 and report.competitor_count > 1:
                    issues.append(
                        QAIssue(
                            issue_type="narrow_strategy_evidence",
                            severity="medium",
                            target_agent="StrategyAgent",
                            reason=f"第 {index} 条策略行动只引用了单一竞品证据，代表性不足。",
                            required_fix="跨竞品策略行动应尽量覆盖多个竞品或明确说明该建议只来自单一竞品对照。",
                            related_ids=[f"strategy:action_plan:{index}"],
                        )
                    )
        citation_sets = [tuple(item.citations) for item in report.action_plan if item.citations]
        if len(citation_sets) >= 3 and len(set(citation_sets)) == 1:
            issues.append(
                QAIssue(
                    issue_type="citation_mismatch",
                    severity="medium",
                    target_agent="StrategyAgent",
                    reason="多条策略行动复用了完全相同的 citation，存在引用泛化风险。",
                    required_fix="为每条策略行动挂载与其主题相关的直接证据。",
                    related_ids=["strategy:action_plan"],
                )
            )
        return issues

    async def build_empty_report(self, state: AnalysisState) -> dict[str, Any]:
        product_name = (
            state["competitor_list"].product_name
            if state.get("competitor_list") is not None
            else state["product_description"]
        )
        report = StrategyReport(
            product_name=product_name,
            status="empty",
            summary="未发现可用竞品，已生成空报告。",
        )
        return {
            "report": report,
            "status": "empty",
            "logs": [{"node": "build_empty_report", "status": "success"}],
        }

    async def finalize(self, state: AnalysisState) -> dict[str, Any]:
        timings: dict[str, float] = {}
        for item in state.get("timing_records", []):
            name = item.get("name")
            duration = item.get("duration")
            if isinstance(name, str) and isinstance(duration, (int, float)):
                timings[name] = float(duration)
        started_at = state.get("run_started_at")
        if isinstance(started_at, (int, float)):
            timings["total"] = time.time() - float(started_at)

        llm_logs: list[dict[str, Any]] = []
        for agent in self.agents.all_agents():
            llm_logs.extend(agent.llm_logs)

        report = state.get("report")
        if report is not None:
            report.raw_llm_logs = llm_logs
            html = self.agents.strategy_agent.format_html_report(
                report,
                product_analysis=state.get("product_analysis"),
                pricing_analysis=state.get("pricing_analysis"),
                market_analysis=state.get("market_analysis"),
                competitor_list=state.get("competitor_list"),
                competitors_data=state.get("competitors_data"),
                timings=timings,
            )
            report_payload = {
                "report": to_dict(report),
                "product_analysis": to_dict(state.get("product_analysis")),
                "pricing_analysis": to_dict(state.get("pricing_analysis")),
                "market_analysis": to_dict(state.get("market_analysis")),
                "competitor_list": to_dict(state.get("competitor_list")),
                "research_coverage": to_dict(state.get("research_coverage")),
                "competitors_data": to_dict(state.get("competitors_data")),
                "timings": timings,
            }
            report_paths = write_report_files(state["run_id"], report.product_name, report_payload, html)
            trace_summary = {
                **state.get("trace_summary", {}),
                "report_paths": report_paths,
                "final_status": state.get("status", report.status),
            }
            write_artifact(state["run_id"], "run_summary", trace_summary)
        else:
            report_paths = {}
            trace_summary = state.get("trace_summary", {})

        return {
            "timings": timings,
            "llm_logs": llm_logs,
            "report_paths": report_paths,
            "trace_summary": trace_summary,
            "status": state.get("status", "success"),
            "logs": [{"node": "finalize", "status": "success"}],
        }

    async def _run_analysis_node(
        self,
        state: AnalysisState,
        node_name: str,
        timing_name: str,
        agent: Any,
        dimension: str,
    ) -> dict[str, Any]:
        start = time.time()
        analysis = await agent.run(
            self._resolve_product_name(state),
            state.get("evidence_bundles", {}),
            state.get("competitors_data", {}),
        )
        analysis = self._sanitize_analysis(dimension, analysis, state)
        write_artifact(state["run_id"], dimension + "_analysis", to_dict(analysis))
        self._persist_trace(
            run_id=state["run_id"],
            node=node_name,
            started_at=start,
            input_summary=f"competitors={len(state.get('evidence_bundles', {}))}",
            output_summary=f"conclusions={len(analysis.conclusions)}",
            decision="quality_gate",
            attempt=state.get("qa_round", 0) + 1,
            llm_logs=agent.llm_logs,
        )
        return {
            f"{dimension}_analysis": analysis,
            "timing_records": [{"name": timing_name, "duration": time.time() - start}],
            "logs": [{"node": node_name, "status": "success"}],
        }

    @staticmethod
    def _resolve_product_name(state: AnalysisState) -> str:
        competitor_list = state.get("competitor_list")
        if competitor_list is not None:
            return competitor_list.product_name
        return state["product_description"]

    @staticmethod
    def _competitor_names(state: AnalysisState) -> list[str]:
        competitor_list = state.get("competitor_list")
        if not competitor_list:
            return []
        return [item.name for item in competitor_list.competitors]

    @staticmethod
    def _filter_retry_tasks(
        tasks: list[Any],
        issues: list[QAIssue],
        retry_count: int,
    ) -> list[Any]:
        if retry_count <= 0:
            return tasks
        wanted = {
            related
            for issue in issues
            if issue.target_agent == "CollectionAgent"
            for related in issue.related_ids
            if ":" in related
        }
        if not wanted:
            return tasks
        filtered = [task for task in tasks if f"{task.competitor}:{task.topic}" in wanted]
        return filtered or tasks

    def _merge_collection_result(self, state: AnalysisState, result: dict[str, Any]) -> dict[str, Any]:
        merged_bundles: dict[str, list[EvidenceBundle]] = {
            competitor: list(bundles)
            for competitor, bundles in state.get("evidence_bundles", {}).items()
        }
        merged_evidence: dict[str, list[ResearchEvidence]] = {
            competitor: list(items)
            for competitor, items in state.get("research_evidence", {}).items()
        }

        for competitor, bundles in result["evidence_bundles"].items():
            topics = {bundle.topic for bundle in bundles}
            kept = [bundle for bundle in merged_bundles.get(competitor, []) if bundle.topic not in topics]
            merged_bundles[competitor] = kept + list(bundles)

        for competitor, evidence_items in result["research_evidence"].items():
            topics = {item.topic for item in evidence_items}
            kept = [item for item in merged_evidence.get(competitor, []) if item.topic not in topics]
            merged_evidence[competitor] = kept + list(evidence_items)

        competitors_data: dict[str, CompetitorData] = {
            competitor: self.agents.collection_agent._build_competitor_data(
                competitor,
                bundles,
                merged_evidence.get(competitor, []),
            )
            for competitor, bundles in merged_bundles.items()
        }

        coverage = self._merge_coverage(
            state.get("research_coverage"),
            result["research_coverage"],
        )
        return {
            "competitors_data": competitors_data,
            "research_evidence": merged_evidence,
            "research_coverage": coverage,
            "evidence_bundles": merged_bundles,
        }

    @staticmethod
    def _merge_coverage(
        old_coverage: ResearchCoverage | None,
        new_coverage: ResearchCoverage,
    ) -> ResearchCoverage:
        if old_coverage is None:
            return new_coverage
        touched = {
            (item["competitor"], item["topic"])
            for item in new_coverage.failed_tasks
        }
        for competitor, topics in new_coverage.completed_topics.items():
            for topic in topics:
                touched.add((competitor, topic))

        old_coverage.failed_tasks = [
            item
            for item in old_coverage.failed_tasks
            if (item["competitor"], item["topic"]) not in touched
        ] + list(new_coverage.failed_tasks)
        old_coverage.coverage_gaps = [
            gap
            for gap in old_coverage.coverage_gaps
            if (gap.competitor, gap.topic) not in touched
        ] + list(new_coverage.coverage_gaps)
        for competitor, topics in new_coverage.completed_topics.items():
            old_topics = old_coverage.completed_topics.setdefault(competitor, [])
            for topic in topics:
                if topic not in old_topics:
                    old_topics.append(topic)
        return old_coverage

    def _sanitize_analysis(self, dimension: str, analysis: Any, state: AnalysisState) -> Any:
        allowed = set(self._competitor_names(state))
        product_name = self._resolve_product_name(state)
        if not allowed:
            return analysis

        if dimension == "product":
            allowed_matrix_keys = allowed | {product_name}
            for feature in analysis.feature_matrix:
                feature.values = {
                    name: value
                    for name, value in feature.values.items()
                    if name in allowed_matrix_keys
                }
                feature.competitor_citations = {
                    name: ids
                    for name, ids in feature.competitor_citations.items()
                    if name in allowed
                }
                feature.citations = self._dedupe_citation_ids(
                    cid
                    for ids in feature.competitor_citations.values()
                    for cid in ids
                )[:4]
            analysis.competitive_advantages = [
                item for item in analysis.competitive_advantages if item.competitor in allowed
            ]
            for node in analysis.feature_tree:
                node.supported_competitors = [
                    name for name in node.supported_competitors if name in allowed_matrix_keys
                ]
            return analysis

        if dimension == "pricing":
            analysis.pricing_comparison = [
                item for item in analysis.pricing_comparison if item.competitor in allowed
            ]
            analysis.pricing_models = [
                item for item in analysis.pricing_models if item.competitor in allowed
            ]
            analysis.value_ranking = [
                name for name in analysis.value_ranking if name in allowed
            ]
            return analysis

        if dimension == "market":
            analysis.market_share_data = [
                item for item in analysis.market_share_data if item.competitor in allowed
            ]
            analysis.user_reputation = {
                name: value
                for name, value in analysis.user_reputation.items()
                if name in allowed
            }
            analysis.user_personas = [
                item
                for item in analysis.user_personas
                if any(item.name.startswith(name) for name in allowed)
            ]
            return analysis

        return analysis

    @staticmethod
    def _dedupe_citation_ids(ids: Any) -> list[str]:
        return list(dict.fromkeys(item for item in ids if item))

    @staticmethod
    def _persist_trace(
        run_id: str,
        node: str,
        started_at: float,
        input_summary: str,
        output_summary: str,
        decision: str,
        attempt: int,
        llm_logs: list[dict[str, Any]] | None = None,
        error: str = "",
    ) -> None:
        ended_at = time.time()
        last_llm = llm_logs[-1] if llm_logs else {}
        prompt = str(last_llm.get("user_message_preview", ""))
        token_usage = {
            "prompt": int(last_llm.get("prompt_tokens_estimate", max(1, len(input_summary) // 4 or 1))),
            "completion": int(last_llm.get("completion_tokens_estimate", max(0, len(output_summary) // 4))),
        }
        write_trace(
            run_id=run_id,
            node=node,
            attempt=attempt,
            data={
                "node": node,
                "status": "error" if error else "success",
                "started_at": now_iso(),
                "ended_at": now_iso(),
                "latency_seconds": round(ended_at - started_at, 4),
                "prompt": prompt,
                "input_summary": input_summary,
                "output_summary": output_summary,
                "token_usage": token_usage,
                "error": error,
                "decision": decision,
                "version": "v2",
            },
        )
