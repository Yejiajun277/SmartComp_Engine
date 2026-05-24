# -*- coding: utf-8 -*-
"""
core/run_store.py - 运行产物与 trace 持久化
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent / "runs"


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def ensure_run_dirs(run_id: str) -> dict[str, Path]:
    root = BASE_DIR / run_id
    trace_dir = root / "trace"
    artifact_dir = root / "artifacts"
    report_dir = root / "report"
    for item in (trace_dir, artifact_dir, report_dir):
        item.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "trace": trace_dir,
        "artifacts": artifact_dir,
        "report": report_dir,
    }


def write_json(path: Path, data: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def write_text(path: Path, data: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return str(path)


def write_trace(run_id: str, node: str, attempt: int, data: dict[str, Any]) -> str:
    dirs = ensure_run_dirs(run_id)
    safe_node = slugify(node)
    path = dirs["trace"] / f"{attempt:02d}_{safe_node}.json"
    return write_json(path, data)


def write_artifact(run_id: str, name: str, data: Any) -> str:
    dirs = ensure_run_dirs(run_id)
    path = dirs["artifacts"] / f"{slugify(name)}.json"
    return write_json(path, data)


def write_report_files(run_id: str, product_name: str, report_json: dict[str, Any], html: str) -> dict[str, str]:
    dirs = ensure_run_dirs(run_id)
    stem = slugify(product_name) or "competitive_analysis"
    json_path = dirs["report"] / f"{stem}_analysis_report.json"
    html_path = dirs["report"] / f"{stem}_analysis_report.html"
    return {
        "json": write_json(json_path, report_json),
        "html": write_text(html_path, html),
    }


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value or "", flags=re.UNICODE).strip("_")
    return cleaned or "artifact"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
