"""Explicit live-case submission and read-only structural acceptance.

Usage: python scripts/validate_competitor_generalization.py --help
The start action makes real model/search calls. It refuses to overwrite a case
record, so polling cannot accidentally submit another paid task. Semantic
category relevance must also be reviewed by a human; this does not certify facts.
"""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request


CASES = {
    "vacuum": "戴森 Dyson V15 Detect 无绳吸尘器，中国家用清洁市场",
    "hotel": "全季酒店住宿服务，中国商旅市场",
    "music": "Spotify 音乐流媒体订阅服务，美国个人用户市场",
}
INTERNAL = re.compile(r"\[[^\[\]\r\n<>]+:(?:q\d+|intro_sup_\d+|sup_[a-z_]+_\d+):r\d+\]")


def request(base, path, payload=None):
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        text = response.read().decode("utf-8")
    return text if path.endswith(".html") else json.loads(text)


class VisibleReport(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.ids, self.hidden = [], [], set(), 0
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.hidden += 1
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#cite-"):
            self.links.append(attrs["href"][1:])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def audit(base, task_id):
    task = request(base, f"/api/tasks/{task_id}")
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(task["status"] == "completed", "Task did not complete")
    check(task["skip_qa"] is False and task["use_rule_engine"] is False,
          "Real model and QA must be enabled")
    check(task["max_competitors"] == 3 and task.get("llm_provider") == "mimo",
          "Expected three competitors with MiMo")
    if task["status"] != "completed":
        return {"pass": False, "task": task, "errors": errors}
    data = {phase: request(base, f"/api/tasks/{task_id}/artifacts/{phase}")
            for phase in ("collection", "dimension", "product", "pricing", "qa")}
    report = request(base, f"/api/tasks/{task_id}/report")
    html = request(base, f"/api/tasks/{task_id}/report.html")
    visible = VisibleReport(html)
    text = "".join(visible.text)
    entities = [report["product_name"], *data["collection"]]
    dimension_lists = {}
    for kind, field in (("product", "feature_matrix"), ("pricing", "dimension_comparison")):
        expected = [d["name"] for d in data["dimension"][kind + "_sub_dimensions"]]
        rows = data[kind][field]
        dimension_lists[kind] = expected
        check(4 <= len(expected) <= 6, f"{kind}: live model dimensions missing")
        check([row["feature"] for row in rows] == expected, f"{kind}: matrix differs from generated dimensions")
        for row in rows:
            check(set(row["values"]) == set(entities), f"{kind}/{row['feature']}: entity columns incomplete")
            check(row["feature"] in text, f"{kind}/{row['feature']}: absent from HTML")
            check(all(isinstance(v, str) and v.strip() for v in row["values"].values()),
                  f"{kind}/{row['feature']}: empty or invalid cell")
    check(len(entities) == 4, "Expected target plus three rivals")
    check(not INTERNAL.search(text), "Internal citation identifier visible")
    check(not (set(visible.links) - visible.ids), "Broken citation anchor")
    check(len(visible.links) > 0, "No reference links")
    checks = {entry["phase"]: entry for entry in data["qa"]["checks"]}
    for phase in ("collection", "product", "pricing", "market", "strategy"):
        last = checks.get(phase, {})
        check(last.get("passed") is True and not last.get("degraded", False), f"{phase}: last QA did not pass")
        check(last.get("hallucination_status") in ("passed", "found"),
              f"{phase}: semantic review did not complete")
        check(not any(i.get("severity") == "critical" for i in last.get("issues", [])),
              f"{phase}: unresolved critical QA issue")
    sources = report.get("citation_index", {}).get("citations", {})
    check(bool(sources), "No collected sources")
    return {"pass": not errors, "task_id": task_id, "product_name": report["product_name"],
            "entities": entities, "dimensions": dimension_lists,
            "qa": {phase: {key: result.get(key) for key in ("passed", "score", "attempt", "hallucination_status", "issues")}
                   for phase, result in checks.items()},
            "source_count": len(sources), "citation_links": len(visible.links),
            "errors": errors, "semantic_review_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "audit"))
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--records", type=Path, default=Path("output/generalization-validation"))
    args = parser.parse_args()
    args.records.mkdir(parents=True, exist_ok=True)
    record = args.records / (args.case + ".json")
    if args.action == "start":
        with record.open("x", encoding="utf-8") as destination:
            # Reserve before POST. If transport fails, inspect server history before
            # explicitly clearing the reservation; never blindly resubmit.
            response = request(args.base_url, "/api/tasks", {
                "product_description": CASES[args.case], "max_competitors": 3,
                "skip_qa": False, "use_rule_engine": False})
            json.dump(response, destination, ensure_ascii=False, indent=2)
        print(json.dumps(response, ensure_ascii=False))
        return
    task_id = json.loads(record.read_text(encoding="utf-8"))["task_id"]
    result = (audit(args.base_url, task_id) if args.action == "audit"
              else request(args.base_url, f"/api/tasks/{task_id}"))
    if args.action == "audit":
        (args.records / (args.case + "-audit.json")).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action == "audit" and not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
