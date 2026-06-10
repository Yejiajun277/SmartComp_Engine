# -*- coding: utf-8 -*-
"""Task lifecycle manager with asyncio concurrency control."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from server.models import EventType, WorkflowEvent
from server.services.event_bus import EventBus

_TASKS_DIR = Path(__file__).resolve().parents[2] / "output" / "tasks"


@dataclass
class TaskState:
    id: str
    product_description: str
    max_competitors: int
    skip_qa: bool
    use_rule_engine: bool = False
    status: str = "pending"  # pending | running | completed | failed
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_agent: str | None = None
    progress: float = 0.0
    report_path: str | None = None
    html_report_path: str | None = None
    report_json: dict | None = None
    llm_logs: list[dict] = field(default_factory=list)
    error: str | None = None


class _DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class TaskManager:
    def __init__(self, event_bus: EventBus, max_concurrent: int = 5):
        self._tasks: dict[str, TaskState] = {}
        self._event_bus = event_bus
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._load_tasks()

    def _save_task(self, task: TaskState) -> None:
        """Persist a single task to disk as JSON."""
        _TASKS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "id": task.id,
            "product_description": task.product_description,
            "max_competitors": task.max_competitors,
            "skip_qa": task.skip_qa,
            "use_rule_engine": task.use_rule_engine,
            "status": task.status,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "current_agent": task.current_agent,
            "progress": task.progress,
            "report_path": task.report_path,
            "html_report_path": task.html_report_path,
            "report_json": task.report_json,
            "llm_logs": task.llm_logs,
            "error": task.error,
        }
        path = _TASKS_DIR / f"{task.id}.json"
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2, cls=_DateTimeEncoder),
                            encoding="utf-8")
        except (TypeError, ValueError) as exc:
            # Fallback: save without report_json if it contains non-serializable types
            data["report_json"] = None
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2, cls=_DateTimeEncoder),
                            encoding="utf-8")
            print(f"[TaskManager] _save_task: report_json non-serializable, saved without it: {exc}")

    def _load_tasks(self) -> None:
        """Restore tasks from disk on startup."""
        if not _TASKS_DIR.is_dir():
            return
        for path in sorted(_TASKS_DIR.glob("*.json")):
            if path.name.endswith("_events.jsonl"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                task = TaskState(
                    id=data["id"],
                    product_description=data["product_description"],
                    max_competitors=data["max_competitors"],
                    skip_qa=data["skip_qa"],
                    use_rule_engine=data.get("use_rule_engine", False),
                    status=data["status"],
                    started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
                    finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
                    current_agent=data.get("current_agent"),
                    progress=data.get("progress", 0.0),
                    report_path=data.get("report_path"),
                    html_report_path=data.get("html_report_path"),
                    report_json=data.get("report_json"),
                    llm_logs=data.get("llm_logs", []),
                    error=data.get("error"),
                )
                # Tasks that were running/pending when the process exited are effectively failed
                if task.status in ("running", "pending"):
                    task.status = "failed"
                    task.error = task.error or "进程重启，任务中断"
                self._tasks[task.id] = task
            except Exception:
                continue  # skip corrupt files

    def _sync_tasks_from_disk(self) -> None:
        """Merge persisted tasks into memory without changing their status."""
        if not _TASKS_DIR.is_dir():
            return
        for path in sorted(_TASKS_DIR.glob("*.json")):
            if path.name.endswith("_events.jsonl"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                task_id = data["id"]
                if task_id in self._tasks:
                    continue
                self._tasks[task_id] = TaskState(
                    id=task_id,
                    product_description=data["product_description"],
                    max_competitors=data["max_competitors"],
                    skip_qa=data["skip_qa"],
                    use_rule_engine=data.get("use_rule_engine", False),
                    status=data["status"],
                    started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
                    finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
                    current_agent=data.get("current_agent"),
                    progress=data.get("progress", 0.0),
                    report_path=data.get("report_path"),
                    html_report_path=data.get("html_report_path"),
                    report_json=data.get("report_json"),
                    llm_logs=data.get("llm_logs", []),
                    error=data.get("error"),
                )
            except Exception:
                continue

    def _on_workflow_event(self, event: WorkflowEvent) -> None:
        """Update task.progress and task.current_agent from workflow events."""
        task = self._tasks.get(event.task_id)
        if not task:
            return
        task.progress = event.progress
        if event.type == EventType.AGENT_STARTED and event.agent:
            task.current_agent = event.agent
        elif event.type in (EventType.AGENT_COMPLETED, EventType.AGENT_FAILED):
            if task.current_agent == event.agent:
                task.current_agent = None
        if event.data and event.data.get("run_dir"):
            task.report_path = event.data["run_dir"]
            self._save_task(task)

    async def submit(self, product_description: str, max_competitors: int,
                     skip_qa: bool, use_rule_engine: bool = False) -> str:
        if not use_rule_engine:
            import config as app_config
            use_rule_engine = not bool(app_config.DOUBAO_API_KEY)

        task_id = str(uuid.uuid4())[:8]
        task = TaskState(
            id=task_id,
            product_description=product_description,
            max_competitors=max_competitors,
            skip_qa=skip_qa,
            use_rule_engine=use_rule_engine,
        )
        self._tasks[task_id] = task
        self._save_task(task)
        asyncio.create_task(self._run_task(task_id, product_description, max_competitors,
                                            skip_qa, use_rule_engine))
        return task_id

    def get(self, task_id: str) -> TaskState | None:
        return self._tasks.get(task_id)

    def delete(self, task_id: str) -> bool:
        self._sync_tasks_from_disk()
        task = self._tasks.pop(task_id, None)
        task_path = _TASKS_DIR / f"{task_id}.json"
        events_path = _TASKS_DIR / f"{task_id}_events.jsonl"
        deleted = False

        if task and task.report_path:
            run_dir = Path(task.report_path)
            output_root = Path(__file__).resolve().parents[2] / "output"
            try:
                if run_dir.is_dir() and output_root in run_dir.resolve().parents:
                    shutil.rmtree(run_dir)
                    deleted = True
            except Exception:
                pass

        for path in (task_path, events_path):
            try:
                if path.exists():
                    path.unlink()
                    deleted = True
            except Exception:
                pass

        return bool(task or deleted)

    def list_all(self) -> list[TaskState]:
        self._sync_tasks_from_disk()
        return sorted(self._tasks.values(), key=lambda t: t.started_at or datetime.min, reverse=True)

    async def _run_task(self, task_id: str, product_description: str,
                        max_competitors: int, skip_qa: bool, use_rule_engine: bool) -> None:
        async with self._semaphore:
            task = self._tasks[task_id]
            task.status = "running"
            task.started_at = datetime.now()
            self._save_task(task)

            # Listen to workflow events to update progress/agent in real time
            self._event_bus.add_listener(self._on_workflow_event)

            # Wait for WebSocket to connect and subscribe
            await asyncio.sleep(1.5)

            mode_msg = "规则引擎模式（无 LLM）" if use_rule_engine else "LLM 智能分析模式"
            await self._event_bus.emit(task_id, WorkflowEvent(
                type=EventType.TASK_STARTED,
                task_id=task_id,
                agent="Orchestrator",
                phase="init",
                status="running",
                progress=0.0,
                message=f"开始分析: {product_description} [{mode_msg}]",
            ))

            try:
                import config as app_config
                app_config.SKIP_QA = skip_qa
                app_config.ENABLE_LLM = not use_rule_engine

                from core.orchestrator import Orchestrator
                orchestrator = Orchestrator()

                # 给每个 Agent 注册 on_log_added 回调，LLM 调用完成后立即通知前端
                def _on_agent_log(log_entry):
                    task.llm_logs.append({
                        "type": "llm",
                        "agent": log_entry.get("agent_id", ""),
                        **{k: log_entry.get(k, "") for k in (
                            "timestamp", "system_prompt", "user_message", "result",
                            "model", "finish_reason", "parse_error",
                        )},
                        **{k: log_entry.get(k, 0) for k in (
                            "prompt_tokens", "completion_tokens", "total_tokens",
                            "duration_ms", "max_tokens",
                        )},
                        **{k: log_entry.get(k, 0.0) for k in ("temperature",)},
                        "success": log_entry.get("success", True),
                    })
                    # fire-and-forget 事件发射（不阻塞 Agent 执行）
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._event_bus.emit(task_id, WorkflowEvent(
                            type=EventType.LLM_LOGS_UPDATED,
                            task_id=task_id,
                            agent=log_entry.get("agent_id", "Agent"),
                            phase="llm_logs",
                            status="running",
                            progress=task.progress,
                            message=f"LLM 调用日志已更新（{len(task.llm_logs)} 条）",
                            data={"total": len(task.llm_logs)},
                        )))
                    except Exception:
                        pass

                for agent in [
                    orchestrator.discovery_agent,
                    orchestrator.collection_agent,
                    orchestrator.dimension_agent,
                    orchestrator.product_agent,
                    orchestrator.pricing_agent,
                    orchestrator.market_agent,
                    orchestrator.strategy_agent,
                    orchestrator.quality_agent,
                ]:
                    if hasattr(agent, 'on_log_added'):
                        agent.on_log_added = _on_agent_log

                log_sync_task = asyncio.create_task(self._sync_llm_logs_live(task, orchestrator))
                try:
                    report = await orchestrator.analyze(
                        product_description, max_competitors,
                        event_bus=self._event_bus, task_id=task_id,
                    )
                finally:
                    log_sync_task.cancel()
                    try:
                        await log_sync_task
                    except asyncio.CancelledError:
                        pass

                task.status = "completed"
                task.finished_at = datetime.now()
                task.progress = 1.0
                task.current_agent = None
                task.report_path = str(orchestrator.run_dir) if hasattr(orchestrator, "run_dir") else None

                # Generate and save HTML report (same as main.py)
                try:
                    html_content = orchestrator.strategy_agent.format_html_report(
                        report,
                        product_analysis=getattr(orchestrator, '_last_product_analysis', None),
                        pricing_analysis=getattr(orchestrator, '_last_pricing_analysis', None),
                        market_analysis=getattr(orchestrator, '_last_market_analysis', None),
                        competitor_list=getattr(orchestrator, '_last_competitor_list', None),
                        competitors_data=getattr(orchestrator, '_last_competitors_data', None),
                        timings=orchestrator.get_timings(),
                    )
                    if task.report_path:
                        html_path = Path(task.report_path) / "report.html"
                        html_path.write_text(html_content, encoding="utf-8")
                        task.html_report_path = str(html_path)
                except Exception:
                    task.html_report_path = None

                # Collect LLM logs
                try:
                    task.llm_logs = _collect_llm_logs(orchestrator)
                except Exception:
                    task.llm_logs = []

                try:
                    task.report_json = _report_to_dict(report)
                except Exception:
                    task.report_json = None

                self._save_task(task)

                await self._event_bus.emit(task_id, WorkflowEvent(
                    type=EventType.TASK_COMPLETED,
                    task_id=task_id,
                    agent="Orchestrator",
                    phase="finalize",
                    status="completed",
                    progress=1.0,
                    message="分析完成",
                    data={
                        "llm_calls": len(task.llm_logs),
                        "rule_engine_mode": use_rule_engine,
                    },
                ))
            except Exception as exc:
                task.status = "failed"
                task.finished_at = datetime.now()
                task.error = str(exc)
                self._save_task(task)

                await self._event_bus.emit(task_id, WorkflowEvent(
                    type=EventType.TASK_FAILED,
                    task_id=task_id,
                    agent="Orchestrator",
                    phase="error",
                    status="failed",
                    progress=task.progress,
                    message=f"分析失败: {exc}",
                ))
            finally:
                self._event_bus.remove_listener(self._on_workflow_event)

    async def _sync_llm_logs_live(self, task: TaskState, orchestrator) -> None:
        """Periodically persist task state to disk while a task is running.

        LLM log events are now emitted immediately via on_log_added callback.
        This task only handles periodic disk persistence and search log sync.
        """
        last_persisted = 0
        while True:
            await asyncio.sleep(3)
            try:
                # 持久化到磁盘（仅当有新日志时）
                if len(task.llm_logs) > last_persisted:
                    last_persisted = len(task.llm_logs)
                    self._save_task(task)
                # 补充搜索日志（搜索客户端没有 on_log_added 回调）
                search_logs = []
                for agent in [
                    orchestrator.discovery_agent,
                    orchestrator.collection_agent,
                ]:
                    if hasattr(agent, 'search_client') and hasattr(agent.search_client, 'search_logs'):
                        for log in agent.search_client.search_logs:
                            log_entry = dict(log)
                            log_entry.setdefault("type", "search")
                            log_entry.setdefault("agent", agent.agent_id)
                            search_logs.append(log_entry)
                if search_logs:
                    existing_search = [l for l in task.llm_logs if l.get("type") == "search"]
                    if len(search_logs) != len(existing_search):
                        # 合并搜索日志（不覆盖已有的 LLM 日志）
                        task.llm_logs = [l for l in task.llm_logs if l.get("type") != "search"] + search_logs
                        self._save_task(task)
            except Exception:
                continue


def _collect_llm_logs(orchestrator) -> list[dict]:
    """Collect LLM + search call logs from all agents."""
    logs = []
    agents = [
        orchestrator.discovery_agent,
        orchestrator.collection_agent,
        orchestrator.dimension_agent,
        orchestrator.product_agent,
        orchestrator.pricing_agent,
        orchestrator.market_agent,
        orchestrator.strategy_agent,
        orchestrator.quality_agent,
    ]
    for agent in agents:
        if hasattr(agent, 'llm_logs'):
            for log in agent.llm_logs:
                logs.append({
                    "type": "llm",
                    "agent": log.get("agent_id") or (agent.agent_id if hasattr(agent, 'agent_id') else agent.__class__.__name__),
                    "timestamp": log.get("timestamp", ""),
                    "system_prompt": log.get("system_prompt", ""),
                    "user_message": log.get("user_message", ""),
                    "result": log.get("result", ""),
                    "prompt_tokens": log.get("prompt_tokens", 0),
                    "completion_tokens": log.get("completion_tokens", 0),
                    "total_tokens": log.get("total_tokens", 0),
                    "duration_ms": log.get("duration_ms", 0.0),
                    "model": log.get("model", ""),
                    "finish_reason": log.get("finish_reason", ""),
                    "temperature": log.get("temperature", 0.0),
                    "max_tokens": log.get("max_tokens", 0),
                    "success": log.get("success", True),
                    "parse_error": log.get("parse_error", ""),
                })
    # Collect search logs from agents that have a search_client
    for agent in agents:
        if hasattr(agent, 'search_client') and hasattr(agent.search_client, 'search_logs'):
            for log in agent.search_client.search_logs:
                log_entry = dict(log)
                log_entry.setdefault("agent", agent.agent_id if hasattr(agent, 'agent_id') else agent.__class__.__name__)
                logs.append(log_entry)
    return logs


def _report_to_dict(report) -> dict:
    from dataclasses import asdict, is_dataclass
    if is_dataclass(report):
        return asdict(report)
    return {}
