# -*- coding: utf-8 -*-
"""
api_server.py - 最小后端接口与静态演示页服务
"""

from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import config
from core.run_store import BASE_DIR, load_json
from models.domain import to_dict
from workflow.graph import run_analysis_graph


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._serve_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
        if parsed.path.startswith("/static/"):
            return self._serve_file(WEB_ROOT / parsed.path.removeprefix("/static/"), "text/plain; charset=utf-8")
        if parsed.path == "/api/runs":
            return self._list_runs()
        if parsed.path.startswith("/api/runs/"):
            return self._get_run(parsed.path)
        return self._json_response({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/runs":
            return self._json_response({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length) or "{}")
        use_llm = bool(payload.get("use_llm", True))
        config.ENABLE_LLM = use_llm
        state = asyncio.run(
            run_analysis_graph(
                product_description=str(payload.get("product_description", "")).strip(),
                max_competitors=int(payload.get("max_competitors", config.DEFAULT_COMPETITOR_COUNT)),
                use_llm=use_llm,
                focus_topics=list(payload.get("focus_topics", [])),
            )
        )
        report = state.get("report")
        response = {
            "run_id": state.get("run_id", ""),
            "status": state.get("status", "success"),
            "trace_summary": state.get("trace_summary", {}),
            "report_paths": state.get("report_paths", {}),
            "report": to_dict(report) if report else None,
        }
        return self._json_response(response)

    def _list_runs(self):
        runs = []
        if BASE_DIR.exists():
            for item in sorted(BASE_DIR.iterdir(), reverse=True):
                if item.is_dir():
                    summary_path = item / "artifacts" / "run_summary.json"
                    status = "unknown"
                    if summary_path.exists():
                        status = load_json(summary_path).get("final_status", "unknown")
                    runs.append({"run_id": item.name, "status": status})
        return self._json_response({"runs": runs})

    def _get_run(self, path: str):
        parts = path.strip("/").split("/")
        if len(parts) < 3:
            return self._json_response({"error": "bad_request"}, HTTPStatus.BAD_REQUEST)
        run_id = parts[2]
        run_root = BASE_DIR / run_id
        if not run_root.exists():
            return self._json_response({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        if len(parts) == 3:
            summary_path = run_root / "artifacts" / "run_summary.json"
            report_path = next((run_root / "report").glob("*_analysis_report.json"), None)
            traces = []
            for trace_file in sorted((run_root / "trace").glob("*.json")):
                traces.append(load_json(trace_file))
            return self._json_response(
                {
                    "run_id": run_id,
                    "summary": load_json(summary_path) if summary_path.exists() else {},
                    "report": load_json(report_path) if report_path else {},
                    "traces": traces,
                }
            )
        if len(parts) == 4 and parts[3] == "report":
            report_path = next((run_root / "report").glob("*_analysis_report.json"), None)
            if report_path is None:
                return self._json_response({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return self._json_response(load_json(report_path))
        if len(parts) == 4 and parts[3] == "html":
            html_path = next((run_root / "report").glob("*_analysis_report.html"), None)
            if html_path is None:
                return self._json_response({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return self._serve_file(html_path, "text/html; charset=utf-8")
        if len(parts) == 4 and parts[3] == "trace":
            traces = [load_json(trace_file) for trace_file in sorted((run_root / "trace").glob("*.json"))]
            return self._json_response({"run_id": run_id, "traces": traces})
        return self._json_response({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists():
            return self._json_response({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = "127.0.0.1", port: int = 8000):
    server = ThreadingHTTPServer((host, port), DemoHandler)
    print(f"Server running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    serve()
