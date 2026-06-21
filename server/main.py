# -*- coding: utf-8 -*-
"""FastAPI application entry point."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Add project root to sys.path so we can import existing modules
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.routers import tasks as tasks_router
from server.routers import ws as ws_router
from server.services.event_bus import EventBus
from server.services.task_manager import TaskManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create shared services
    event_bus = EventBus()
    task_manager = TaskManager(event_bus)
    app.state.event_bus = event_bus
    app.state.task_manager = task_manager
    yield
    # Shutdown: nothing to clean up (in-memory)


app = FastAPI(title="SmartComp Engine", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router.router)
app.include_router(ws_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve frontend static files (production mode)
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve SPA - all non-API routes return index.html for client-side routing."""
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_frontend_dist / "index.html")
