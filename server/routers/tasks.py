# -*- coding: utf-8 -*-
"""REST API routes for task management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server.models import (
    TaskCreateRequest, TaskCreateResponse, TaskSummary,
    InterventionResponse, DescriptionEvaluateRequest, DescriptionEvaluateResponse,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# task_manager is injected via app.state in main.py


def _empty_qa_timeline():
    return {"checks": [], "max_retries": 2, "total_retries": 0}


def _get_manager(request):
    return request.app.state.task_manager


@router.post("", response_model=TaskCreateResponse)
async def create_task(body: TaskCreateRequest, request: Request):
    manager = _get_manager(request)
    task_id = await manager.submit(
        body.product_description,
        body.max_competitors,
        body.skip_qa,
        body.use_rule_engine,
        body.enable_human_review,
    )
    return TaskCreateResponse(task_id=task_id, status="pending")


@router.post("/evaluate-description", response_model=DescriptionEvaluateResponse)
async def evaluate_description(body: DescriptionEvaluateRequest, request: Request):
    """
    评估产品描述质量，返回质量分数和补充问题。
    - quality_score >= 0.7: 返回 quality="good"，无需补充
    - quality_score < 0.7:  返回 quality="insufficient"，附带问题列表
    """
    from server.services.description_evaluator import evaluate_description as _evaluate
    result = await _evaluate(body.product_description)
    return DescriptionEvaluateResponse(**result)


@router.get("/{task_id}/llm-logs")
async def get_llm_logs(task_id: str, request: Request):
    manager = _get_manager(request)
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"logs": task.llm_logs, "total": len(task.llm_logs)}


@router.get("", response_model=list[TaskSummary])
async def list_tasks(request: Request):
    manager = _get_manager(request)
    tasks = manager.list_all()
    return [
        TaskSummary(
            id=t.id,
            product_description=t.product_description,
            max_competitors=t.max_competitors,
            status=t.status,
            current_agent=t.current_agent,
            progress=t.progress,
            started_at=t.started_at,
            finished_at=t.finished_at,
            error=t.error,
            enable_human_review=t.enable_human_review,
            pending_intervention=t.pending_intervention,
        )
        for t in tasks
    ]


@router.get("/{task_id}", response_model=TaskSummary)
async def get_task(task_id: str, request: Request):
    manager = _get_manager(request)
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskSummary(
        id=task.id,
        product_description=task.product_description,
        max_competitors=task.max_competitors,
        status=task.status,
        current_agent=task.current_agent,
        progress=task.progress,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
        enable_human_review=task.enable_human_review,
        pending_intervention=task.pending_intervention,
    )


@router.delete("/{task_id}")
async def delete_task(task_id: str, request: Request):
    manager = _get_manager(request)
    if not manager.delete(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


@router.get("/{task_id}/report")
async def get_report(task_id: str, request: Request):
    manager = _get_manager(request)
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("completed", "completed_degraded"):
        raise HTTPException(status_code=400, detail=f"Task is {task.status}, not completed")
    if not task.report_json:
        raise HTTPException(status_code=404, detail="Report not available")
    return task.report_json


@router.get("/{task_id}/report.html")
async def get_html_report(task_id: str, request: Request):
    from fastapi.responses import HTMLResponse
    manager = _get_manager(request)
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("completed", "completed_degraded"):
        raise HTTPException(status_code=400, detail=f"Task is {task.status}, not completed")
    if not task.html_report_path:
        raise HTTPException(status_code=404, detail="HTML report not available")
    from pathlib import Path
    html_path = Path(task.html_report_path)
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="HTML report file not found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@router.get("/{task_id}/artifacts/{phase}")
async def get_artifact(task_id: str, phase: str, request: Request):
    manager = _get_manager(request)
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.report_path:
        if phase == "qa":
            return _empty_qa_timeline()
        raise HTTPException(status_code=404, detail="No artifacts available")

    import json
    from pathlib import Path

    run_dir = Path(task.report_path)
    artifact_map = {
        "discovery": "01_competitor_list.json",
        "collection": "02_competitors_data.json",
        "dimension": "03_dimension_config.json",
        "product": "04_product_analysis.json",
        "product_analysis": "04_product_analysis.json",
        "pricing": "05_pricing_analysis.json",
        "pricing_analysis": "05_pricing_analysis.json",
        "market": "06_market_analysis.json",
        "market_analysis": "06_market_analysis.json",
        "strategy": "07_strategy_report.json",
        "qa": "qa_timeline.json",
        "llm": "llm_logs.json",
    }
    filename = artifact_map.get(phase)
    if not filename:
        raise HTTPException(status_code=400, detail=f"Unknown phase: {phase}")

    artifact_path = run_dir / filename
    if not artifact_path.exists():
        if phase == "qa":
            return _empty_qa_timeline()
        raise HTTPException(status_code=404, detail=f"Artifact not found: {filename}")

    return json.loads(artifact_path.read_text(encoding="utf-8"))


# ── 人工介入端点 ──

@router.get("/{task_id}/intervention")
async def get_intervention(task_id: str, request: Request):
    """获取当前待审核的介入数据（前端轮询）。"""
    manager = _get_manager(request)
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    intervention = manager.get_pending_intervention(task_id)
    if not intervention:
        return {"pending": False}
    # 返回介入类型和对应的待审核数据
    run_dir = task.report_path
    payload = {"pending": True, "type": intervention["type"]}
    if run_dir:
        from pathlib import Path
        import json
        run_path = Path(run_dir)
        if intervention["type"] == "competitor_confirm":
            artifact = run_path / "01_competitor_list.json"
            if artifact.exists():
                payload["data"] = json.loads(artifact.read_text(encoding="utf-8"))
        elif intervention["type"] == "data_review":
            artifact = run_path / "02_competitors_data.json"
            if artifact.exists():
                payload["data"] = json.loads(artifact.read_text(encoding="utf-8"))
    return payload


@router.post("/{task_id}/intervention")
async def submit_intervention(task_id: str, body: InterventionResponse, request: Request):
    """提交人工介入决策（通过/打回/编辑）。"""
    manager = _get_manager(request)
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.pending_intervention:
        raise HTTPException(status_code=400, detail="No pending intervention")

    response = {
        "action": body.action,
        "feedback": body.feedback,
        "edited_competitors": body.edited_competitors,
        "edited_competitors_data": body.edited_competitors_data,
    }
    ok = await manager.submit_intervention_response(task_id, response)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to submit intervention")

    # 通过 WebSocket 通知前端介入已提交
    event_bus = request.app.state.event_bus
    from server.models import EventType, WorkflowEvent
    await event_bus.emit(task_id, WorkflowEvent(
        type=EventType.INTERVENTION_SUBMITTED,
        task_id=task_id,
        agent="HumanReview",
        phase=task.pending_intervention or "unknown",
        status="completed",
        progress=task.progress,
        message=f"人工介入已提交: {body.action}",
        data={"action": body.action},
    ))

    return {"ok": True, "action": body.action}
