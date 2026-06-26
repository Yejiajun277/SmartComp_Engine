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
    LLM_LOGS_UPDATED = "llm_logs_updated"
    INTERVENTION_REQUIRED = "intervention_required"
    INTERVENTION_SUBMITTED = "intervention_submitted"


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
    enable_human_review: bool = False


class DescriptionEvaluateRequest(BaseModel):
    """描述质量评估请求。"""
    product_description: str


class DescriptionQuestion(BaseModel):
    """LLM生成的补充问题。"""
    question: str = Field(description="问题文本")
    field: str = Field(description="对应的字段名，如 category/features/target_users")
    options: list[str] | None = Field(default=None, description="选择题选项，None表示开放式问题")


class DescriptionEvaluateResponse(BaseModel):
    """描述质量评估响应。"""
    quality_score: float = Field(description="质量分数 0-1")
    quality: str = Field(description="good | insufficient")
    missing_dimensions: list[str] = Field(default=[], description="缺失的维度")
    questions: list[DescriptionQuestion] = Field(default=[], description="补充问题列表")


class InterventionResponse(BaseModel):
    """用户提交的人工介入决策。"""
    action: str = Field(description="approve | reject | edit")
    feedback: str = Field(default="", description="打回时的反馈意见")
    edited_competitors: list[dict] | None = Field(default=None, description="编辑后的竞品列表")
    edited_competitors_data: dict | None = Field(default=None, description="编辑后的采集数据")


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
    enable_human_review: bool = False
    pending_intervention: str | None = None  # competitor_confirm | data_review | None
