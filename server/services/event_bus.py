# -*- coding: utf-8 -*-
"""In-memory event bus with ring buffer for reconnection replay."""

from __future__ import annotations

import json
import asyncio
from collections import deque
from pathlib import Path
from typing import Callable, Awaitable

from server.models import WorkflowEvent

_TASKS_DIR = Path(__file__).resolve().parents[2] / "output" / "tasks"


class EventBus:
    def __init__(self, history_size: int = 200):
        self._subscribers: dict[str, list[Callable[[WorkflowEvent], Awaitable[None]]]] = {}
        self._listeners: list[Callable[[WorkflowEvent], None]] = []
        self._history: dict[str, deque[WorkflowEvent]] = {}
        self._deleted_tasks: set[str] = set()
        self._history_size = history_size

    def add_listener(self, callback: Callable[[WorkflowEvent], None]) -> None:
        """Add a global listener that receives all events (sync, for TaskManager)."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[WorkflowEvent], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def emit(self, task_id: str, event: WorkflowEvent) -> None:
        if task_id in self._deleted_tasks:
            return
        self._history.setdefault(task_id, deque(maxlen=self._history_size)).append(event)
        self._persist_event(task_id, event)
        # Notify global listeners (sync callbacks, e.g. TaskManager progress update)
        for cb in self._listeners:
            try:
                cb(event)
            except Exception as e:
                print(f"[EventBus] listener error: {e}")
        subs = self._subscribers.get(task_id, [])
        print(f"[EventBus] emit {event.type.value} for {task_id}, subscribers={len(subs)}")
        for cb in subs:
            try:
                await cb(event)
            except Exception as e:
                print(f"[EventBus] subscriber error: {e}")

    def subscribe(self, task_id: str, callback: Callable[[WorkflowEvent], Awaitable[None]]) -> None:
        if task_id in self._deleted_tasks:
            return
        self._subscribers.setdefault(task_id, []).append(callback)

    def unsubscribe(self, task_id: str, callback: Callable[[WorkflowEvent], Awaitable[None]]) -> None:
        subs = self._subscribers.get(task_id, [])
        if callback in subs:
            subs.remove(callback)

    def get_history(self, task_id: str) -> list[dict]:
        if task_id in self._deleted_tasks:
            return []
        # Prefer in-memory (live session); fall back to disk (after restart)
        if task_id in self._history:
            return [e.model_dump(mode="json") for e in self._history[task_id]]
        return self._load_history_from_disk(task_id)

    def _persist_event(self, task_id: str, event: WorkflowEvent) -> None:
        _TASKS_DIR.mkdir(parents=True, exist_ok=True)
        path = _TASKS_DIR / f"{task_id}_events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def _load_history_from_disk(self, task_id: str) -> list[dict]:
        path = _TASKS_DIR / f"{task_id}_events.jsonl"
        if not path.is_file():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # Cache in memory so subsequent calls don't re-read
        self._history[task_id] = deque(
            [WorkflowEvent(**e) for e in events], maxlen=self._history_size
        )
        return events

    def clear_task(self, task_id: str) -> None:
        """Forget a deleted task and reject late events from its cancelled job."""
        self.mark_task_deleted(task_id)
        self.purge_task(task_id)

    def purge_task(self, task_id: str) -> None:
        """Remove task history and subscribers without creating a tombstone."""
        self._history.pop(task_id, None)
        self._subscribers.pop(task_id, None)

    def mark_task_deleted(self, task_id: str) -> None:
        """Reject new events while task cancellation and cleanup are in progress."""
        self._deleted_tasks.add(task_id)
