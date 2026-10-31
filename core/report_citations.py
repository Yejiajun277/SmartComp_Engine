"""Readable citation display without rewriting saved report facts or HTML tags."""
import html
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit


_MARKERS = re.compile(r"\[([^\[\]\r\n<>]+)\]")
_SOURCE_ID = re.compile(r"[^\[\]\r\n<>]+?:(?:q\d+|intro_sup_\d+|sup_[a-z_]+_\d+):r\d+\Z")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def citation_ids_in_marker(value: str) -> list[str]:
    """Only citation-shaped brackets qualify; dates and ordinary labels do not."""
    parts = [part.strip() for part in re.split(r"[,，;；]", html.unescape(value))]
    return parts if parts and all(_SOURCE_ID.fullmatch(part) for part in parts) else []


def extract_inline_citation_ids(text: str) -> list[str]:
    return [cid for match in _MARKERS.finditer(text)
            for cid in citation_ids_in_marker(match.group(1))]


def _web_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


class _ReportScan(HTMLParser):
    """Record original offsets, so untouched markup is preserved byte for byte."""
    def __init__(self, markup: str):
        super().__init__(convert_charrefs=False)
        self.markup = markup
        self.lines = [0]
        self.lines.extend(match.end() for match in re.finditer("\n", markup))
        self.stack = []
        self.regions = []
        self.anchors = {}
        self.numbers = {}
        self.link_numbers = {}
        self.number_nodes = []
        self.linked_ids = []
        self.source_urls = {}
        self.body_end = len(markup)
        self.feed(markup)
        self.close()

    def _position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        anchor = values.get("id", "")
        anchor = anchor[5:] if anchor.startswith("cite-") else None
        if anchor:
            self.anchors.setdefault(anchor, self._position())
        href = values.get("href", "") or ""
        target = href[6:] if tag == "a" and href.startswith("#cite-") else None
        if target:
            self.linked_ids.append(target)
        if tag == "a" and _web_url(href):
            for frame in self.stack:
                if frame["anchor"]:
                    self.source_urls.setdefault(frame["anchor"], href)
        frame = {"tag": tag, "anchor": anchor, "target": target, "text": [], "segments": [],
                 "skip": tag in {"a", "script", "style"}
                 or values.get("data-report-citations") == "supplemental"}
        if tag not in _VOID:
            self.stack.append(frame)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "body":
            self.body_end = self._position()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                for frame in self.stack[i:]:
                    if frame["target"]:
                        number = re.fullmatch(r"\s*\[(\d+)\]\s*", "".join(frame["text"]))
                        if number:
                            self.link_numbers.setdefault(frame["target"], int(number.group(1)))
                            for start, end, text in frame["segments"]:
                                if re.fullmatch(r"\s*\[\d+\]\s*", text):
                                    self.number_nodes.append((start, end, frame["target"], text))
                del self.stack[i:]
                break

    def _text(self, data, length):
        start = self._position()
        end = start + length
        for frame in self.stack:
            if frame["target"]:
                frame["text"].append(data)
                frame["segments"].append((start, end, data))
            if frame["anchor"] and (number := re.match(r"^\s*\[(\d+)\](?:\s|$)", data)):
                self.numbers.setdefault(frame["anchor"], int(number.group(1)))
        if any(frame["skip"] for frame in self.stack):
            return
        if self.regions and self.regions[-1][1] == start:
            self.regions[-1] = (self.regions[-1][0], end)
        else:
            self.regions.append((start, end))

    def handle_data(self, data):
        self._text(data, len(data))

    def handle_entityref(self, name):
        start = self._position()
        token = re.match(r"&" + re.escape(name) + r";?", self.markup[start:]).group()
        self._text(token, len(token))

    def handle_charref(self, name):
        start = self._position()
        token = re.match(r"&#" + re.escape(name) + r";?", self.markup[start:]).group()
        self._text(token, len(token))


