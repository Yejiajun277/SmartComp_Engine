# -*- coding: utf-8 -*-
"""Read-only, secret-free runtime configuration endpoint."""

from __future__ import annotations

from fastapi import APIRouter

import config
from server.models import RuntimeConfigResponse, RuntimeProviderStatus

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("", response_model=RuntimeConfigResponse)
async def get_runtime_config() -> RuntimeConfigResponse:
    llm_configured = bool(config.MIMO_API_KEY.strip())
    search_configured = bool(config.TAVILY_API_KEY.strip())

    return RuntimeConfigResponse(
        llm=RuntimeProviderStatus(
            configured=llm_configured,
            provider=config.LLM_PROVIDER,
            model=config.MIMO_MODEL if llm_configured else None,
        ),
        search=RuntimeProviderStatus(
            configured=search_configured,
            provider="tavily",
        ),
        default_mode="model" if llm_configured else "rule",
    )
