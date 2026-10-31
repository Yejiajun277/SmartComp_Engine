# -*- coding: utf-8 -*-
"""Product comparison with category-safe dimensions and bounded recovery."""
import re
import json
from dataclasses import asdict, dataclass, field

from agents.base_agent import BaseAgent
from models.domain import CompetitorData, ProductAnalysis, FeatureComparison, CompetitiveAdvantage
from core.prompt_loader import load as load_prompts
import config


@dataclass
class _ProductBatch:
    """Transient recovery provenance; rendered notes live in the public summary."""
    analysis: ProductAnalysis
    notes: list[tuple[tuple[str, ...], str]] = field(default_factory=list)


class ProductAgent(BaseAgent):
    """Compare products without treating missing evidence as capability claims."""

    def __init__(self):
        prompts = load_prompts("product_agent")
        self._system_prompt_template = prompts["system_prompt"]
        self._prompt_analyze = prompts["prompt_analyze"]
        super().__init__(agent_id="ProductAgent", system_prompt=self._system_prompt_template)

    def set_sub_dimensions(self, sub_dimensions_text: str):
        self.system_prompt = self._system_prompt_template.format(sub_dimensions=sub_dimensions_text)

    @staticmethod
    def _dimension_names(sub_dimensions: str) -> list[str]:
        """Read the numbered Markdown contract emitted by the orchestrator."""
        names = []
        for line in sub_dimensions.splitlines():
            line = re.sub(r"^\s*(?:\d+[.)、]\s*|[-*]\s+)", "", line).strip()
            if not line:
                continue
            bold = re.match(r"\*\*(.+?)\*\*", line)
            name = bold.group(1) if bold else re.split(r"[：:]", line, maxsplit=1)[0]
            name = name.strip()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _collected_dimensions(competitors_data, target_product_data) -> list[str]:
        data = ([target_product_data] if target_product_data else []) + list(competitors_data.values())
        return list(dict.fromkeys(fi.name.strip() for entity in data
                                  for fi in entity.product_features if fi.name.strip()))

    @staticmethod
    def _canonical_feature(feature: str, dimensions: list[str]) -> str | None:
        # Only exact labels or clearly separated explanatory suffixes may merge.
        feature = feature.strip()
        key = feature.casefold()
        for name in dimensions:
            if key == name.casefold():
                return name
        for name in sorted(dimensions, key=len, reverse=True):
            if key.startswith(name.casefold()):
                suffix = feature[len(name):]
                if suffix and suffix[0] in "（(:：[【 —–-":
                    return name
        return None

    def _complete_analysis(self, analysis, product_name, competitors_data, dimensions):
        """Keep one stable row per dimension and one cell per compared product."""
        names = list(dict.fromkeys([product_name, *competitors_data]))
        rows = {name: FeatureComparison(name, {entity: "⚪" for entity in names})
                for name in dimensions}
        for feature in analysis.feature_matrix:
            name = self._canonical_feature(feature.feature, dimensions)
            if name is None:
                continue
            row = rows[name]
            for entity, value in feature.values.items():
                if entity in row.values and isinstance(value, str) and value.strip():
                    if value != "⚪" or row.values[entity] == "⚪":
                        row.values[entity] = value
            row.citations = list(dict.fromkeys(row.citations + feature.citations))
        analysis.feature_matrix = list(rows.values())
        analysis.competitive_advantages = [adv for adv in analysis.competitive_advantages
                                           if adv.competitor in competitors_data]
        analysis.citations = list(dict.fromkeys(
            cite for item in [*analysis.feature_matrix, *analysis.competitive_advantages]
            for cite in item.citations))
        return analysis

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData],
                  target_product_data: CompetitorData | None = None,
                  sub_dimensions: str = "",
                  feedback: str = "") -> ProductAnalysis:
        self._log("🔧 开始产品分析...")
        dimensions = self._dimension_names(sub_dimensions)
        if not dimensions:
            dimensions = self._collected_dimensions(competitors_data, target_product_data)
        # Clear previous dimensions when the same agent is reused for another category.
        self.set_sub_dimensions(sub_dimensions or "\n".join(
            f"{i}. **{name}**" for i, name in enumerate(dimensions, 1)))
        if config.ENABLE_LLM:
            result, truncated = await self._request_analysis(
                product_name, competitors_data, target_product_data, feedback, max_tokens=8192)
            if truncated and len(competitors_data) >= 2:
                self._log("⚠️ 输出截断，启动有界分片恢复")
                chunked = await self._run_chunked(
                    product_name, competitors_data, target_product_data, feedback, dimensions)
                initial = self._parse_product_analysis(result) if result else ProductAnalysis()
                return self._merge_analyses(
                    [self._scoped_batch(initial, competitors_data), chunked],
                    product_name, competitors_data, dimensions,
                    replace_parent=True).analysis
            if result:
                analysis = self._parse_product_analysis(result)
                if truncated:
                    analysis.summary += "；模型输出截断，降级保留已解析内容，缺失数据标为⚪。"
                return self._complete_analysis(analysis, product_name, competitors_data, dimensions)
            self._log("⚠️ LLM产品分析失败，降级保留维度与数据缺口")
        return self._rule_analyze(product_name, competitors_data, target_product_data, dimensions)

    async def _request_analysis(self, product_name, competitors_data, target_product_data,
                                feedback, max_tokens: int = 4096):
        text = self._build_competitors_text(product_name, competitors_data, target_product_data)
        if feedback:
            text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"
        prompt = self._prompt_analyze.format(product_name=product_name, competitors_text=text)
        return await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=max_tokens)

    async def _run_chunked(self, product_name: str,
                           competitors_data: dict[str, CompetitorData],
                           target_product_data: CompetitorData | None,
                           feedback: str,
                           dimensions: list[str] | None = None) -> _ProductBatch:
        """Split malformed truncated chunks too, down to one rival per leaf.

        Recovery uses at most 2*N-2 calls in addition to the initial request.
        Failed leaves retain every dimension as unknown evidence.
        """
        if dimensions is None:
            dimensions = self._collected_dimensions(competitors_data, target_product_data)
        names = list(competitors_data)
        if len(names) < 2:
            return self._scoped_batch(self._rule_analyze(
                product_name, competitors_data, target_product_data, dimensions), competitors_data)
        mid = len(names) // 2
        analyses = []
        for subset in (names[:mid], names[mid:]):
            chunk = {name: competitors_data[name] for name in subset}
            result, truncated = await self._request_analysis(
                product_name, chunk, target_product_data, feedback)
            parsed = self._parse_product_analysis(result) if result else ProductAnalysis()
            if truncated and len(chunk) >= 2:
                recovered = await self._run_chunked(
                    product_name, chunk, target_product_data, feedback, dimensions)
                batch = self._merge_analyses(
                    [self._scoped_batch(parsed, chunk), recovered], product_name, chunk, dimensions,
                    replace_parent=True)
            else:
                if not result:
                    parsed = self._rule_analyze(product_name, chunk, target_product_data, dimensions)
                elif truncated:
                    parsed.summary += "；单竞品输出仍截断，降级保留已解析内容，缺失数据标为⚪。"
                batch = self._scoped_batch(parsed, chunk)
            analyses.append(batch)
        return self._merge_analyses(analyses, product_name, competitors_data, dimensions)

    @staticmethod
    def _scoped_batch(analysis, competitors_data):
        notes = [(tuple(competitors_data), analysis.summary)] if analysis.summary else []
        return _ProductBatch(analysis, notes)

    def _merge_analyses(self, batches, product_name, competitors_data, dimensions,
                        *, replace_parent: bool = False):
        analyses = [batch.analysis for batch in batches]
        # Later recovered chunks replace earlier truncated judgments for that rival.
        # Keep a parsed parent judgment when recovery supplies no replacement.
        advantages = {}
        for analysis in analyses:
            for advantage in analysis.competitive_advantages:
                advantages[advantage.competitor] = advantage
        # A truncated parent's global conclusions are obsolete after recovery.
        # Peer batches contribute scoped points in order, with exact duplicates removed.
        point_sources = analyses[1:] if replace_parent else analyses
        merged = ProductAnalysis(
            feature_matrix=[row for analysis in analyses for row in analysis.feature_matrix],
            competitive_advantages=list(advantages.values()),
            differentiation_points=list(dict.fromkeys(
                point.strip() for analysis in point_sources
                for point in analysis.differentiation_points
                if isinstance(point, str) and point.strip()))[:3],
        )
        merged = self._complete_analysis(merged, product_name, competitors_data, dimensions)
        # Batch-local narratives cannot describe the scope of the merged report.
        # Build its coverage statement from the final rows and retained judgments.
        cells = [value for row in merged.feature_matrix for value in row.values.values()]
        unknown = cells.count("⚪")
        degraded = any("降级" in analysis.summary for analysis in analyses)
        merged.summary = (
            f"分片恢复合并：我方{product_name}与{len(competitors_data)}家竞品"
            f"（{'、'.join(competitors_data)}），共{len(merged.feature_matrix)}个维度，"
            f"未知{unknown}/{len(cells)}格（⚪）。"
            f"保留{len(merged.competitive_advantages)}项逐竞品优劣势判断，"
            "具体引用和适用范围见逐项记录，不作全品牌外推。"
        )
        if degraded:
            merged.summary += "部分请求失败或仍截断，采用降级结果；未知不代表支持或不支持。"
        # Keep original qualifications under the actual request subset, including
        # nested batches. Never re-label nested notes as a larger parent request.
        note_batches = batches[1:] if replace_parent else batches
        notes = [note for batch in note_batches for note in batch.notes]
        if replace_parent:
            parent = analyses[0]
            retained = [adv.competitor for adv in parent.competitive_advantages
                        if advantages.get(adv.competitor) is adv
                        and adv.competitor in competitors_data]
            # Parent cells can survive even without a retained advantage entry.
            recovered_cells = {
                (self._canonical_feature(row.feature, dimensions), entity)
                for analysis in analyses[1:] for row in analysis.feature_matrix
                for entity, value in row.values.items()
                if isinstance(value, str) and value.strip() and value != "⚪"
            }
            for row in parent.feature_matrix:
                dimension = self._canonical_feature(row.feature, dimensions)
                for entity, value in row.values.items():
                    if (dimension and isinstance(value, str) and value.strip() and value != "⚪"
                            and entity in (product_name, *competitors_data)
                            and (dimension, entity) not in recovered_cells and entity not in retained):
                        retained.append(entity)
            if retained:
                suffix = f"【保留原批次判断：{'、'.join(retained)}；其余以恢复结果为准】"
                notes = [(scope, text + suffix) for scope, text in batches[0].notes] + notes
        notes = list(dict.fromkeys(notes))
        for scope, text in notes:
            merged.summary += f"\n局部比较（仅包含 {'、'.join(scope)}）：{text}"
        return _ProductBatch(merged, notes)


    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData],
                                 target_product_data: CompetitorData | None = None) -> str:
        """构建竞品数据文本，附带引用来源编号"""
        lines = []

        def append_entity(name: str, data: CompetitorData):
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            if data.product_features:
                lines.append("- 产品功能（完整原始条目、限定和引用）: " + json.dumps(
                    [asdict(feature) for feature in data.product_features], ensure_ascii=False))
            else:
                lines.append("- 产品功能: 暂无数据")
            lines.append(f"- 优势: {data.strengths}")
            lines.append(f"- 劣势: {data.weaknesses}")
            if data.citations:
                lines.append(f"- 数据来源:")
                lines.append(self.build_citations_text(
                    data.citations, max_snippet=max(len(c.snippet or "") for c in data.citations)))

        if target_product_data:
            append_entity(product_name, target_product_data)
        for name, data in competitors_data.items():
            append_entity(name, data)
        return "\n".join(lines)

    def _parse_product_analysis(self, result: dict) -> ProductAnalysis:
        """解析LLM返回的产品分析结果，提取引用 ID"""
        all_citation_ids = []

        feature_matrix = []
        for fm in result.get("feature_matrix", []):
            fm_cites = self.extract_citation_ids(fm)
            all_citation_ids.extend(fm_cites)
            feature_matrix.append(FeatureComparison(
                feature=fm.get("feature", ""),
                values=fm.get("values", {}),
                citations=fm_cites,
            ))

        advantages = []
        for adv in result.get("competitive_advantages", []):
            adv_cites = self.extract_citation_ids(adv)
            all_citation_ids.extend(adv_cites)
            advantages.append(CompetitiveAdvantage(
                competitor=adv.get("competitor", ""),
                our_advantage=adv.get("our_advantage", ""),
                their_advantage=adv.get("their_advantage", ""),
                citations=adv_cites,
            ))

        return ProductAnalysis(
            feature_matrix=feature_matrix,
            competitive_advantages=advantages,
            differentiation_points=result.get("differentiation_points", []),
            summary=result.get("summary", ""),
            citations=list(set(all_citation_ids)),
        )

    def _rule_analyze(self, product_name: str,
                       competitors_data: dict[str, CompetitorData],
                       target_product_data: CompetitorData | None = None,
                       dimensions: list[str] | None = None) -> ProductAnalysis:
        """Fallback supplies structure only; it cannot verify capability evidence."""
        if dimensions is None:
            dimensions = self._collected_dimensions(competitors_data, target_product_data)
        analysis = ProductAnalysis(
            summary="规则降级：资料不足，保留分析维度；未完成模型对比，缺失证据标为⚪，不推断支持或不支持。",
        )
        return self._complete_analysis(analysis, product_name, competitors_data, dimensions)
