"""Category-specific pricing comparisons with bounded, evidence-safe recovery."""
from dataclasses import asdict, dataclass, field
import json
import re
from agents.base_agent import BaseAgent
from models.domain import CompetitorData, FeatureComparison, PricingAnalysis, PricingItem
from core.prompt_loader import load as load_prompts
import config

UNKNOWN = "资料不足"

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

    def _complete_analysis(self, analysis, product_name, competitors_data, dimensions):
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
                return self._merge_batches([self._scoped(initial, competitors_data), recovered], product_name, competitors_data, dimensions, replace_parent=True).analysis
            if result:
                analysis = self._parse_pricing_analysis(result)
                if truncated:
                    analysis.summary += "；输出仍截断，降级保留已解析资料，缺口保持未知。"
                return self._complete_analysis(analysis, product_name, competitors_data, dimensions)
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
                batch = self._merge_batches([self._scoped(parsed, chunk), recovered], product_name, chunk, dimensions, replace_parent=True)
            else:
                if not result:
                    parsed = self._rule_analyze(product_name, chunk, target_product_data, dimensions)
                elif truncated:
                    parsed.summary += "；输出仍截断，降级保留已解析资料，缺口保持未知。"
                batch = self._scoped(parsed, chunk)
            batches.append(batch)
        return self._merge_batches(batches, product_name, competitors_data, dimensions)

    @staticmethod
    def _scoped(analysis, competitors_data):
        return _PricingBatch(analysis, [(tuple(competitors_data), analysis.summary, analysis.pricing_strategy_analysis)])

    def _merge_batches(self, batches, product_name, competitors_data, dimensions, *, replace_parent=False):
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
        merged = self._complete_analysis(PricingAnalysis(pricing_comparison=list(items.values()), dimension_comparison=[row for batch in batches for row in batch.analysis.dimension_comparison]), product_name, competitors_data, dimensions)
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
                lines.append("- 数据来源:\n" + self.build_citations_text(data.citations))
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
        if invalid:
            summary += "；降级：部分模型字段格式异常，缺失内容保持资料不足。"
        return PricingAnalysis(pricing_comparison=items, dimension_comparison=rows,
            pricing_strategy_analysis=strategy,
            value_ranking=[name for name in ranking if isinstance(name, str)], summary=summary)

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
        return self._complete_analysis(PricingAnalysis(pricing_comparison=items, summary="降级：仅保留采集到的价格与方案；未完成定价维度判断，缺口标为资料不足。"), product_name, competitors_data, dimensions or [])
