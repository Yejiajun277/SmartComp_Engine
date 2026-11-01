"""Category-specific pricing comparisons with bounded, evidence-safe recovery."""
from dataclasses import asdict, dataclass, field
import json
import re
from agents.base_agent import BaseAgent
from models.domain import CompetitorData, FeatureComparison, PricingAnalysis, PricingItem
from core.prompt_loader import load as load_prompts
import config

UNKNOWN = "资料不足"
_SOURCE_LIMIT = re.compile(r"标题|原文截断|表述不完整|原文不完整|不详|未注明|未披露|未知|仅供参考|另有来源|据另一来源")
_NOT_COMPARABLE = re.compile(
    r"(?:不可|不能|不宜|无法)[^。；;\n]{0,12}(?:比较|排名|排序)|不具可比性|not\s+(?:directly\s+)?comparable|cannot\s+rank|incomparable", re.I)
_US_REGION = re.compile(
    r"美国|美國|美区|美區|(?<![A-Za-z0-9_])(?:United\s+States(?:\s+of\s+America)?|USA|U\.S\.A\.|U\.S\.|US)(?![A-Za-z0-9_]|\$)", re.I)
_PRICE_COMPARISON = re.compile(
    r"排名|排序|性价比|价差|价[格位]?梯度|更[便宜贵低高优]|最[便宜贵低高优]|低于|高于|领先|优于|便宜|昂贵|"
    r"\b(?:rank\w*|cheap\w*|cheapest|pricier|cheaper|expensive|best|worst|better|worse|higher|lower)\b|\bvalue\s+(?:for\s+money|leader)\b", re.I)
_COMPARISON_GAP = "未确认同一市场、日期、规格/权益和计价单位的可比报价；仅展示来源报价与限制，不可直接排名。"
_CURRENCY_CODES = r"USD|CNY|EUR|GBP|JPY|HKD|TWD|AUD|CAD|NZD|SGD|CHF"
_MONEY_TOKEN = re.compile(
    r"(?:US\$|(?<![A-Za-z])(?:" + _CURRENCY_CODES + r")(?![A-Za-z])|[$€£¥￥])\s*(\d+(?:[,.]\d+)*)"
    r"|(\d+(?:[,.]\d+)*)\s*(?:(?:" + _CURRENCY_CODES + r")(?![A-Za-z])|美元|人民币|日元|欧元|英镑|港元|港币|新台币|元)", re.I)

@dataclass
class _PricingBatch:
    analysis: PricingAnalysis
    notes: list[tuple[tuple[str, ...], str, str]] = field(default_factory=list)

class PricingAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("pricing_agent")
        self._system_prompt_template = prompts["system_prompt"]
        self._prompt_analyze = prompts["prompt_analyze"]
        super().__init__(agent_id="PricingAgent", system_prompt=self._system_prompt_template)

    def set_sub_dimensions(self, text: str):
        self.system_prompt = self._system_prompt_template.format(sub_dimensions=text)

    @staticmethod
    def _dimension_names(text: str) -> list[str]:
        names = []
        for line in text.splitlines():
            line = re.sub(r"^\s*(?:\d+[.)、]\s*|[-*]\s+)", "", line).strip()
            if not line:
                continue
            bold = re.match(r"\*\*(.+?)\*\*", line)
            name = (bold.group(1) if bold else re.split(r"[：:]", line, maxsplit=1)[0]).strip()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _canonical_feature(value: str, names: list[str]) -> str | None:
        value = value.strip()
        for name in names:
            if value.casefold() == name.casefold():
                return name
        for name in sorted(names, key=len, reverse=True):
            if value.casefold().startswith(name.casefold()):
                suffix = value[len(name):]
                if suffix and suffix[0] in "（(:：[【 —–-":
                    return name
        return None

    @staticmethod
    def _known(value) -> bool:
        return isinstance(value, str) and value.strip() not in {"", UNKNOWN, "未知", "暂无公开信息", "暂无数据", "⚪", "—"}

    @staticmethod
    def _amounts(text):
        return set(re.findall(r"\d+(?:[,.]\d+)*", text))

    @staticmethod
    def _money_amounts(text):
        return {value for match in _MONEY_TOKEN.finditer(text) for value in match.groups() if value}

    @staticmethod
    def _offering_matches(label, sentence):
        """Require an offering label, not a prefix of a longer priced offering.

        Keep word separators so 'Individual Plus' cannot become 'Individual'.
        Only ordinary quote grammar may follow the label before the amount;
        an unrecognised model modifier remains an unconfirmed binding. This
        deliberately does not guess that two different offering names are aliases.
        """
        words = re.findall(r"\w+", label)
        if not words:
            return False
        pattern = r"[\W_]*".join(re.escape(word) for word in words)
        if words[0][0].isascii() and words[0][0].isalnum():
            pattern = r"(?<![A-Za-z0-9_])" + pattern
        for match in re.finditer(pattern, sentence, re.I):
            tail = sentence[match.end():]
            price = next(_MONEY_TOKEN.finditer(tail), None)
            if price is None:
                continue
            gap = tail[:price.start()]
            gap = _US_REGION.sub("", gap)
            gap = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", gap)
            gap = re.sub(r"\b(?:plan|package|tier|sku|price|priced|cost|costs|at|is|now|in|the|for)\b", "", gap, flags=re.I)
            gap = re.sub(r"价格|價格|报价|報價|售价|售價|定价|定價|套餐|方案|每台|每月|为|為|在", "", gap)
            if not re.sub(r"[\W_]", "", gap):
                return True
        return False

    @classmethod
    def _quote_sentences(cls, data, tier, citation_ids):
        """Return source sentences tied to this offering and original amount."""
        amounts = cls._money_amounts(tier.price)
        label = re.split(r"[（(]", _US_REGION.sub("", tier.tier_name), maxsplit=1)[0].strip()
        if not amounts or not label:
            return []
        sources = {cite.id: cite for cite in data.citations}
        result = []
        for cid in citation_ids:
            cite = sources.get(cid)
            if cite is None:
                continue
            # Do not borrow a region from an unrelated paragraph of a source.
            for sentence in re.split(r"[。；;\n]|(?<!\d)\.(?!\d)", cite.snippet):
                # A sentence listing multiple prices cannot establish which
                # offering owns a later region/date. Keep its raw quote, but
                # do not combine those clauses into a common comparison basis.
                if sum(1 for _ in _MONEY_TOKEN.finditer(sentence)) != 1:
                    continue
                if amounts <= cls._money_amounts(sentence) and cls._offering_matches(label, sentence):
                    result.append(sentence)
        return result

    @classmethod
    def _price_has_us_scope(cls, data, tier, citation_ids):
        """A dollar sign, search query or another tier is never a country."""
        return any(_US_REGION.search(sentence) for sentence in cls._quote_sentences(data, tier, citation_ids))

    @classmethod
    def _bound_region(cls, text, data, citation_ids=None):
        if not _US_REGION.search(text):
            return text
        amounts = cls._amounts(text)
        selected = [tier for tier in data.pricing_tiers if amounts & cls._amounts(tier.price)]
        if not re.search(r"\$|USD|美元", text + " ".join(tier.price for tier in selected), re.I):
            return text
        if not selected:
            return _US_REGION.sub("美元计价（来源未注明地区）", text)
        for tier in selected:
            ids = [cid for cid in tier.citations if citation_ids is None or cid in citation_ids]
            if not cls._price_has_us_scope(data, tier, ids):
                return _US_REGION.sub("美元计价（来源未注明地区）", text)
        return text

    @classmethod
    def _scope_notes(cls, references):
        notes = {}
        for entity, data in references.items():
            original = []
            for tier in data.pricing_tiers:
                # Keep every native quote's scope, not just lines containing a
                # few uncertainty keywords. These are collected terms, not a
                # newly inferred current-market offer.
                line = f"{tier.tier_name}: {tier.price}"
                original.append(cls._bound_region(line, data, tier.citations))
                original.extend(tier.features)
                ids = [cid for cid in tier.citations if any(cite.id == cid for cite in data.citations)]
                original.append("报价来源：" + (" ".join(f"[{cid}]" for cid in ids) if ids else "资料不足，未绑定有效来源"))
            if original:
                notes[entity] = list(dict.fromkeys(original))
        return notes

    @staticmethod
    def _without_comparisons(text):
        # Price facts remain in the source-bound native quote notes. Do not
        # leave a softer ranking in a cell after rejecting the ranking array.
        parts = re.split(r"(?<=[。；;！!?？])|\n", text)
        return "".join(part for part in parts if not _PRICE_COMPARISON.search(part)).strip() or UNKNOWN

    def _enforce_scope(self, analysis, references, basis):
        for row in analysis.dimension_comparison:
            for entity, value in row.values.items():
                if entity in references:
                    value = self._bound_region(value, references[entity], row.citations or None)
                row.values[entity] = value if basis else self._without_comparisons(value)
        for item in analysis.pricing_comparison:
            for name in ("free_tier", "paid_tier", "pricing_model"):
                value = getattr(item, name)
                if item.competitor in references:
                    value = self._bound_region(value, references[item.competitor], item.citations or None)
                setattr(item, name, value if basis or not value else self._without_comparisons(value))
        if not basis:
            original = analysis.summary + " " + analysis.pricing_strategy_analysis
            diagnostics = [word for word in ("降级", "截断", "格式异常") if word in original]
            analysis.value_ranking = []
            analysis.summary = ("、".join(diagnostics) + "；" if diagnostics else "") + _COMPARISON_GAP
            analysis.pricing_strategy_analysis = "各报价的原始规格、价格、条件及来源单独保留；现有证据不足以形成跨品牌价格优劣或性价比结论。"
        return analysis

    def _validated_basis(self, basis, references):
        """Bind comparison context to the chosen original tier and its sources."""
        fields = ("unit", "currency", "region", "period", "offering_scope")
        if not isinstance(basis, dict) or not references:
            return {}
        if any(not isinstance(basis.get(name), str) or not basis[name].strip()
               or _SOURCE_LIMIT.search(basis[name]) for name in fields):
            return {}
        quotes = basis.get("quotes")
        if not isinstance(quotes, list) or len(quotes) != len(references):
            return {}
        selected = {}
        normalize = lambda value: re.sub(r"\s+", "", value).casefold()
        for quote in quotes:
            if not isinstance(quote, dict) or not isinstance(quote.get("entity"), str):
                return {}
            entity = quote["entity"]
            if entity not in references or entity in selected:
                return {}
            data = references[entity]
            known_sources = {cite.id: cite for cite in data.citations}
            ids = quote.get("citations")
            if not isinstance(ids, list) or not ids or any(
                    not isinstance(cid, str) or cid not in known_sources for cid in ids):
                return {}
            linked = [known_sources[cid] for cid in ids]
            source_text = " ".join(cite.title + " " + cite.snippet for cite in linked)
            supported = False
            for tier in data.pricing_tiers:
                if tier.tier_name != quote.get("tier_name") or tier.price != quote.get("price_text"):
                    continue
                if not self._known(tier.price) or not re.search(r"\d", tier.price):
                    continue
                tier_text = " ".join([tier.tier_name, tier.price, *tier.features])
                if tier.citations:
                    if not set(ids).issubset(set(tier.citations)):
                        continue
                elif not tier.price or normalize(tier.price) not in normalize(source_text):
                    continue
                context = tier_text + " " + source_text
                if _SOURCE_LIMIT.search(context):
                    continue
                if _US_REGION.search(basis["region"]) and not self._price_has_us_scope(data, tier, ids):
                    continue
                if any(all(normalize(basis[name]) in normalize(sentence) for name in fields)
                       for sentence in self._quote_sentences(data, tier, ids)):
                    supported = True
                    break
            if not supported:
                return {}
            selected[entity] = quote
        if set(selected) != set(references):
            return {}
        return {**{name: basis[name].strip() for name in fields}, "quotes": [
            {name: quote[name] for name in ("entity", "tier_name", "price_text", "citations")}
            for quote in quotes]}

    def _complete_analysis(self, analysis, product_name, competitors_data, dimensions, target_product_data=None):
        entities = list(dict.fromkeys([product_name, *competitors_data]))
        rows = {name: FeatureComparison(name, dict.fromkeys(entities, UNKNOWN)) for name in dimensions}
        for incoming in analysis.dimension_comparison:
            name = self._canonical_feature(incoming.feature, dimensions)
            if name is None:
                continue
            row = rows[name]
            for entity, value in incoming.values.items():
                if entity in row.values and self._known(value):
                    row.values[entity] = value.strip()
            row.citations = list(dict.fromkeys([*row.citations, *incoming.citations]))
        analysis.dimension_comparison = list(rows.values())
        items = {item.competitor: item for item in analysis.pricing_comparison if item.competitor in competitors_data}
        analysis.pricing_comparison = [items.get(name, PricingItem(name, paid_tier=UNKNOWN)) for name in competitors_data]
        analysis.value_ranking = list(dict.fromkeys(name for name in analysis.value_ranking if name in competitors_data))
        references = {product_name: target_product_data} if target_product_data is not None else {}
        references.update(competitors_data)
        analysis.source_scope_notes = self._scope_notes(references)
        basis = self._validated_basis(analysis.comparable_basis, references)
        prose = " ".join([analysis.summary, analysis.pricing_strategy_analysis,
                          *(value for row in analysis.dimension_comparison for value in row.values.values())])
        if product_name not in references or _NOT_COMPARABLE.search(prose):
            basis = {}
        analysis.comparable_basis = basis
        self._enforce_scope(analysis, references, basis)
        analysis.citations = list(dict.fromkeys(cid for item in [*analysis.pricing_comparison, *analysis.dimension_comparison] for cid in item.citations))
        return analysis

    async def run(self, product_name: str, competitors_data: dict[str, CompetitorData], target_product_data: CompetitorData | None = None, sub_dimensions: str = "", feedback: str = "") -> PricingAnalysis:
        self._log("💰 开始定价分析...")
        dimensions = self._dimension_names(sub_dimensions)
        self.set_sub_dimensions(sub_dimensions or "本轮没有可确认的定价维度，不生成替代维度。仅保留采集到的报价与缺口。")
        if config.ENABLE_LLM:
            result, truncated = await self._request_analysis(product_name, competitors_data, target_product_data, feedback, 8192)
            if truncated and len(competitors_data) >= 2:
                initial = self._parse_pricing_analysis(result) if result else PricingAnalysis()
                recovered = await self._run_chunked(product_name, competitors_data, target_product_data, feedback, dimensions)
                return self._merge_batches([self._scoped(initial, competitors_data), recovered], product_name, competitors_data, dimensions, replace_parent=True, target_product_data=target_product_data).analysis
            if result:
                analysis = self._parse_pricing_analysis(result)
                if truncated:
                    analysis.summary += "；输出仍截断，降级保留已解析资料，缺口保持未知。"
                return self._complete_analysis(analysis, product_name, competitors_data, dimensions, target_product_data)
        return self._rule_analyze(product_name, competitors_data, target_product_data, dimensions)

    async def _request_analysis(self, product_name, competitors_data, target_product_data, feedback, max_tokens):
        text = self._build_competitors_text(product_name, competitors_data, target_product_data)
        if feedback:
            text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"
        prompt = self._prompt_analyze.format(product_name=product_name, competitors_text=text)
        return await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=max_tokens)

    async def _run_chunked(self, product_name, competitors_data, target_product_data, feedback, dimensions):
        """Retry malformed truncated chunks too; at most2N−2 extra calls."""
        names = list(competitors_data)
        batches = []
        middle = len(names) // 2
        for subset in (names[:middle], names[middle:]):
            chunk = {name: competitors_data[name] for name in subset}
            result, truncated = await self._request_analysis(product_name, chunk, target_product_data, feedback, 4096)
            parsed = self._parse_pricing_analysis(result) if result else PricingAnalysis()
            if truncated and len(chunk) >= 2:
                recovered = await self._run_chunked(product_name, chunk, target_product_data, feedback, dimensions)
                batch = self._merge_batches([self._scoped(parsed, chunk), recovered], product_name, chunk, dimensions, replace_parent=True, target_product_data=target_product_data)
            else:
                if not result:
                    parsed = self._rule_analyze(product_name, chunk, target_product_data, dimensions)
                elif truncated:
                    parsed.summary += "；输出仍截断，降级保留已解析资料，缺口保持未知。"
                batch = self._scoped(parsed, chunk)
            batches.append(batch)
        return self._merge_batches(batches, product_name, competitors_data, dimensions, target_product_data=target_product_data)

    @staticmethod
    def _scoped(analysis, competitors_data):
        return _PricingBatch(analysis, [(tuple(competitors_data), analysis.summary, analysis.pricing_strategy_analysis)])

    def _merge_batches(self, batches, product_name, competitors_data, dimensions, *, replace_parent=False, target_product_data=None):
        items = {}
        for batch in batches:
            for item in batch.analysis.pricing_comparison:
                previous = items.get(item.competitor)
                if previous is None:
                    items[item.competitor] = item
                else:
                    withdraw_free = item.free_tier == "" and self._known(item.paid_tier)
                    items[item.competitor] = PricingItem(item.competitor,
                        *(getattr(item, name) if self._known(getattr(item, name))
                          or (name == "free_tier" and withdraw_free) else getattr(previous, name)
                          for name in ("free_tier", "paid_tier", "pricing_model")),
                        list(dict.fromkeys([*previous.citations, *item.citations])))
        merged = self._complete_analysis(PricingAnalysis(pricing_comparison=list(items.values()), dimension_comparison=[row for batch in batches for row in batch.analysis.dimension_comparison]), product_name, competitors_data, dimensions, target_product_data)
        notes = [note for batch in (batches[1:] if replace_parent else batches) for note in batch.notes]
        if replace_parent:
            parent = batches[0].analysis
            recovered_cells = {(self._canonical_feature(row.feature, dimensions), entity) for batch in batches[1:] for row in batch.analysis.dimension_comparison for entity, value in row.values.items() if self._known(value)}
            retained = {item.competitor for item in parent.pricing_comparison
                if any(self._known(getattr(item, field_name)) and not any(
                    later.competitor == item.competitor and (
                        self._known(getattr(later, field_name)) or
                        (field_name == "free_tier" and later.free_tier == "" and self._known(later.paid_tier)))
                    for batch in batches[1:] for later in batch.analysis.pricing_comparison)
                    for field_name in ("free_tier", "paid_tier", "pricing_model"))}
            retained.update(entity for row in parent.dimension_comparison for entity, value in row.values.items()
                if self._canonical_feature(row.feature, dimensions) and entity in (product_name, *competitors_data)
                and self._known(value) and (self._canonical_feature(row.feature, dimensions), entity) not in recovered_cells)
            parent_notes = []
            for scope, summary, strategy in batches[0].notes:
                kept = tuple(name for name in (product_name, *scope) if name in retained)
                if kept:
                    record = (f"原始批次记录（仅保留{'、'.join(kept)}单元格限定；"
                              f"其余以恢复结果为准，并非当前结论）：{summary}")
                    if strategy:
                        record += f"\n原始策略记录（并非当前结论）：{strategy}"
                    parent_notes.append((kept, record, ""))
            notes = parent_notes + notes
        notes = list(dict.fromkeys(notes))
        unknown = sum(not self._known(value) for row in merged.dimension_comparison for value in row.values.values())
        merged.summary = f"我方{product_name}与{len(competitors_data)}家竞品（{'、'.join(competitors_data)}），共{len(dimensions)}个定价维度，{unknown}格资料不足。"
        for scope, summary, strategy in notes:
            if summary:
                merged.summary += f"\n适用竞品（{'、'.join(scope)}）：{summary}"
            if strategy:
                merged.pricing_strategy_analysis += f"\n适用竞品（{'、'.join(scope)}）：{strategy}"
        if any("降级" in summary for _, summary, _ in notes):
            merged.summary += "部分请求采用降级结果，未知报价不参与推算或排名。"
        merged.summary += "\n分组报价未确认全体同口径，不可直接排名。"
        references = {product_name: target_product_data} if target_product_data is not None else {}
        references.update(competitors_data)
        self._enforce_scope(merged, references, {})
        return _PricingBatch(merged, notes)

    def _build_competitors_text(self, product_name, competitors_data, target_product_data=None):
        lines = []
        def append_entity(name, data):
            lines.append(f"\n### {name}" + ("（我方产品）" if name == product_name else ""))
            lines.append("- 定价信息（含原始规格、权益、条件及引用）: " + json.dumps(
                [asdict(tier) for tier in data.pricing_tiers], ensure_ascii=False))
            lines.append("- 产品/服务条目（保留适用权益和维护条件）: " + json.dumps(
                [asdict(feature) for feature in data.product_features], ensure_ascii=False))
            lines.append(f"- 优势: {data.strengths}")
            lines.append(f"- 劣势: {data.weaknesses}")
            if data.citations:
                price_sources = {cid for tier in data.pricing_tiers for cid in tier.citations}
                lines.append("- 数据来源（价阶绑定来源保留完整已保存摘要）:\n" + "\n".join(
                    self.build_citations_text([cite], max_snippet=len(cite.snippet) if cite.id in price_sources else 200)
                    for cite in data.citations))
        if target_product_data:
            append_entity(product_name, target_product_data)
        for name, data in competitors_data.items():
            append_entity(name, data)
        lines.append("\n矩阵必须使用上述产品原名作为values的键；我方列即：" + product_name)
        return "\n".join(lines)

    def _parse_pricing_analysis(self, result):
        if not isinstance(result, dict):
            return PricingAnalysis(summary="降级：模型定价字段格式异常，未形成可用比较。")
        invalid = []
        def sequence(name):
            value = result.get(name, [])
            if not isinstance(value, list):
                invalid.append(name)
                return []
            return value
        def text(name):
            value = result.get(name, "")
            if not isinstance(value, str):
                invalid.append(name)
                return ""
            return value
        items = []
        for item in sequence("pricing_comparison"):
            if isinstance(item, dict):
                items.append(PricingItem(competitor=str(item.get("competitor", "")), free_tier=item.get("free_tier", "") if isinstance(item.get("free_tier", ""), str) else "", paid_tier=item.get("paid_tier", "") if isinstance(item.get("paid_tier", ""), str) else "", pricing_model=item.get("pricing_model", "") if isinstance(item.get("pricing_model", ""), str) else "", citations=self.extract_citation_ids(item)))
        rows = []
        for row in sequence("dimension_comparison"):
            if isinstance(row, dict) and isinstance(row.get("feature"), str) and isinstance(row.get("values"), dict):
                rows.append(FeatureComparison(row["feature"], row["values"], self.extract_citation_ids(row)))
        ranking = sequence("value_ranking")
        if any(not isinstance(name, str) for name in ranking):
            invalid.append("value_ranking")
        strategy, summary = text("pricing_strategy_analysis"), text("summary")
        basis = result.get("comparable_basis", {})
        if not isinstance(basis, dict):
            invalid.append("comparable_basis")
            basis = {}
        if invalid:
            summary += "；降级：部分模型字段格式异常，缺失内容保持资料不足。"
        return PricingAnalysis(pricing_comparison=items, dimension_comparison=rows,
            pricing_strategy_analysis=strategy,
            value_ranking=[name for name in ranking if isinstance(name, str)], summary=summary,
            comparable_basis=basis)

    def _rule_analyze(self, product_name, competitors_data, target_product_data=None, dimensions=None):
        items = []
        for name, data in competitors_data.items():
            free, paid = [], []
            for tier in data.pricing_tiers:
                text = f"{tier.tier_name}: {tier.price}"
                explicitly_free = bool(re.fullmatch(r"免费(?:版|套餐|方案)?|free(?: tier| plan)?", tier.tier_name.strip(), re.I))
                zero_price = bool(re.fullmatch(r"(?:[¥￥$]\s*)?0(?:\.0+)?(?:元)?", tier.price.strip()))
                (free if explicitly_free or zero_price else paid).append(text)
            items.append(PricingItem(name, "；".join(free), "；".join(paid) or UNKNOWN, "；".join(tier.tier_name for tier in data.pricing_tiers), list(dict.fromkeys(cid for tier in data.pricing_tiers for cid in tier.citations))))
        return self._complete_analysis(PricingAnalysis(pricing_comparison=items, summary="降级：仅保留采集到的价格与方案；未完成定价维度判断，缺口标为资料不足。"), product_name, competitors_data, dimensions or [], target_product_data)
