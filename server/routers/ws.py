# -*- coding: utf-8 -*-
"""WebSocket route for real-time task progress."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/tasks/{task_id}")
async def task_progress_ws(websocket: WebSocket, task_id: str):
    await websocket.accept()

    manager = websocket.app.state.task_manager
    event_bus = websocket.app.state.event_bus

    # Check task exists
    task = manager.get(task_id)
    if not task:
        try:
            await websocket.send_json({"type": "error", "message": "Task not found"})
            await websocket.close()
        except Exception:
            pass
        return

    queue: asyncio.Queue = asyncio.Queue()
    subscribed = False

    try:
        # Send history for reconnection replay
        history = event_bus.get_history(task_id)
        print(f"[WS] {task_id}: sending {len(history)} history events")
        for event in history:
            await websocket.send_json(event)

        # If task already finished, close.
        # History events (from disk) should include the terminal event, but send
        # a synthetic one as fallback to ensure the frontend stops reconnecting.
        if task.status in ("completed", "failed"):
            if not history or history[-1].get("type") not in ("task_completed", "task_failed"):
                terminal_type = "task_completed" if task.status == "completed" else "task_failed"
                await websocket.send_json({
                    "type": terminal_type,
                    "task_id": task_id,
                    "agent": "Orchestrator",
                    "phase": "finalize",
                    "status": task.status,
                    "progress": 1.0 if task.status == "completed" else task.progress,
                    "message": task.error if task.status == "failed" else "分析完成",
                })
            await websocket.close()
            return

        # Subscribe to live events
        async def on_event(event):
            print(f"[WS] {task_id}: queueing event {event.type.value}")
            await queue.put(event)

        event_bus.subscribe(task_id, on_event)
        subscribed = True
        print(f"[WS] {task_id}: subscribed to live events")

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                print(f"[WS] {task_id}: sending event {event.type.value}")
                await websocket.send_json(event.model_dump(mode="json"))
                if event.type.value in ("task_completed", "task_failed"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        pass  # Client disconnected or send failed — normal during page navigation
    finally:
        if subscribed:
            event_bus.unsubscribe(task_id, on_event)
