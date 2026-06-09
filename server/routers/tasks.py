# -*- coding: utf-8 -*-
"""REST API routes for task management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server.models import TaskCreateRequest, TaskCreateResponse, TaskSummary

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# task_manager is injected via app.state in main.py


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
    )
    return TaskCreateResponse(task_id=task_id, status="pending")


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
    if task.status != "completed":
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
    if task.status != "completed":
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
        raise HTTPException(status_code=404, detail=f"Artifact not found: {filename}")

    return json.loads(artifact_path.read_text(encoding="utf-8"))
