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
        super().__init__(
            agent_id="ProductAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData]) -> ProductAnalysis:
        """
        主运行逻辑：全量数据分析产品对比

        Args:
            product_name: 用户产品名称
            competitors_data: 竞品采集数据

        Returns:
            ProductAnalysis: 产品分析结果
        """
        self._log("🔧 开始产品分析...")

        # 构建竞品数据摘要
        competitors_text = self._build_competitors_text(product_name, competitors_data)

        if config.ENABLE_LLM:
            prompt = self._prompt_analyze.format(
                product_name=product_name,
                competitors_text=competitors_text,
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                analysis = self._parse_product_analysis(result)
                self._log(f"✅ 产品分析完成: {len(analysis.feature_matrix)}个功能维度, "
                          f"{len(analysis.differentiation_points)}个差异点")
                return analysis
            else:
                self._log("⚠️ LLM产品分析失败，降级到规则引擎")

        # Fallback: 规则引擎分析
        return self._rule_analyze(product_name, competitors_data)

    def _build_competitors_text(self, product_name: str,
                                 competitors_data: dict[str, CompetitorData]) -> str:
        """构建竞品数据文本"""
        lines = []
        for name, data in competitors_data.items():
            label = name if name != product_name else f"{name}(我方产品)"
            lines.append(f"\n### {label}")
            lines.append(f"- 产品功能: {data.product_features[:300]}")
            lines.append(f"- 优势: {data.strengths[:200]}")
            lines.append(f"- 劣势: {data.weaknesses[:200]}")
        return "\n".join(lines)

    def _parse_product_analysis(self, result: dict) -> ProductAnalysis:
        """解析LLM返回的产品分析结果"""
        feature_matrix = []
        for fm in result.get("feature_matrix", []):
            feature_matrix.append(FeatureComparison(
                feature=fm.get("feature", ""),
                values=fm.get("values", {}),
            ))

        advantages = []
        for adv in result.get("competitive_advantages", []):
            advantages.append(CompetitiveAdvantage(
                competitor=adv.get("competitor", ""),
                our_advantage=adv.get("our_advantage", ""),
                their_advantage=adv.get("their_advantage", ""),
            ))

        return ProductAnalysis(
            feature_matrix=feature_matrix,
            competitive_advantages=advantages,
            differentiation_points=result.get("differentiation_points", []),
            summary=result.get("summary", ""),
        )

    def _rule_analyze(self, product_name: str,
                       competitors_data: dict[str, CompetitorData]) -> ProductAnalysis:
        """规则引擎产品分析"""
        # 简单的关键词匹配
        all_features = set()
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
            # 先检查我方产品（使用产品描述+竞品数据中标注为"我方"的信息）
            product_text = product_name.lower()
            for name, data in competitors_data.items():
                product_text += f" {data.product_features} {data.strengths}".lower()
            if any(kw.lower() in product_text for kw in keywords):
                values[product_name] = "✅"
            else:
                values[product_name] = "❌"
            # 再检查每个竞品
            for name, data in competitors_data.items():
                text = f"{data.product_features} {data.strengths}".lower()
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
