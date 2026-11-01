"""Legacy report display fixes must leave saved evidence and JSON untouched."""
import copy
from html.parser import HTMLParser
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers.tasks import router


class VisibleText(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.parts = []
        self.feed(markup)

    def handle_data(self, data):
        self.parts.append(data)


class LegacyReportCitationApiTests(unittest.TestCase):
    def serve(self, markup, report=None, status="completed"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.html"
            path.write_text(markup, encoding="utf-8")
            before = path.read_bytes()
            saved = copy.deepcopy(report or {})
            task = SimpleNamespace(status=status, html_report_path=str(path), report_json=saved)
            app = FastAPI()
            app.include_router(router)
            app.state.task_manager = SimpleNamespace(get=lambda task_id: task if task_id == "saved" else None)
            with TestClient(app) as client:
                response = client.get("/api/tasks/saved/report.html")
                json_response = client.get("/api/tasks/saved/report")
                missing = client.get("/api/tasks/missing/report.html")
            self.assertEqual(path.read_bytes(), before, "Viewing a report must not rewrite saved HTML")
            self.assertEqual(saved, report or {}, "Viewing a report must not rewrite its evidence")
            self.assertEqual(missing.status_code, 404)
            return response, json_response

    def test_saved_report_resolves_inline_id_without_changing_raw_html_or_json(self):
        cid = "iPhone DUO:q0:r0"
        summary = f"内屏镜头隐藏于面板下方 [{cid}]。"
        markup = (
            '<html><body><div data-source="' + cid + '">'
            '<h3>屏下镜头<sup><a href="#cite-' + cid + '">[1]</a></sup></h3>'
            '<p>' + summary + '</p></div><div id="cite-' + cid + '">'
            '<span>[1]</span><a href="https://example.test/source">产品资料</a></div></body></html>'
        )
        report = {"target_product_intro": {"core_capabilities": [{"summary": summary, "citations": [cid]}]},
                  "citation_index": {"citations": {cid: {"id": cid, "url": "https://example.test/source", "title": "产品资料"}}}}
        response, json_response = self.serve(markup, report)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("[" + cid + "]", "".join(VisibleText(response.text).parts))
        self.assertIn('href="#cite-' + cid + '"', response.text)
        self.assertIn('data-source="' + cid + '"', response.text)
        self.assertEqual(json_response.json(), report)

    def test_unknown_reference_is_explicit_instead_of_exposing_internal_id(self):
        response, _ = self.serve('<html><body><p>仍需核实 [未知品牌:q9:r9]。</p></body></html>')
        self.assertEqual(response.status_code, 200)
        visible = "".join(VisibleText(response.text).parts)
        self.assertIn("来源未匹配", visible)
        self.assertNotIn("未知品牌:q9:r9", visible)
        self.assertIn("仍需核实", visible)

    def test_existing_plain_report_and_noncompleted_status_keep_their_contract(self):
        markup = "<html><body><p>[2026] 配置为 [256GB]。</p></body></html>"
        response, _ = self.serve(markup)
        self.assertEqual(response.text, markup)
        response, _ = self.serve(markup, status="running")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