def normalize_report_citations(markup: str, citations: dict | None = None) -> str:
    """Resolve inline IDs to real saved sources without rewriting report prose.

    Source dictionaries are optional: old HTML can reuse its existing appendix.
    Unknown IDs get a visible unmatched marker; no citation is invented.
    Existing link attributes and structure stay intact. Only pure numeric citation
    labels may be corrected to match their actual appendix target.
    """
    if not markup:
        return markup
    scan = _ReportScan(markup)
    sources = citations if isinstance(citations, dict) else {}
    numbers = {cid: scan.numbers.get(cid, scan.link_numbers.get(cid)) for cid in scan.anchors}
    next_number = max([0, *scan.numbers.values(), *scan.link_numbers.values()]) + 1
    resolved = {}
    pending = {}
    insertions = {}
    url_targets = {}
    for cid in scan.anchors:
        source = sources.get(cid)
        url = source.get("url", "") if isinstance(source, dict) else ""
        url = url or scan.source_urls.get(cid, "")
        if url:
            url_targets.setdefault(url.strip(), cid)

    def number_for(cid):
        nonlocal next_number
        if not numbers.get(cid):
            numbers[cid] = scan.link_numbers.get(cid) or next_number
            next_number = max(next_number, numbers[cid] + 1)
        return numbers[cid]

    def resolve(cid):
        if cid in resolved:
            return resolved[cid]
        if cid in scan.anchors:
            result = (cid, number_for(cid))
        else:
            source = sources.get(cid)
            source = source if isinstance(source, dict) else {}
            url = str(source.get("url", "") or "").strip()
            title = str(source.get("title", "") or "").strip()
            target = url_targets.get(url) if url else None
            if target:
                result = (target, number_for(target))
            elif title or url:
                pending[cid] = (title, url)
                result = (cid, number_for(cid))
                if url:
                    url_targets[url] = cid
            else:
                result = None
        resolved[cid] = result
        return result

    # Historical reports can already contain alias links whose source appendix
    # deduplicated their URL. Add a true alias target without changing that link.
    for cid in dict.fromkeys(scan.linked_ids):
        result = resolve(cid)
        if result and result[0] != cid and cid not in scan.anchors:
            target = result[0]
            alias = f'<span id="{html.escape("cite-" + cid, quote=True)}"></span>'
            position = scan.anchors.get(target, scan.body_end)
            insertions[position] = insertions.get(position, "") + alias

    def replace(match):
        ids = citation_ids_in_marker(match.group(1))
        if not ids:
            return match.group(0)
        parts = []
        for cid in ids:
            result = resolve(cid)
            if result:
                target, number = result
                parts.append(
                    f'<sup><a href="{html.escape("#cite-" + target, quote=True)}" '
                    f'style="color:#3b82f6;text-decoration:none;font-size:11px;">[{number}]</a></sup>')
            else:
                parts.append('<sup class="citation-unmatched" title="' +
                             html.escape("未找到保存的引用来源：" + cid, quote=True) +
                             '" style="color:#b45309;">[来源未匹配]</sup>')
        return "".join(parts)

    edits = []
    for start, end, cid, text in scan.number_nodes:
        result = resolve(cid)
        if result:
            corrected = re.sub(r"(?<=\[)\d+(?=\])", str(result[1]), text)
            if corrected != text:
                edits.append((start, end, corrected))
    for start, end in scan.regions:
        original = markup[start:end]
        changed = _MARKERS.sub(replace, original)
        if changed != original:
            edits.append((start, end, changed))
    if pending:
        items = []
        for cid, (title, url) in pending.items():
            label = html.escape(title or url)
            if _web_url(url):
                label = (f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                         f'rel="noopener noreferrer">{label}</a>')
            elif url:
                label += " — " + html.escape(url)
            items.append(f'<div id="{html.escape("cite-" + cid, quote=True)}">'
                         f'<span>[{number_for(cid)}]</span> {label}</div>')
        appendix = ('<section data-report-citations="supplemental" '
                    'style="margin:24px;padding:20px;background:#fff;border-radius:12px;">'
                    '<h2 style="font-size:18px;">补充引用来源</h2>' + "".join(items) + '</section>')
        insertions[scan.body_end] = insertions.get(scan.body_end, "") + appendix
    edits.extend((position, position, value) for position, value in insertions.items())
    for start, end, replacement in sorted(edits, reverse=True):
        markup = markup[:start] + replacement + markup[end:]
    return markup
