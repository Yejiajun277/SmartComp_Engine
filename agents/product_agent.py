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
            result = await self.async_ask_llm_json(prompt, max_tokens=4096)
            if result:
                analysis = self._parse_product_analysis(result)
                self._log(f"✅ 产品分析完成: {len(analysis.feature_matrix)}个功能维度, "
                          f"{len(analysis.differentiation_points)}个差异点")
                return analysis
            else:
                self._log("⚠️ LLM产品分析失败，降级到规则引擎")

        # Fallback: 规则引擎分析
        return self._rule_analyze(product_name, competitors_data, target_product_data)

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
