# -*- coding: utf-8 -*-
"""
agents/quality_agent.py — 质检Agent

职责：完整性检查 + 幻觉检测，发现问题后打回对应 Agent 重做
LLM调用：1次/检查（幻觉检测）
提示词来源：prompts/quality_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import (
    CompetitorData, CompetitorList, ProductAnalysis, PricingAnalysis, MarketAnalysis,
    StrategyReport, QualityIssue, QualityCheckResult, QATimeline, HallucinationCheckStatus,
)
from core.prompt_loader import load as load_prompts
from datetime import datetime
import config
import json


class QualityAgent(BaseAgent):
    """质检 Agent — 完整性检查 + 幻觉检测"""

    MAX_RETRIES = 2
    PASS_SCORE = 70

    # 阶段权重：(critical扣分, warning扣分)
    PHASE_WEIGHTS = {
        "collection": (15, 3),
        "product": (20, 5),
        "pricing": (20, 5),
        "market": (20, 5),
        "strategy": (25, 5),
    }

    # 类别乘数
    CATEGORY_MULTIPLIERS = {
        "completeness": 1.0,
        "hallucination": 1.5,
        "citation": 1.0,
        "schema": 0.8,
    }

    _MEANINGLESS_VALUES = {"未知", "n/a", "暂无", "无", "unknown", "not available", "-"}

    @staticmethod
    def _is_meaningless(text: str) -> bool:
        """判断文本是否为无意义填充值"""
        return text.strip().lower() in QualityAgent._MEANINGLESS_VALUES

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
        self._passed_fields: set[str] = set()  # 已通过质检的字段，避免重复标记

    async def run(self, *args, **kwargs):
        """不直接调用，请使用 check_collection / check_analysis / check_strategy"""
        raise NotImplementedError("QualityAgent 不直接运行，请使用 check_collection/check_analysis/check_strategy")

    # ── Phase 2: 采集数据质检 ──

    async def check_collection(
        self,
        competitors_data: dict[str, CompetitorData],
        original_search_texts: dict[str, str],
        competitor_list: CompetitorList = None,
        attempt: int = 1,
    ) -> QualityCheckResult:
        """Phase 2 质检：检查采集数据"""
        self._log(f"🔍 质检采集数据（第{attempt}次）...")
        issues = []

        # 完整性检查
        issues.extend(self._check_collection_completeness(competitors_data, competitor_list))

        # 幻觉检测（仅 LLM 模式）
        hallucination_status = HallucinationCheckStatus.SKIPPED.value
        if config.ENABLE_LLM and original_search_texts:
            hallucination_issues, hallucination_status, fail_reason = await self._check_collection_hallucination(
                competitors_data, original_search_texts
            )
            # 过滤掉已通过的字段（避免重复标记同一字段为幻觉）
            new_hallucination = []
            for hi in hallucination_issues:
                if hi.field and hi.field not in self._passed_fields:
                    new_hallucination.append(hi)
                elif not hi.field:
                    new_hallucination.append(hi)
            issues.extend(new_hallucination)
            if hallucination_status == HallucinationCheckStatus.FAILED.value:
                issues.append(QualityIssue(
                    severity="warning", category="hallucination",
                    field="__hallucination_check__",
                    description=f"幻觉检测未能完成（{fail_reason}），结果可信度未知",
                    suggestion="建议重新运行质检",
                ))

        # 引用有效性检查（规则引擎）
        all_citations = []
        all_output_ids = []
        for d in competitors_data.values():
            all_citations.extend(d.citations)
            for fi in d.product_features:
                all_output_ids.extend(fi.citations)
            for pt in d.pricing_tiers:
                all_output_ids.extend(pt.citations)
        if all_citations:
            issues.extend(self._check_citation_validity(all_citations, list(set(all_output_ids))))

        score = self._calculate_score(issues, phase="collection", competitor_count=len(competitors_data))
        passed = score >= self.PASS_SCORE

        # 计算 hallucination_score
        h_issues = [i for i in issues if i.category in ("hallucination", "citation")]
        critical_d, warning_d = self.PHASE_WEIGHTS.get("collection", (20, 5))
        h_deduction = sum(
            (critical_d if i.severity == "critical" else warning_d)
            * self.CATEGORY_MULTIPLIERS.get(i.category, 1.0)
            for i in h_issues
        )
        h_score = max(0.0, 100.0 - h_deduction)
        if hallucination_status == HallucinationCheckStatus.FAILED.value:
            h_score = 60.0

        result = QualityCheckResult(
            phase="collection",
            target_agent="CollectionAgent",
            passed=passed,
            score=score,
            issues=issues,
            checked_at=datetime.now().isoformat(timespec="seconds"),
            attempt=attempt,
            hallucination_status=hallucination_status,
            hallucination_score=h_score,
        )

        # 记录已通过的字段（避免下一轮重复标记为幻觉）
        if passed:
            for name, data in competitors_data.items():
                for field_name in ["strengths", "weaknesses", "channels", "market_share", "user_reviews"]:
                    val = getattr(data, field_name, "")
                    if val and len(str(val).strip()) > 10:
                        self._passed_fields.add(f"{name}.{field_name}")
        else:
            # 未通过时，记录本轮没有幻觉问题的字段为"已通过"
            halluc_fields = {i.field for i in issues if i.category == "hallucination" and i.field}
            for name, data in competitors_data.items():
                for field_name in ["strengths", "weaknesses", "channels", "market_share", "user_reviews"]:
                    field_key = f"{name}.{field_name}"
                    if field_key not in halluc_fields:
                        val = getattr(data, field_name, "")
                        if val and len(str(val).strip()) > 10:
                            self._passed_fields.add(field_key)

        status = "✅ 通过" if passed else "❌ 未通过"
        self._log(f"   采集数据质检: {status} (分数: {score}, 问题: {len(issues)})")
        return result

    def _check_collection_completeness(
        self,
        competitors_data: dict[str, CompetitorData],
        competitor_list: CompetitorList = None,
    ) -> list[QualityIssue]:
        """采集数据完整性检查（规则引擎）"""
        issues = []

        # 覆盖性检查
        if competitor_list:
            expected_names = {c.name for c in competitor_list.competitors}
            actual_names = set(competitors_data.keys())
            missing = expected_names - actual_names
            for name in missing:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field=f"competitors.{name}",
                    description=f"竞品 '{name}' 未被采集",
                    suggestion="重新搜索该竞品的数据",
                ))

        for name, data in competitors_data.items():
            if not data.name:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field=f"{name}.name",
                    description="竞品名称为空",
                    suggestion="确保采集到竞品名称",
                ))

            # 产品功能检查
            if not data.product_features:
                issues.append(QualityIssue(
                    severity="critical", category="completeness",
                    field=f"{name}.product_features",
                    description="产品功能列表为空",
                    suggestion="重新搜索该竞品的产品功能信息",
                ))
            else:
                if len(data.product_features) < 2:
                    issues.append(QualityIssue(
                        severity="warning", category="completeness",
                        field=f"{name}.product_features",
                        description=f"产品功能仅 {len(data.product_features)} 项，可能采集不完整",
                        suggestion="补充该竞品的产品功能信息",
                    ))
                for i, fi in enumerate(data.product_features):
                    if not fi.name:
                        issues.append(QualityIssue(
                            severity="critical", category="completeness",
                            field=f"{name}.product_features[{i}].name",
                            description="功能项名称为空",
                            suggestion="确保每个功能项都有名称",
                        ))

            # 定价层级检查
            if not data.pricing_tiers:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.pricing_tiers",
                    description="定价层级为空",
                    suggestion="补充该竞品的定价信息",
                ))
            else:
                if len(data.pricing_tiers) < 2:
                    issues.append(QualityIssue(
                        severity="warning", category="completeness",
                        field=f"{name}.pricing_tiers",
                        description=f"定价层级仅 {len(data.pricing_tiers)} 个，可能采集不完整",
                        suggestion="补充该竞品的定价层级信息",
                    ))
                for i, pt in enumerate(data.pricing_tiers):
                    if not pt.tier_name:
                        issues.append(QualityIssue(
                            severity="critical", category="completeness",
                            field=f"{name}.pricing_tiers[{i}].tier_name",
                            description="定价层级名称为空",
                            suggestion="确保每个定价层级都有名称",
                        ))

            # 市场份额检查（含无意义文本检测）
            if not data.market_share:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.market_share",
                    description="市场份额信息为空",
                    suggestion="补充该竞品的市场份额数据",
                ))
            elif self._is_meaningless(data.market_share):
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.market_share",
                    description=f"市场份额为无意义文本: '{data.market_share}'",
                    suggestion="补充该竞品的实际市场份额数据",
                ))

            # 文本字段检查（空或过短）
            for field_name, display_name, search_hint in [
                ("strengths", "优势", "竞争优势 核心优势 行业地位"),
                ("weaknesses", "劣势", "劣势 不足 用户吐槽"),
                ("channels", "渠道", "渠道策略 推广方式 合作伙伴 生态"),
                ("user_reviews", "用户评价", "用户评价 口碑 评分"),
            ]:
                text = getattr(data, field_name)
                if not text or not text.strip():
                    issues.append(QualityIssue(
                        severity="warning", category="completeness",
                        field=f"{name}.{field_name}",
                        description=f"{display_name}信息为空，需要补充搜索",
                        suggestion=f"搜索 '{name} {search_hint}' 补充{display_name}数据",
                    ))
                elif len(text.strip()) < 20:
                    issues.append(QualityIssue(
                        severity="warning", category="completeness",
                        field=f"{name}.{field_name}",
                        description=f"{display_name}内容过短（{len(text.strip())} 字符），可能为无效填充",
                        suggestion=f"搜索 '{name} {search_hint}' 补充{display_name}数据",
                    ))

            # 引用来源检查
            if not data.citations:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.citations",
                    description="无引用来源",
                    suggestion="确保采集数据有来源引用",
                ))
            elif len(data.citations) < 2:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field=f"{name}.citations",
                    description=f"引用来源仅 {len(data.citations)} 条，数据可信度较低",
                    suggestion="补充更多引用来源",
                ))

        return issues

    async def _check_collection_hallucination(
        self,
        competitors_data: dict[str, CompetitorData],
        original_search_texts: dict[str, str],
    ) -> tuple[list[QualityIssue], str]:
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
                "citations": [{"id": c.id, "title": c.title[:80], "query": c.query} for c in data.citations[:30]],
            }

        # 截断原始搜索文本
        search_texts_limited = {}
        for name, text in original_search_texts.items():
            search_texts_limited[name] = text[:8000]

        prompt = self._prompt_check_collection.format(
            original_search_texts=json.dumps(search_texts_limited, ensure_ascii=False, indent=2),
            competitors_data_json=json.dumps(data_summary, ensure_ascii=False, indent=2),
        )

        result, reason = self.ask_llm_json_with_reason(prompt, max_tokens=4096)
        if not result:
            self._log(f"   ⚠️ 幻觉检测失败: {reason}")
            return [], HallucinationCheckStatus.FAILED.value, reason

        issues = self._parse_issues(result)
        hallucination_issues = [i for i in issues if i.category == "hallucination"]
        status = HallucinationCheckStatus.FOUND.value if hallucination_issues else HallucinationCheckStatus.PASSED.value
        return issues, status, ""

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
        hallucination_status = HallucinationCheckStatus.SKIPPED.value
        if config.ENABLE_LLM:
            hallucination_issues, hallucination_status, fail_reason = await self._check_analysis_hallucination(
                analysis_type, analysis, competitors_data
            )
            issues.extend(hallucination_issues)
            if hallucination_status == HallucinationCheckStatus.FAILED.value:
                issues.append(QualityIssue(
                    severity="warning", category="hallucination",
                    field="__hallucination_check__",
                    description=f"幻觉检测未能完成（{fail_reason}），结果可信度未知",
                    suggestion="建议重新运行质检",
                ))

        score = self._calculate_score(issues, phase=analysis_type)
        passed = score >= self.PASS_SCORE

        # 计算 hallucination_score
        h_issues = [i for i in issues if i.category in ("hallucination", "citation")]
        critical_d, warning_d = self.PHASE_WEIGHTS.get(analysis_type, (20, 5))
        h_deduction = sum(
            (critical_d if i.severity == "critical" else warning_d)
            * self.CATEGORY_MULTIPLIERS.get(i.category, 1.0)
            for i in h_issues
        )
        h_score = max(0.0, 100.0 - h_deduction)
        if hallucination_status == HallucinationCheckStatus.FAILED.value:
            h_score = 60.0

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
            hallucination_status=hallucination_status,
            hallucination_score=h_score,
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
            elif len(pa.feature_matrix) < 3:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="feature_matrix",
                    description=f"功能矩阵仅 {len(pa.feature_matrix)} 行，维度可能不足",
                    suggestion="补充更多功能对比维度",
                ))
            if not pa.competitive_advantages:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="competitive_advantages",
                    description="竞争优势为空",
                    suggestion="补充竞争优势分析",
                ))
            if not pa.differentiation_points:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="differentiation_points",
                    description="差异化要点为空",
                    suggestion="补充差异化分析",
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
            else:
                compared = {pc.competitor for pc in pra.pricing_comparison}
                expected = set(competitors_data.keys())
                missing = expected - compared
                for name in missing:
                    issues.append(QualityIssue(
                        severity="critical", category="completeness",
                        field=f"pricing_comparison.{name}",
                        description=f"定价对比未覆盖竞品 '{name}'",
                        suggestion="补充该竞品的定价对比数据",
                    ))
            if not pra.value_ranking:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="value_ranking",
                    description="性价比排名为空",
                    suggestion="补充性价比排名",
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
            if not ma.user_reputation:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="user_reputation",
                    description="用户口碑数据为空",
                    suggestion="补充用户口碑分析",
                ))
            if not ma.user_profiles:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="user_profiles",
                    description="用户画像数据为空",
                    suggestion="补充用户画像分析",
                ))
            if not ma.channel_analysis:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="channel_analysis",
                    description="渠道分析为空",
                    suggestion="补充渠道策略分析",
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
    ) -> tuple[list[QualityIssue], str]:
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

        result, reason = self.ask_llm_json_with_reason(prompt, max_tokens=4096)
        if not result:
            self._log(f"   ⚠️ {analysis_type} 幻觉检测失败: {reason}")
            return [], HallucinationCheckStatus.FAILED.value, reason

        issues = self._parse_issues(result)
        hallucination_issues = [i for i in issues if i.category == "hallucination"]
        status = HallucinationCheckStatus.FOUND.value if hallucination_issues else HallucinationCheckStatus.PASSED.value
        return issues, status, ""

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
        hallucination_status = HallucinationCheckStatus.SKIPPED.value
        if config.ENABLE_LLM:
            hallucination_issues, hallucination_status, fail_reason = await self._check_strategy_hallucination(
                report, product_analysis, pricing_analysis, market_analysis
            )
            issues.extend(hallucination_issues)
            if hallucination_status == HallucinationCheckStatus.FAILED.value:
                issues.append(QualityIssue(
                    severity="warning", category="hallucination",
                    field="__hallucination_check__",
                    description=f"幻觉检测未能完成（{fail_reason}），结果可信度未知",
                    suggestion="建议重新运行质检",
                ))

        score = self._calculate_score(issues, phase="strategy")
        passed = score >= self.PASS_SCORE

        # 计算 hallucination_score
        h_issues = [i for i in issues if i.category in ("hallucination", "citation")]
        critical_d, warning_d = self.PHASE_WEIGHTS.get("strategy", (20, 5))
        h_deduction = sum(
            (critical_d if i.severity == "critical" else warning_d)
            * self.CATEGORY_MULTIPLIERS.get(i.category, 1.0)
            for i in h_issues
        )
        h_score = max(0.0, 100.0 - h_deduction)
        if hallucination_status == HallucinationCheckStatus.FAILED.value:
            h_score = 60.0

        result = QualityCheckResult(
            phase="strategy",
            target_agent="StrategyAgent",
            passed=passed,
            score=score,
            issues=issues,
            checked_at=datetime.now().isoformat(timespec="seconds"),
            attempt=attempt,
            hallucination_status=hallucination_status,
            hallucination_score=h_score,
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
        if not report.differentiation_strategy:
            issues.append(QualityIssue(
                severity="critical", category="completeness",
                field="differentiation_strategy",
                description="差异化策略为空",
                suggestion="确保策略报告包含差异化策略",
            ))
        if not report.action_plan:
            issues.append(QualityIssue(
                severity="critical", category="completeness",
                field="action_plan",
                description="行动方案为空",
                suggestion="确保策略报告包含行动方案",
            ))
        else:
            if len(report.action_plan) < 2:
                issues.append(QualityIssue(
                    severity="warning", category="completeness",
                    field="action_plan",
                    description=f"行动方案仅 {len(report.action_plan)} 项，建议补充",
                    suggestion="补充更多行动方案项",
                ))
            for i, item in enumerate(report.action_plan):
                if not item.action:
                    issues.append(QualityIssue(
                        severity="critical", category="completeness",
                        field=f"action_plan[{i}].action",
                        description="行动方案项内容为空",
                        suggestion="确保每个行动方案都有具体描述",
                    ))
                if not item.priority:
                    issues.append(QualityIssue(
                        severity="warning", category="completeness",
                        field=f"action_plan[{i}].priority",
                        description="行动方案项优先级为空",
                        suggestion="确保每个行动方案都有优先级",
                    ))
        if not report.risk_assessment:
            issues.append(QualityIssue(
                severity="warning", category="completeness",
                field="risk_assessment",
                description="风险评估为空",
                suggestion="补充风险评估内容",
            ))
        if not report.citation_index or not report.citation_index.citations:
            issues.append(QualityIssue(
                severity="warning", category="completeness",
                field="citation_index",
                description="引用索引为空",
                suggestion="补充引用来源",
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
    ) -> tuple[list[QualityIssue], str]:
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

        result, reason = self.ask_llm_json_with_reason(prompt, max_tokens=4096)
        if not result:
            self._log(f"   ⚠️ 策略报告幻觉检测失败: {reason}")
            return [], HallucinationCheckStatus.FAILED.value, reason

        issues = self._parse_issues(result)
        hallucination_issues = [i for i in issues if i.category == "hallucination"]
        status = HallucinationCheckStatus.FOUND.value if hallucination_issues else HallucinationCheckStatus.PASSED.value
        return issues, status, ""

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

    def extract_missing_fields(self, result: QualityCheckResult,
                               competitors_data: dict[str, 'CompetitorData'] | None = None) -> dict[str, list[str]]:
        """从质检结果和实际数据中提取每个竞品的缺失/截断字段。

        检测三种情况：
        1. 字段为空
        2. 字段内容被截断（末尾语义不完整）
        3. 质检 issue 标记的幻觉/缺失字段

        Returns:
            dict[str, list[str]]: {竞品名: [需要补充的字段名列表]}
        """
        missing: dict[str, list[str]] = {}
        supplementable = {"strengths", "weaknesses", "channels", "market_share", "user_reviews"}
        pricing_check = {"pricing_tiers"}

        def _is_truncated(text: str) -> bool:
            """判断文本是否被截断（末尾语义不完整）"""
            if not text or len(text.strip()) < 10:
                return False
            text = text.strip()
            # 末尾不是正常标点结尾，且长度较长，大概率被截断
            normal_endings = {"。", "！", "？", ".", "!", "?", "；", "」", "）", "》", "\"", "'", "…"}
            if text[-1] in normal_endings:
                return False
            # 长文本且末尾无标点 → 截断
            if len(text) > 50:
                return True
            return False

        def _add_missing(comp_name: str, field_name: str):
            if comp_name not in missing:
                missing[comp_name] = []
            if field_name not in missing[comp_name]:
                missing[comp_name].append(field_name)

        # 方式1：直接检查数据（空字段 + 截断字段）
        if competitors_data:
            for name, data in competitors_data.items():
                for field_name in supplementable:
                    val = getattr(data, field_name, "")
                    if not val or not str(val).strip():
                        _add_missing(name, field_name)
                    elif _is_truncated(str(val)):
                        _add_missing(name, field_name)
                # pricing_tiers 检查
                if not data.pricing_tiers:
                    _add_missing(name, "pricing_tiers")

        # 方式2：从 issue 中提取（空字段 + 截断字段 + 幻觉字段）
        for issue in result.issues:
            if issue.severity != "critical":
                continue
            desc = issue.description or ""
            is_truncation = "截断" in desc or "未完成" in desc or "语义不完整" in desc
            is_empty = "为空" in desc or "缺失" in desc or "空白" in desc
            is_hallucination = "幻觉" in desc or "unsupported" in desc.lower() or "虚构" in desc or "无依据" in desc or "编造" in desc

            if not (is_truncation or is_empty or is_hallucination):
                continue

            field = issue.field
            if not field:
                continue

            # 解析 field 中的竞品名和字段名
            targets = []  # [(comp_name, field_name), ...]

            if "." in field:
                parts = field.split(".")
                if len(parts) >= 2:
                    comp_name = parts[0]
                    field_name = parts[1].split("[")[0].split("、")[0]
                    targets.append((comp_name, field_name))

            # 处理 "微信视频号.strengths、微信视频号.weaknesses" 格式
            if "、" in field:
                for sub in field.split("、"):
                    sub = sub.strip()
                    if "." in sub:
                        parts = sub.split(".")
                        if len(parts) >= 2:
                            targets.append((parts[0], parts[1].split("[")[0]))

            supplementable_all = supplementable | pricing_check
            for comp_name, field_name in targets:
                if field_name in supplementable_all:
                    _add_missing(comp_name, field_name)

        return missing

    def build_supplement_feedback(self, missing_fields: dict[str, list[str]]) -> str:
        """根据缺失字段构造给 CollectionAgent 的补充搜索反馈。

        Args:
            missing_fields: extract_missing_fields 的返回值

        Returns:
            结构化的反馈文本，CollectionAgent 可解析
        """
        if not missing_fields:
            return ""

        lines = ["[补充搜索指令] 以下竞品的特定字段数据缺失，请针对性搜索补充："]
        field_queries = {
            "strengths": "竞争优势 核心优势 行业地位",
            "weaknesses": "劣势 不足 用户吐槽 差评",
            "channels": "渠道策略 推广方式 合作伙伴 生态",
            "market_share": "市场份额 用户量 DAU MAU 市占率",
            "pricing_tiers": "定价 价格 收费标准 会员 套餐",
            "user_reviews": "用户评价 口碑 评分 好评 差评",
        }
        for comp_name, fields in missing_fields.items():
            for f in fields:
                query = field_queries.get(f, f)
                lines.append(f"- 竞品「{comp_name}」缺少 {f}，请搜索: {comp_name} {query}")

        return "\n".join(lines)

    def _check_citation_validity(
        self,
        citations: list,
        citation_ids_in_output: list[str],
    ) -> list[QualityIssue]:
        """引用有效性检查（规则引擎）"""
        issues = []
        citation_id_set = {c.id for c in citations}

        # 只在有输出引用 ID 时才检查孤立引用（避免空列表导致全部标记为孤立）
        if citation_ids_in_output:
            # 输出中引用的 ID 在 citations 列表中不存在
            for cid in citation_ids_in_output:
                if cid not in citation_id_set:
                    issues.append(QualityIssue(
                        severity="critical", category="citation",
                        field=f"citations.{cid}",
                        description=f"引用了不存在的来源 ID: '{cid}'",
                        suggestion="移除无效引用或补充来源数据",
                    ))

            # citations 中的引用在输出中从未被使用
            used_set = set(citation_ids_in_output)
            for c in citations:
                if c.id not in used_set:
                    issues.append(QualityIssue(
                        severity="warning", category="citation",
                        field=f"citations.{c.id}",
                        description=f"引用来源 '{c.id}' 未被使用（孤立引用）",
                        suggestion="在分析中引用该来源或移除冗余数据",
                    ))

        # 始终检查引用信息完整性
        for c in citations:
            if not c.title:
                issues.append(QualityIssue(
                    severity="warning", category="citation",
                    field=f"citations.{c.id}.title",
                    description=f"引用 '{c.id}' 的 title 为空",
                    suggestion="补充引用标题",
                ))
            if not c.url:
                issues.append(QualityIssue(
                    severity="warning", category="citation",
                    field=f"citations.{c.id}.url",
                    description=f"引用 '{c.id}' 的 url 为空",
                    suggestion="补充引用链接",
                ))

        return issues

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

    def _calculate_score(
        self,
        issues: list[QualityIssue],
        phase: str = "collection",
        competitor_count: int = 1,
    ) -> float:
        """根据 issues 计算质量分数（多维度加权）"""
        critical_deduction, warning_deduction = self.PHASE_WEIGHTS.get(phase, (20, 5))

        # 分离 completeness 和 hallucination 类别的 issues
        completeness_issues = [i for i in issues if i.category in ("completeness", "schema")]
        hallucination_issues = [i for i in issues if i.category == "hallucination"]
        citation_issues = [i for i in issues if i.category == "citation"]

        # completeness 部分
        completeness_deduction = 0
        for issue in completeness_issues:
            base = critical_deduction if issue.severity == "critical" else warning_deduction
            multiplier = self.CATEGORY_MULTIPLIERS.get(issue.category, 1.0)
            completeness_deduction += base * multiplier

        # 采集阶段按竞品数量归一化
        if phase == "collection" and competitor_count > 1:
            completeness_deduction = completeness_deduction / competitor_count

        completeness_score = max(0.0, 100.0 - completeness_deduction)

        # hallucination 部分（包含 citation 类别的 issue）
        hallucination_deduction = 0
        for issue in hallucination_issues + citation_issues:
            base = critical_deduction if issue.severity == "critical" else warning_deduction
            multiplier = self.CATEGORY_MULTIPLIERS.get(issue.category, 1.0)
            hallucination_deduction += base * multiplier

        hallucination_score = max(0.0, 100.0 - hallucination_deduction)

        # 加权合并
        final_score = completeness_score * 0.6 + hallucination_score * 0.4
        return round(final_score, 1)
