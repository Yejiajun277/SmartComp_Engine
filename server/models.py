# -*- coding: utf-8 -*-
"""Pydantic models for the API server."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    QA_CHECK_STARTED = "qa_check_started"
    QA_CHECK_PASSED = "qa_check_passed"
    QA_CHECK_FAILED = "qa_check_failed"
    QA_RETRYING = "qa_retrying"
    PROGRESS_UPDATE = "progress_update"


class WorkflowEvent(BaseModel):
    type: EventType
    task_id: str
    agent: str
    phase: str
    status: str  # running | completed | failed | retrying
    progress: float = 0.0
    message: str = ""
    data: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class TaskCreateRequest(BaseModel):
    product_description: str
    max_competitors: int = 5
    skip_qa: bool = False
    use_rule_engine: bool = False


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str


class TaskSummary(BaseModel):
    id: str
    product_description: str
    max_competitors: int
    status: str
    current_agent: str | None = None
    progress: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
