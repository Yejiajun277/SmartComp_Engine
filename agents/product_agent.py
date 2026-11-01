# -*- coding: utf-8 -*-
"""Product comparison with category-safe dimensions and bounded recovery."""
import re
import json
from dataclasses import dataclass, field

from agents.base_agent import BaseAgent
from models.domain import CompetitorData, ProductAnalysis, FeatureComparison, CompetitiveAdvantage
from core.prompt_loader import load as load_prompts
import config


@dataclass
class _ProductBatch:
    """Transient recovery provenance; rendered notes live in the public summary."""
    analysis: ProductAnalysis
    notes: list[tuple[tuple[str, ...], str]] = field(default_factory=list)
    narrative_citations: list[str] = field(default_factory=list)


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
            [*analysis.citations, *(cite for item in [*analysis.feature_matrix, *analysis.competitive_advantages]
                                    for cite in item.citations)]))
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
        result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=max_tokens)
        if result:
            result = self._ground_result(result, product_name, competitors_data, target_product_data)
        return result, truncated

    @staticmethod
    def _entity_facts(data: CompetitorData) -> dict:
        """Stable entity-local selectors; quotations retain the whole saved scope.

        Tier features are product facts too: a combined SKU comparison may have
        positive evidence for one SKU only in its individual tier description.
        Prices themselves are intentionally outside this product catalog.
        """
        sources = {citation.id for citation in data.citations if citation.id}
        facts = {}
        for index, item in enumerate(data.product_features):
            text = "：".join(value for value in (item.name, item.description) if value)
            facts[f"product_features[{index}]"] = {
                "text": text,
                "citations": list(dict.fromkeys(c for c in item.citations if c in sources)),
            }
        for tier_index, tier in enumerate(data.pricing_tiers):
            for feature_index, text in enumerate(tier.features):
                if not isinstance(text, str) or not text.strip():
                    continue
                facts[f"pricing_tiers[{tier_index}].features[{feature_index}]"] = {
                    "text": f"{tier.tier_name}：{text}",
                    "citations": list(dict.fromkeys(c for c in tier.citations if c in sources)),
                }
        return facts

    def _ground_result(self, result, product_name, competitors_data, target_product_data):
        """Project selected saved facts, never an unqualified model paraphrase.

        A row-wide source citation cannot prove that one status applies to every
        SKU in a column. Text cells therefore retain the original fact and its
        version/region qualifiers; absent bindings remain genuine gaps. This is
        not a semantic verification of the collected fact (the QA gate does that).
        """
        entities = dict(competitors_data)
        if target_product_data:
            entities[product_name] = target_product_data
        catalogs = {name: self._entity_facts(data) for name, data in entities.items()}
        if not isinstance(result, dict):
            return {}
        def select(entity, fact_ids):
            if not isinstance(fact_ids, list):
                return [], []
            selected, citations = [], []
            for fact_id in fact_ids:
                if not isinstance(fact_id, str):
                    continue
                fact = catalogs.get(entity, {}).get(fact_id)
                if not fact or not fact["text"] or not fact["citations"]:
                    continue
                if fact["text"] not in selected:
                    selected.append(fact["text"])
                citations.extend(fact["citations"])
            return selected, list(dict.fromkeys(citations))

        def project(facts):
            lines, citations = [], []
            if not isinstance(facts, list):
                return lines, citations
            for item in facts:
                if not isinstance(item, dict) or not isinstance(item.get("entity"), str):
                    continue
                entity = item["entity"]
                selected, refs = select(entity, item.get("fact_ids"))
                lines.extend(f"{entity}｜{text}" for text in selected)
                citations.extend(refs)
            return list(dict.fromkeys(lines)), list(dict.fromkeys(citations))

        rows, all_citations = [], []
        raw_rows = result.get("feature_matrix")
        for row in raw_rows if isinstance(raw_rows, list) else []:
            if not isinstance(row, dict) or not isinstance(row.get("feature"), str):
                continue
            evidence = row.get("evidence")
            evidence = evidence if isinstance(evidence, dict) else {}
            values, refs = {}, []
            for entity in (product_name, *competitors_data):
                selected, bound_refs = select(entity, evidence.get(entity))
                values[entity] = ("采集事实（仅限下述原文范围）：" + "；".join(selected)
                                  if selected else "⚪")
                refs.extend(bound_refs)
            refs = list(dict.fromkeys(refs))
            rows.append({"feature": row["feature"], "values": values, "citations": refs})
            all_citations.extend(refs)

        advantages = []
        raw_advantages = result.get("competitive_advantages")
        for item in raw_advantages if isinstance(raw_advantages, list) else []:
            if (not isinstance(item, dict) or not isinstance(item.get("competitor"), str)
                    or item["competitor"] not in competitors_data):
                continue
            rival = item["competitor"]
            ours, our_refs = select(product_name, item.get("our_evidence"))
            theirs, their_refs = select(rival, item.get("their_evidence"))
            if not ours and not theirs:
                continue
            refs = list(dict.fromkeys(our_refs + their_refs))
            advantages.append({"competitor": rival,
                "our_advantage": "比较依据（仅限采集规格）：" + "；".join(ours) if ours else "资料不足，不能确认优势。",
                "their_advantage": "比较依据（仅限采集规格）：" + "；".join(theirs) if theirs else "资料不足，不能确认优势。",
                "citations": refs})
            all_citations.extend(refs)

        points, narrative_citations = [], []
        raw_points = result.get("differentiation_points")
        for item in raw_points if isinstance(raw_points, list) else []:
            if not isinstance(item, dict):
                continue
            lines, refs = project(item.get("facts"))
            if lines:
                points.append("；".join(lines))
                all_citations.extend(refs)
                narrative_citations.extend(refs)
        raw_summary = result.get("summary")
        lines, refs = project(raw_summary.get("facts") if isinstance(raw_summary, dict) else None)
        all_citations.extend(refs)
        narrative_citations.extend(refs)
        return {"feature_matrix": rows, "competitive_advantages": advantages,
                "differentiation_points": points[:3],
                "summary": ("按采集规格逐项比较，不外推其他SKU/地区：\n" + "\n".join(lines)
                            if lines else "资料不足：摘要缺少有效的逐实体事实绑定，未保留无范围的模型断言。"),
                "citations": list(dict.fromkeys(all_citations)),
                "_narrative_citations": list(dict.fromkeys(narrative_citations))}

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
        return _ProductBatch(analysis, notes, getattr(analysis, "_narrative_citations", []))

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
        narrative_batches = batches[1:] if replace_parent else batches
        narrative_citations = list(dict.fromkeys(
            cite for batch in narrative_batches for cite in batch.narrative_citations))
        merged = ProductAnalysis(
            feature_matrix=[row for analysis in analyses for row in analysis.feature_matrix],
            competitive_advantages=list(advantages.values()),
            differentiation_points=list(dict.fromkeys(
                point.strip() for analysis in point_sources
                for point in analysis.differentiation_points
                if isinstance(point, str) and point.strip()))[:3],
            citations=narrative_citations,
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
                narrative_citations = list(dict.fromkeys(
                    narrative_citations + batches[0].narrative_citations))
                merged.citations = list(dict.fromkeys(merged.citations + narrative_citations))
        notes = list(dict.fromkeys(notes))
        for scope, text in notes:
            merged.summary += f"\n局部比较（仅包含 {'、'.join(scope)}）：{text}"
        return _ProductBatch(merged, notes, narrative_citations)


    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData],
                                 target_product_data: CompetitorData | None = None) -> str:
        """构建竞品数据文本，附带引用来源编号"""
        lines = []

        def append_entity(name: str, data: CompetitorData):
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            lines.append("- 产品功能（完整原始条目、限定和引用；ID仅在本实体内有效）: " + json.dumps(
                self._entity_facts(data), ensure_ascii=False))
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
        all_citation_ids = list(result.get("citations", []))

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

        analysis = ProductAnalysis(
            feature_matrix=feature_matrix,
            competitive_advantages=advantages,
            differentiation_points=result.get("differentiation_points", []),
            summary=result.get("summary", ""),
            citations=list(set(all_citation_ids)),
        )
        # Internal recovery provenance is excluded from the persisted dataclass.
        analysis._narrative_citations = result.get("_narrative_citations", [])
        return analysis

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
