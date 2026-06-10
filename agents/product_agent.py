# -*- coding: utf-8 -*-
"""
agents/product_agent.py — 产品分析Agent

职责：逐竞品对比功能矩阵，标注优势/劣势/差异点
LLM调用：1次
外部工具：无
提示词来源：prompts/product_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import CompetitorData, ProductAnalysis, FeatureComparison, CompetitiveAdvantage
from core.prompt_loader import load as load_prompts
import config
import json


class ProductAgent(BaseAgent):
    """产品分析Agent — 功能对比矩阵"""

    def __init__(self):
        prompts = load_prompts("product_agent")
        self._system_prompt_template = prompts["system_prompt"]
        self._prompt_analyze = prompts["prompt_analyze"]
        super().__init__(
            agent_id="ProductAgent",
            system_prompt=self._system_prompt_template,
        )

    def set_sub_dimensions(self, sub_dimensions_text: str):
        """注入动态子维度（由 DimensionAgent 生成）"""
        self.system_prompt = self._system_prompt_template.format(
            sub_dimensions=sub_dimensions_text
        )

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData],
                  target_product_data: CompetitorData | None = None,
                  sub_dimensions: str = "",
                  feedback: str = "") -> ProductAnalysis:
        """
        主运行逻辑：全量数据分析产品对比

        Args:
            product_name: 用户产品名称
            competitors_data: 竞品采集数据

        Returns:
            ProductAnalysis: 产品分析结果
        """
        self._log("🔧 开始产品分析...")

        if sub_dimensions:
            self.set_sub_dimensions(sub_dimensions)

        # 构建竞品数据摘要
        competitors_text = self._build_competitors_text(product_name, competitors_data, target_product_data)

        # 注入质检反馈
        if feedback:
            competitors_text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=competitors_text,
            )
            result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=4096)
            if result:
                # 检测到截断且竞品数量较多时，启动分片重试
                if truncated and len(competitors_data) >= 2:
                    self._log(f"⚠️ 检测到输出截断，竞品数量={len(competitors_data)}，启动分片重试...")
                    chunked_analysis = await self._run_chunked(
                        product_name, competitors_data, target_product_data, feedback
                    )
                    if chunked_analysis:
                        return chunked_analysis
                    self._log("⚠️ 分片重试未产生更好结果，使用首次（可能不完整）的分析")
                analysis = self._parse_product_analysis(result)
                self._log(f"✅ 产品分析完成: {len(analysis.feature_matrix)}个功能维度, "
                          f"{len(analysis.differentiation_points)}个差异点")
                return analysis
            else:
                # 即使解析失败，如果竞品数量>=2，也尝试分片
                if truncated and len(competitors_data) >= 2:
                    self._log(f"⚠️ JSON解析失败+截断，尝试分片重试...")
                    chunked_analysis = await self._run_chunked(
                        product_name, competitors_data, target_product_data, feedback
                    )
                    if chunked_analysis:
                        return chunked_analysis
                self._log("⚠️ LLM产品分析失败，降级到规则引擎")

        # Fallback: 规则引擎分析
        return self._rule_analyze(product_name, competitors_data, target_product_data)

    async def _run_chunked(self, product_name: str,
                           competitors_data: dict[str, CompetitorData],
                           target_product_data: CompetitorData | None,
                           feedback: str) -> ProductAnalysis | None:
        """
        分片重试：将竞品拆成多批分别调用LLM，再合并结果。
        递归拆分，直到每批调用不再截断。
        """
        all_names = list(competitors_data.keys())
        if len(all_names) < 2:
            return None

        # 拆成两半
        mid = len(all_names) // 2
        chunks = [
            {name: competitors_data[name] for name in all_names[:mid]},
            {name: competitors_data[name] for name in all_names[mid:]},
        ]

        all_features = []
        all_advantages = []
        all_diff_points = []
        summaries = []
        all_citations = []

        for i, chunk in enumerate(chunks):
            self._log(f"  📦 分片 {i+1}/{len(chunks)}: {list(chunk.keys())}")
            chunk_text = self._build_competitors_text(product_name, chunk, target_product_data)
            if feedback:
                chunk_text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"

            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=chunk_text,
            )
            result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=4096)
            if not result:
                self._log(f"  ⚠️ 分片 {i+1} 调用失败，跳过")
                continue

            # 如果分片仍然截断且还有2+竞品，递归拆分
            if truncated and len(chunk) >= 2:
                self._log(f"  ⚠️ 分片 {i+1} 仍然截断，继续拆分...")
                sub_analysis = await self._run_chunked(
                    product_name, chunk, target_product_data, feedback
                )
                if sub_analysis:
                    all_features.extend(sub_analysis.feature_matrix)
                    all_advantages.extend(sub_analysis.competitive_advantages)
                    all_diff_points.extend(sub_analysis.differentiation_points)
                    all_citations.extend(sub_analysis.citations)
                    if sub_analysis.summary:
                        summaries.append(sub_analysis.summary)
                    continue

            # 解析本片结果
            parsed = self._parse_product_analysis(result)
            all_features.extend(parsed.feature_matrix)
            all_advantages.extend(parsed.competitive_advantages)
            all_diff_points.extend(parsed.differentiation_points)
            all_citations.extend(parsed.citations)
            if parsed.summary:
                summaries.append(parsed.summary)

        if not all_advantages and not all_features:
            return None

        # 去重并合并 feature_matrix：同名功能维度合并 values 字典
        feature_map: dict[str, FeatureComparison] = {}
        for fm in all_features:
            if fm.feature in feature_map:
                feature_map[fm.feature].values.update(fm.values)
                feature_map[fm.feature].citations = list(set(feature_map[fm.feature].citations + fm.citations))
            else:
                feature_map[fm.feature] = fm
        merged_features = list(feature_map.values())

        # 去重差异点
        seen_diff = set()
        unique_diff = []
        for dp in all_diff_points:
            if dp not in seen_diff:
                seen_diff.add(dp)
                unique_diff.append(dp)

        self._log(f"✅ 分片合并完成: {len(merged_features)}个功能维度, "
                  f"{len(all_advantages)}个优势对比, {len(unique_diff)}个差异点")

        return ProductAnalysis(
            feature_matrix=merged_features,
            competitive_advantages=all_advantages,
            differentiation_points=unique_diff,
            summary="；".join(summaries) if summaries else "",
            citations=list(set(all_citations)),
        )

    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData],
                                 target_product_data: CompetitorData | None = None) -> str:
        """构建竞品数据文本，附带引用来源编号"""
        lines = []

        def append_entity(name: str, data: CompetitorData):
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            if data.product_features:
                features_text = "; ".join([f"{fi.name}: {fi.description}" for fi in data.product_features[:10]])
                lines.append(f"- 产品功能: {features_text[:300]}")
            else:
                lines.append("- 产品功能: 暂无数据")
            lines.append(f"- 优势: {data.strengths[:200]}")
            lines.append(f"- 劣势: {data.weaknesses[:200]}")
            if data.citations:
                lines.append(f"- 数据来源:")
                lines.append(self.build_citations_text(data.citations))

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
                       target_product_data: CompetitorData | None = None) -> ProductAnalysis:
        """规则引擎产品分析"""
        feature_keywords = {
            "即时通讯": ["通讯", "消息", "聊天"],
            "视频会议": ["视频", "会议", "通话"],
            "文档协作": ["文档", "协作", "编辑"],
            "审批流程": ["审批", "流程", "工作流"],
            "项目管理": ["项目", "任务", "看板"],
            "数据分析": ["数据", "分析", "报表"],
            "AI助手": ["AI", "智能", "助手"],
        }

        feature_matrix = []
        for feature, keywords in feature_keywords.items():
            values = {}
            product_text = product_name.lower()
            if target_product_data:
                features_str = " ".join([fi.name + " " + fi.description for fi in target_product_data.product_features])
                product_text += f" {features_str} {target_product_data.strengths}".lower()
            if any(kw.lower() in product_text for kw in keywords):
                values[product_name] = "✅"
            else:
                values[product_name] = "❌"
            for name, data in competitors_data.items():
                features_str = " ".join([fi.name + " " + fi.description for fi in data.product_features])
                text = f"{features_str} {data.strengths}".lower()
                if any(kw.lower() in text for kw in keywords):
                    values[name] = "✅"
                else:
                    values[name] = "❌"
            feature_matrix.append(FeatureComparison(feature=feature, values=values))

        return ProductAnalysis(
            feature_matrix=feature_matrix,
            competitive_advantages=[],
            differentiation_points=["(规则引擎分析，详情请启用LLM)"],
            summary="基于关键词匹配的简单产品对比（建议启用LLM获得深度分析）",
        )
