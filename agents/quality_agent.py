# -*- coding: utf-8 -*-
"""
agents/quality_agent.py — 质检Agent

职责：完整性检查 + 幻觉检测，发现问题后打回对应 Agent 重做
LLM调用：1次/检查（幻觉检测）
提示词来源：prompts/quality_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import (
    CompetitorData, ProductAnalysis, PricingAnalysis, MarketAnalysis,
    StrategyReport, QualityIssue, QualityCheckResult, QATimeline,
)
from core.prompt_loader import load as load_prompts
from datetime import datetime
import config
import json


class QualityAgent(BaseAgent):
    """质检 Agent — 完整性检查 + 幻觉检测"""

    MAX_RETRIES = 2
    PASS_SCORE = 70

    def __init__(self):
        prompts = load_prompts("quality_agent")
        super().__init__(
            agent_id="QualityAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_check_collection = prompts["prompt_check_collection"]
        self._prompt_check_analysis = prompts["prompt_check_analysis"]
        self._prompt_check_strategy = prompts["prompt_check_strategy"]
        self._prompt_build_feedback = prompts["prompt_build_feedback"]
        self.timeline = QATimeline(max_retries=self.MAX_RETRIES)

    async def run(self, *args, **kwargs):
        """不直接调用，请使用 check_collection / check_analysis / check_strategy"""
        raise NotImplementedError("QualityAgent 不直接运行，请使用 check_collection/check_analysis/check_strategy")

    # ── Phase 2: 采集数据质检 ──

    async def check_collection(
        self,
        competitors_data: dict[str, CompetitorData],
        original_search_texts: dict[str, str],
        attempt: int = 1,
    ) -> QualityCheckResult:
        """Phase 2 质检：检查采集数据"""
        self._log(f"🔍 质检采集数据（第{attempt}次）...")
        issues = []

        # 完整性检查
        issues.extend(self._check_collection_completeness(competitors_data))

        # 幻觉检测（仅 LLM 模式）
        if config.ENABLE_LLM and original_search_texts:
            hallucination_issues = await self._check_collection_hallucination(
                competitors_data, original_search_texts
            )
            issues.extend(hallucination_issues)

        score = self._calculate_score(issues)
        passed = score >= self.PASS_SCORE

        result = QualityCheckResult(
            phase="collection",
            target_agent="CollectionAgent",
            passed=passed,
            score=score,
            issues=issues,
            checked_at=datetime.now().isoformat(timespec="seconds"),
            attempt=attempt,
        )

        status = "✅ 通过" if passed else "❌ 未通过"
        self._log(f"   采集数据质检: {status} (分数: {score}, 问题: {len(issues)})")
        return result

    def _check_collection_completeness(
        self, competitors_data: dict[str, CompetitorData]
    ) -> list[QualityIssue]:
        """采集数据完整性检查（规则引擎）"""
        issues = []
        for name, data in competitors_data.items():
            if not data.name:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field=f"{name}.name",
                    description="竞品名称为空",
                    suggestion="确保采集到竞品名称",
                ))
            if not data.product_features:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field=f"{name}.product_features",
                    description="产品功能列表为空",
                    suggestion="重新搜索该竞品的产品功能信息",
                ))
            else:
                for i, fi in enumerate(data.product_features):
                    if not fi.name:
                        issues.append(QualityIssue(
                            severity="critical", category="completeness",
                            field=f"{name}.product_features[{i}].name",
                            description="功能项名称为空",
                            suggestion="确保每个功能项都有名称",
                        ))
            if not data.pricing_tiers:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.pricing_tiers",
                    description="定价层级为空",
                    suggestion="补充该竞品的定价信息",
                ))
            else:
                for i, pt in enumerate(data.pricing_tiers):
                    if not pt.tier_name:
                        issues.append(QualityIssue(
                            severity="critical", category="completeness",
                            field=f"{name}.pricing_tiers[{i}].tier_name",
                            description="定价层级名称为空",
                            suggestion="确保每个定价层级都有名称",
                        ))
            if not data.market_share:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.market_share",
                    description="市场份额信息为空",
                    suggestion="补充该竞品的市场份额数据",
                ))
            if not data.citations:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.citations",
                    description="无引用来源",
                    suggestion="确保采集数据有来源引用",
                ))
        return issues

    async def _check_collection_hallucination(
        self,
        competitors_data: dict[str, CompetitorData],
        original_search_texts: dict[str, str],
    ) -> list[QualityIssue]:
        """采集数据幻觉检测（LLM）"""
        # 构建竞品数据摘要
        data_summary = {}
        for name, data in competitors_data.items():
            data_summary[name] = {
                "product_features": [{"name": fi.name, "description": fi.description} for fi in data.product_features],
                "pricing_tiers": [{"tier_name": pt.tier_name, "price": pt.price} for pt in data.pricing_tiers],
                "market_share": data.market_share,
                "user_reviews": data.user_reviews[:200],
                "strengths": data.strengths[:200],
                "weaknesses": data.weaknesses[:200],
            }

        # 截断原始搜索文本
        search_texts_limited = {}
        for name, text in original_search_texts.items():
            search_texts_limited[name] = text[:3000]

        prompt = self._prompt_check_collection.format(
            original_search_texts=json.dumps(search_texts_limited, ensure_ascii=False, indent=2),
            competitors_data_json=json.dumps(data_summary, ensure_ascii=False, indent=2),
        )

        result = self.ask_llm_json(prompt, max_tokens=2048)
        if not result:
            return []

        return self._parse_issues(result)

    # ── Phase 3: 分析结果质检 ──

    async def check_analysis(
        self,
        analysis_type: str,
        analysis: ProductAnalysis | PricingAnalysis | MarketAnalysis,
        competitors_data: dict[str, CompetitorData],
        attempt: int = 1,
    ) -> QualityCheckResult:
        """Phase 3 质检：检查分析结果"""
        self._log(f"🔍 质检{analysis_type}分析（第{attempt}次）...")
        issues = []

        # 完整性检查
        issues.extend(self._check_analysis_completeness(analysis_type, analysis, competitors_data))

        # 幻觉检测（仅 LLM 模式）
        if config.ENABLE_LLM:
            hallucination_issues = await self._check_analysis_hallucination(
                analysis_type, analysis, competitors_data
            )
            issues.extend(hallucination_issues)

        score = self._calculate_score(issues)
        passed = score >= self.PASS_SCORE

        agent_id_map = {
            "product": "ProductAgent",
            "pricing": "PricingAgent",
            "market": "MarketAgent",
        }

        result = QualityCheckResult(
            phase=analysis_type,
            target_agent=agent_id_map.get(analysis_type, "UnknownAgent"),
            passed=passed,
            score=score,
            issues=issues,
            checked_at=datetime.now().isoformat(timespec="seconds"),
            attempt=attempt,
        )

        status = "✅ 通过" if passed else "❌ 未通过"
        self._log(f"   {analysis_type}分析质检: {status} (分数: {score}, 问题: {len(issues)})")
        return result

    def _check_analysis_completeness(
        self,
        analysis_type: str,
        analysis: ProductAnalysis | PricingAnalysis | MarketAnalysis,
        competitors_data: dict[str, CompetitorData],
    ) -> list[QualityIssue]:
        """分析结果完整性检查"""
        issues = []

        if analysis_type == "product":
            pa: ProductAnalysis = analysis
            if not pa.feature_matrix:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field="feature_matrix",
                    description="功能矩阵为空",
                    suggestion="确保产品分析生成功能对比矩阵",
                ))
            if not pa.summary:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="summary",
                    description="产品分析摘要为空",
                    suggestion="补充产品分析摘要",
                ))

        elif analysis_type == "pricing":
            pra: PricingAnalysis = analysis
            if not pra.pricing_comparison:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field="pricing_comparison",
                    description="定价对比为空",
                    suggestion="确保定价分析生成对比数据",
                ))
            if not pra.summary:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="summary",
                    description="定价分析摘要为空",
                    suggestion="补充定价分析摘要",
                ))

        elif analysis_type == "market":
            ma: MarketAnalysis = analysis
            if not ma.market_share_data:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field="market_share_data",
                    description="市场份额数据为空",
                    suggestion="确保市场分析生成份额数据",
                ))
            if not ma.summary:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="summary",
                    description="市场分析摘要为空",
                    suggestion="补充市场分析摘要",
                ))

        return issues

    async def _check_analysis_hallucination(
        self,
        analysis_type: str,
        analysis: ProductAnalysis | PricingAnalysis | MarketAnalysis,
        competitors_data: dict[str, CompetitorData],
    ) -> list[QualityIssue]:
        """分析结果幻觉检测（LLM）"""
        # 构建采集数据摘要
        data_summary = {}
        for name, data in competitors_data.items():
            data_summary[name] = {
                "product_features": [{"name": fi.name, "description": fi.description} for fi in data.product_features[:5]],
                "market_share": data.market_share[:200],
                "strengths": data.strengths[:200],
                "weaknesses": data.weaknesses[:200],
            }

        # 序列化分析结果
        if analysis_type == "product":
            analysis_json = {
                "feature_matrix": [{"feature": fm.feature, "values": fm.values} for fm in analysis.feature_matrix],
                "differentiation_points": analysis.differentiation_points,
                "summary": analysis.summary,
            }
        elif analysis_type == "pricing":
            analysis_json = {
                "pricing_comparison": [{"competitor": pc.competitor, "free_tier": pc.free_tier, "paid_tier": pc.paid_tier} for pc in analysis.pricing_comparison],
                "value_ranking": analysis.value_ranking,
                "summary": analysis.summary,
            }
        else:
            analysis_json = {
                "market_share_data": [{"competitor": ms.competitor, "share_estimate": ms.share_estimate} for ms in analysis.market_share_data],
                "growth_trends": analysis.growth_trends,
                "summary": analysis.summary,
            }

        prompt = self._prompt_check_analysis.format(
            analysis_type=analysis_type,
            competitors_data_summary=json.dumps(data_summary, ensure_ascii=False, indent=2),
            analysis_json=json.dumps(analysis_json, ensure_ascii=False, indent=2),
            feedback="",
        )

        result = self.ask_llm_json(prompt, max_tokens=2048)
        if not result:
            return []

        return self._parse_issues(result)

    # ── Phase 4: 最终报告质检 ──

    async def check_strategy(
        self,
        report: StrategyReport,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        attempt: int = 1,
    ) -> QualityCheckResult:
        """Phase 4 质检：检查最终报告"""
        self._log(f"🔍 质检策略报告（第{attempt}次）...")
        issues = []

        # 完整性检查
        issues.extend(self._check_strategy_completeness(report))

        # 幻觉检测（仅 LLM 模式）
        if config.ENABLE_LLM:
            hallucination_issues = await self._check_strategy_hallucination(
                report, product_analysis, pricing_analysis, market_analysis
            )
            issues.extend(hallucination_issues)

        score = self._calculate_score(issues)
        passed = score >= self.PASS_SCORE

        result = QualityCheckResult(
            phase="strategy",
            target_agent="StrategyAgent",
            passed=passed,
            score=score,
            issues=issues,
            checked_at=datetime.now().isoformat(timespec="seconds"),
            attempt=attempt,
        )

        status = "✅ 通过" if passed else "❌ 未通过"
        self._log(f"   策略报告质检: {status} (分数: {score}, 问题: {len(issues)})")
        return result

    def _check_strategy_completeness(self, report: StrategyReport) -> list[QualityIssue]:
        """策略报告完整性检查"""
        issues = []
        if not report.overall_positioning:
            issues.append(QualityIssue(
                severity="critical", category="completeness",
                field="overall_positioning",
                description="整体定位为空",
                suggestion="确保策略报告包含整体定位",
            ))
        if not report.action_plan:
            issues.append(QualityIssue(
                severity="critical", category="completeness",
                field="action_plan",
                description="行动方案为空",
                suggestion="确保策略报告包含行动方案",
            ))
        else:
            for i, item in enumerate(report.action_plan):
                if not item.action:
                    issues.append(QualityIssue(
                        severity="critical", category="completeness",
                        field=f"action_plan[{i}].action",
                        description="行动方案项内容为空",
                        suggestion="确保每个行动方案都有具体描述",
                    ))
        if not report.risk_assessment:
            issues.append(QualityIssue(
                severity="warning", category="completeness",
                field="risk_assessment",
                description="风险评估为空",
                suggestion="补充风险评估内容",
            ))
        if not report.summary:
            issues.append(QualityIssue(
                severity="warning", category="completeness",
                field="summary",
                description="报告摘要为空",
                suggestion="补充报告摘要",
            ))
        return issues

    async def _check_strategy_hallucination(
        self,
        report: StrategyReport,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
    ) -> list[QualityIssue]:
        """策略报告幻觉检测（LLM）"""
        three_dim = {
            "product_summary": product_analysis.summary,
            "differentiation_points": product_analysis.differentiation_points,
            "pricing_summary": pricing_analysis.summary,
            "value_ranking": pricing_analysis.value_ranking,
            "market_summary": market_analysis.summary,
            "growth_trends": market_analysis.growth_trends,
        }

        strategy_json = {
            "overall_positioning": report.overall_positioning,
            "differentiation_strategy": report.differentiation_strategy,
            "action_plan": [{"priority": ai.priority, "action": ai.action, "timeline": ai.timeline} for ai in report.action_plan],
            "risk_assessment": report.risk_assessment,
            "summary": report.summary,
        }

        prompt = self._prompt_check_strategy.format(
            three_dimensional_analysis=json.dumps(three_dim, ensure_ascii=False, indent=2),
            strategy_report_json=json.dumps(strategy_json, ensure_ascii=False, indent=2),
        )

        result = self.ask_llm_json(prompt, max_tokens=2048)
        if not result:
            return []

        return self._parse_issues(result)

    # ── 通用工具方法 ──

    def build_feedback(self, result: QualityCheckResult) -> str:
        """根据质检结果构造给被打回 Agent 的反馈消息"""
        if config.ENABLE_LLM:
            prompt = self._prompt_build_feedback.format(
                qa_result_json=json.dumps({
                    "phase": result.phase,
                    "target_agent": result.target_agent,
                    "score": result.score,
                    "issues": [
                        {"severity": i.severity, "field": i.field, "description": i.description, "suggestion": i.suggestion}
                        for i in result.issues
                    ],
                }, ensure_ascii=False, indent=2)
            )
            feedback = self.ask_llm(prompt, max_tokens=512)
            if feedback:
                return feedback

        # 规则引擎 fallback
        critical_issues = [i for i in result.issues if i.severity == "critical"]
        if critical_issues:
            descriptions = [f"- {i.field}: {i.description}（建议: {i.suggestion}）" for i in critical_issues[:3]]
            return f"质检发现以下关键问题，请修正：\n" + "\n".join(descriptions)
        return "质检未通过，请检查输出完整性。"

    def _parse_issues(self, result: dict) -> list[QualityIssue]:
        """解析 LLM 返回的 issues 列表"""
        issues = []
        for item in result.get("issues", []):
            issues.append(QualityIssue(
                severity=item.get("severity", "warning"),
                category=item.get("category", "completeness"),
                field=item.get("field", ""),
                description=item.get("description", ""),
                expected=item.get("expected", ""),
                actual=item.get("actual", ""),
                suggestion=item.get("suggestion", ""),
            ))
        return issues

    def _calculate_score(self, issues: list[QualityIssue]) -> float:
        """根据 issues 计算质量分数"""
        score = 100.0
        for issue in issues:
            if issue.severity == "critical":
                score -= 20
            elif issue.severity == "warning":
                score -= 5
        return max(0.0, score)
