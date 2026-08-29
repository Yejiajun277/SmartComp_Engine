# -*- coding: utf-8 -*-
"""Pydantic models for the API server."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

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
    LLM_LOGS_UPDATED = "llm_logs_updated"


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


class RuntimeProviderStatus(BaseModel):
    configured: bool
    provider: str
    model: str | None = None


class RuntimeConfigResponse(BaseModel):
    llm: RuntimeProviderStatus
    search: RuntimeProviderStatus
    default_mode: Literal["model", "rule"]


class TaskSummary(BaseModel):
    id: str
    product_description: str
    max_competitors: int
    skip_qa: bool
    use_rule_engine: bool
    llm_provider: str | None = None
    llm_model: str | None = None
    status: str
    current_agent: str | None = None
    progress: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
