# -*- coding: utf-8 -*-
"""
agents/strategy_agent.py — 策略建议Agent

职责：综合三维分析，输出差异化定位建议和行动方案
LLM调用：1次
外部工具：无
提示词来源：prompts/strategy_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import (
    ProductAnalysis, PricingAnalysis, MarketAnalysis,
    StrategyReport, ActionItem, CitationIndex, CompetitorData,
    TargetProductIntro, IntroItem, Citation,
    SWOTAnalysis, SWOTQuadrant, SWOTCrossStrategy
)
from core.search_client import SearchClient
from core.prompt_loader import load as load_prompts
import config
import json


class StrategyAgent(BaseAgent):
    """策略建议Agent — 综合三维分析输出策略"""

    def __init__(self):
        prompts = load_prompts("strategy_agent")
        super().__init__(
            agent_id="StrategyAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_strategy = prompts["prompt_strategy"]
        self.search_client = SearchClient()

    async def run(self, product_name: str,
                  competitor_count: int,
                  product_analysis: ProductAnalysis,
                  pricing_analysis: PricingAnalysis,
                  market_analysis: MarketAnalysis,
                  target_product_data: CompetitorData | None = None,
                  competitors_data: dict[str, CompetitorData] | None = None,
                  feedback: str = "") -> StrategyReport:
        """
        主运行逻辑：综合三维分析输出策略

        Args:
            product_name: 产品名称
            competitor_count: 竞品数量
            product_analysis: 产品分析结果
            pricing_analysis: 定价分析结果
            market_analysis: 市场分析结果

        Returns:
            StrategyReport: 策略建议报告
        """
        self._log("🎯 开始策略建议...")

        # 构建全局引用索引
        citation_index = CitationIndex()
        if target_product_data:
            for cite in target_product_data.citations:
                citation_index.add(cite)
        if competitors_data:
            for data in competitors_data.values():
                for cite in data.citations:
                    citation_index.add(cite)

        # 构建三维分析汇总文本
        analysis_text = self._build_analysis_text(
            product_name, product_analysis, pricing_analysis, market_analysis
        )

        if feedback:
            analysis_text += f"\n\n### 质检反馈（请据此修正）\n{feedback}"

        if config.ENABLE_LLM:
            intro_supplement_cites = []
            if self._needs_target_intro_supplement(target_product_data):
                intro_supplement_cites = await self._async_supplement_target_intro_sources(
                    product_name, len(citation_index.citations)
                )
                for cite in intro_supplement_cites:
                    citation_index.add(cite)

            target_intro_context = self._build_target_intro_context(
                product_name,
                target_product_data,
                product_analysis,
                pricing_analysis,
                market_analysis,
                intro_supplement_cites,
            )
            prompt = self._prompt_strategy.format(
                product_name=product_name,
                target_intro_context=target_intro_context,
                analysis_text=analysis_text,
            )
            result, truncated = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=6144)
            if result and truncated:
                # 截断了：提升 max_tokens 重试一次
                self._log("⚠️ 策略输出被截断，提升 max_tokens 重试...")
                result2, truncated2 = await self.async_ask_llm_json_with_truncation_check(prompt, max_tokens=8192)
                if result2:
                    if truncated2:
                        self._log("⚠️ 8192 tokens 仍截断，使用已有结果（部分内容可能不完整）")
                    else:
                        result = result2  # 用完整结果替换
            if result:
                report = self._parse_strategy_report(product_name, competitor_count, result)
                report.citation_index = citation_index
                report.target_product_data = target_product_data
                self._log(f"✅ 策略建议完成: {len(report.action_plan)}项行动方案")
                return report
            else:
                self._log("⚠️ LLM策略建议失败，降级到规则引擎")

        return self._rule_strategy(product_name, competitor_count,
                                    product_analysis, pricing_analysis, market_analysis,
                                    citation_index, target_product_data)

    def _build_analysis_text(self, product_name: str,
                              product_analysis: ProductAnalysis,
                              pricing_analysis: PricingAnalysis,
                              market_analysis: MarketAnalysis) -> str:
        """构建三维分析汇总文本，附带引用编号"""
        lines = []

        # 产品分析
        lines.append("## 一、产品分析")
        if product_analysis.feature_matrix:
            features = [fm.feature for fm in product_analysis.feature_matrix]
            lines.append(f"对比功能维度: {', '.join(features[:10])}")
        if product_analysis.competitive_advantages:
            for adv in product_analysis.competitive_advantages[:5]:
                cite_tag = f" [{','.join(adv.citations)}]" if adv.citations else ""
                lines.append(f"- vs {adv.competitor}: 我方优势={adv.our_advantage}, 对方优势={adv.their_advantage}{cite_tag}")
        if product_analysis.differentiation_points:
            lines.append(f"差异化点: {', '.join(product_analysis.differentiation_points[:5])}")
        lines.append(f"摘要: {product_analysis.summary}")

        # 定价分析
        lines.append("\n## 二、定价分析")
        if pricing_analysis.pricing_comparison:
            for pc in pricing_analysis.pricing_comparison[:5]:
                cite_tag = f" [{','.join(pc.citations)}]" if pc.citations else ""
                lines.append(f"- {pc.competitor}: 免费={pc.free_tier}, 付费={pc.paid_tier}, 模式={pc.pricing_model}{cite_tag}")
        lines.append(f"策略分析: {pricing_analysis.pricing_strategy_analysis}")
        if pricing_analysis.value_ranking:
            lines.append(f"性价比排名: {' > '.join(pricing_analysis.value_ranking)}")
        lines.append(f"摘要: {pricing_analysis.summary}")

        # 市场分析
        lines.append("\n## 三、市场分析")
        if market_analysis.market_share_data:
            for ms in market_analysis.market_share_data[:5]:
                cite_tag = f" [{','.join(ms.citations)}]" if ms.citations else ""
                lines.append(f"- {ms.competitor}: 份额={ms.share_estimate}, 趋势={ms.trend}{cite_tag}")
        lines.append(f"增长趋势: {market_analysis.growth_trends}")
        lines.append(f"渠道分析: {market_analysis.channel_analysis}")
        lines.append(f"摘要: {market_analysis.summary}")

        return "\n".join(lines)

    @staticmethod
    def _dedupe_ids(ids: list[str]) -> list[str]:
        seen = set()
        result = []
        for cid in ids:
            if cid and cid not in seen:
                seen.add(cid)
                result.append(cid)
        return result

    @staticmethod
    def _find_feature_value(values_dict: dict, target_name: str) -> str:
        """从 feature_matrix.values 中查找我方产品状态，兼容模糊键名。"""
        if not values_dict:
            return ""
        if target_name in values_dict:
            return values_dict[target_name]
        for key, val in values_dict.items():
            if target_name in key or key in target_name:
                return val
        return ""

    @staticmethod
    def _trim_text(text: str, limit: int = 140) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip("，。；;、 ") + "..."

    def _pick_query_citations(self, citations: list[Citation],
                              keywords: list[str],
                              limit: int = 3) -> list[str]:
        ids = []
        for cite in citations or []:
            query = cite.query or ""
            if any(keyword in query for keyword in keywords):
                ids.append(cite.id)
            if len(ids) >= limit:
                break
        return ids

    def _needs_target_intro_supplement(self, target_product_data: CompetitorData | None) -> bool:
        """仅在目标产品介绍素材明显不足时，补一轮轻量搜索。"""
        if not target_product_data:
            return True
        empty_core_fields = sum(
            1
            for value in (
                target_product_data.market_share,
                target_product_data.user_reviews,
                target_product_data.strengths,
            )
            if not (value or "").strip()
        )
        return (
            len(target_product_data.citations) < 6
            or len(target_product_data.product_features) < 2
            or not target_product_data.pricing_tiers
            or empty_core_fields >= 2
        )

    def _supplement_target_intro_sources(self, product_name: str,
                                         base_count: int = 0) -> list[Citation]:
        """为目标产品介绍补充少量通用介绍类来源，不回写采集产物。"""
        self._log(f"   🧩 目标产品介绍素材不足，为 {product_name} 补充介绍类搜索")
        queries = [
            f"{product_name} 产品简介 核心功能 官方介绍",
            f"{product_name} 产品定位 用户价值 平台介绍",
        ]
        results = self.search_client.batch_search(queries)
        citations = []
        counter = base_count
        for i, sr in enumerate(results):
            for ref in sr.get("references", []):
                ref_url = ref.get("url", "")
                ref_title = ref.get("title", "")
                if not ref_url and not ref_title:
                    continue
                citations.append(Citation(
                    id=f"{product_name}:intro_sup_{i}:r{counter}",
                    title=ref_title,
                    url=ref_url,
                    snippet=ref.get("content", "") or ref.get("summary", ""),
                    site_name=ref.get("site_name", ""),
                    query=sr.get("query", ""),
                    competitor=product_name,
                ))
                counter += 1
        return citations

    async def _async_supplement_target_intro_sources(self, product_name: str,
                                                     base_count: int = 0) -> list[Citation]:
        """为目标产品介绍异步补充少量通用介绍类来源，不回写采集产物。"""
        self._log(f"   🧩 目标产品介绍素材不足，为 {product_name} 补充介绍类搜索")
        queries = [
            f"{product_name} 产品简介 核心功能 官方介绍",
            f"{product_name} 产品定位 用户价值 平台介绍",
        ]
        results = await self.search_client.async_batch_search(queries)
        citations = []
        counter = base_count
        for i, sr in enumerate(results):
            for ref in sr.get("references", []):
                ref_url = ref.get("url", "")
                ref_title = ref.get("title", "")
                if not ref_url and not ref_title:
                    continue
                citations.append(Citation(
                    id=f"{product_name}:intro_sup_{i}:r{counter}",
                    title=ref_title,
                    url=ref_url,
                    snippet=ref.get("content", "") or ref.get("summary", ""),
                    site_name=ref.get("site_name", ""),
                    query=sr.get("query", ""),
                    competitor=product_name,
                ))
                counter += 1
        return citations

    def _build_target_intro_context(self, product_name: str,
                                    target_product_data: CompetitorData | None,
                                    product_analysis: ProductAnalysis,
                                    pricing_analysis: PricingAnalysis,
                                    market_analysis: MarketAnalysis,
                                    supplemental_citations: list[Citation] | None = None) -> str:
        """构建目标产品介绍的专用 LLM 素材，尽量给结构化事实而不是全文。"""
        lines = [f"## 目标产品：{product_name}"]
        target_citations = list(target_product_data.citations) if target_product_data else []
        target_citations.extend(supplemental_citations or [])

        if target_product_data:
            lines.append("\n### 原始采集事实")
            if target_product_data.product_features:
                lines.append("- 功能项：")
                feature_refs = self._pick_query_citations(target_citations, ["产品功能", "功能介绍", "核心功能"], 3)
                ref_text = f" [{','.join(feature_refs)}]" if feature_refs else ""
                for fi in target_product_data.product_features[:5]:
                    lines.append(
                        f"  - {fi.name}: {self._trim_text(fi.description, 120)}{ref_text}"
                    )
            if target_product_data.pricing_tiers:
                lines.append("- 定价层级：")
                for pt in target_product_data.pricing_tiers[:4]:
                    cites = pt.citations or self._pick_query_citations(
                        target_citations, ["定价", "价格", "收费", "会员", "套餐"], 2
                    )
                    cite_text = f" [{','.join(cites)}]" if cites else ""
                    feat_text = "；".join(pt.features[:2]) if pt.features else ""
                    lines.append(
                        f"  - {pt.tier_name}: {self._trim_text(pt.price, 100)}"
                        f"{'；' + self._trim_text(feat_text, 60) if feat_text else ''}{cite_text}"
                    )
            if target_product_data.market_share:
                market_refs = self._pick_query_citations(target_citations, ["市场份额", "用户量", "用户规模", "DAU", "MAU"], 3)
                ref_tag = f" [{','.join(market_refs)}]" if market_refs else ""
                lines.append(f"- 市场数据：{self._trim_text(target_product_data.market_share, 180)}{ref_tag}")
            if target_product_data.user_reviews:
                review_refs = self._pick_query_citations(target_citations, ["用户评价", "用户反馈", "使用场景", "评测"], 3)
                ref_tag = f" [{','.join(review_refs)}]" if review_refs else ""
                lines.append(f"- 用户评价：{self._trim_text(target_product_data.user_reviews, 180)}{ref_tag}")
            if target_product_data.strengths:
                strength_refs = self._pick_query_citations(target_citations, ["竞争优势", "核心优势", "行业地位", "优势"], 3)
                ref_tag = f" [{','.join(strength_refs)}]" if strength_refs else ""
                lines.append(f"- 优势：{self._trim_text(target_product_data.strengths, 180)}{ref_tag}")
            if target_product_data.weaknesses:
                weakness_refs = self._pick_query_citations(target_citations, ["劣势", "不足", "用户吐槽", "差评"], 3)
                ref_tag = f" [{','.join(weakness_refs)}]" if weakness_refs else ""
                lines.append(f"- 劣势：{self._trim_text(target_product_data.weaknesses, 180)}{ref_tag}")
            if target_product_data.channels:
                channel_refs = self._pick_query_citations(target_citations, ["渠道", "推广", "合作伙伴", "生态"], 3)
                ref_tag = f" [{','.join(channel_refs)}]" if channel_refs else ""
                lines.append(f"- 渠道：{self._trim_text(target_product_data.channels, 180)}{ref_tag}")

        lines.append("\n### 三维分析中与我方产品直接相关的结构化结果")
        for fm in product_analysis.feature_matrix[:10]:
            value = self._find_feature_value(fm.values, product_name)
            if value in ("✅", "🔶", "✓", "支持", "部分支持"):
                own_cites = [cid for cid in fm.citations if cid.startswith(product_name + ":")]
                cite_tag = f" [{','.join(own_cites)}]" if own_cites else ""
                lines.append(f"- 功能矩阵：{fm.feature} = {value}{cite_tag}")

        for pc in pricing_analysis.pricing_comparison:
            if pc.competitor == product_name:
                cite_tag = f" [{','.join(pc.citations)}]" if pc.citations else ""
                lines.append(
                    f"- 定价分析：免费={self._trim_text(pc.free_tier, 90)}；"
                    f"付费={self._trim_text(pc.paid_tier, 130)}；"
                    f"模式={self._trim_text(pc.pricing_model, 90)}{cite_tag}"
                )
                break

        for ms in market_analysis.market_share_data:
            if ms.competitor == product_name:
                cite_tag = f" [{','.join(ms.citations)}]" if ms.citations else ""
                lines.append(
                    f"- 市场分析：份额/规模={self._trim_text(ms.share_estimate, 120)}；趋势={ms.trend}{cite_tag}"
                )
                break

        rep = market_analysis.user_reputation.get(product_name)
        if rep:
            cite_tag = f" [{','.join(rep.citations)}]" if rep.citations else ""
            lines.append(f"- 用户口碑：评分={rep.score}；关键词={', '.join(rep.keywords[:6])}{cite_tag}")

        profile = market_analysis.user_profiles.get(product_name)
        if profile:
            cite_tag = f" [{','.join(profile.citations)}]" if profile.citations else ""
            lines.append(
                f"- 用户画像：目标用户={self._trim_text(profile.target_audience, 80)}；"
                f"场景={', '.join(profile.use_cases[:4])}；痛点={', '.join(profile.pain_points[:4])}{cite_tag}"
            )

        if supplemental_citations:
            lines.append("\n### 补充介绍类来源摘录")
            for cite in supplemental_citations[:4]:
                lines.append(
                    f"- [{cite.id}] {cite.title}: {self._trim_text(cite.snippet, 150)}"
                )

        if target_citations:
            lines.append("\n### 可用引用 ID")
            lines.append(self.build_citations_text(target_citations[:20]))
        else:
            lines.append("\n### 可用引用 ID\n- 无")

        return "\n".join(lines)

    def _parse_intro_item(self, data: dict) -> IntroItem:
        citations = []
        if isinstance(data, dict):
            citations = self._dedupe_ids(list(data.get("citations", [])) + self.extract_citation_ids(data))
        return IntroItem(
            title=data.get("title", "") if isinstance(data, dict) else "",
            summary=data.get("summary", "") if isinstance(data, dict) else "",
            citations=citations,
        )

    def _parse_target_product_intro(self, result: dict) -> TargetProductIntro | None:
        data = result.get("target_product_intro", {})
        if not isinstance(data, dict):
            return None

        def parse_items(key: str) -> list[IntroItem]:
            items = []
            for item in data.get(key, []):
                if not isinstance(item, dict):
                    continue
                parsed = self._parse_intro_item(item)
                if parsed.title or parsed.summary or parsed.citations:
                    items.append(parsed)
            return items

        channel = data.get("channel")
        channel_item = self._parse_intro_item(channel) if isinstance(channel, dict) else None
        if channel_item and not any([channel_item.title, channel_item.summary, channel_item.citations]):
            channel_item = None
        intro = TargetProductIntro(
            hero_summary=data.get("hero_summary", ""),
            core_capabilities=parse_items("core_capabilities"),
            monetization=parse_items("monetization"),
            market_user=parse_items("market_user"),
            strengths=parse_items("strengths"),
            weaknesses=parse_items("weaknesses"),
            channel=channel_item,
        )

        if not any([
            intro.hero_summary,
            intro.core_capabilities,
            intro.monetization,
            intro.market_user,
            intro.strengths,
            intro.weaknesses,
            intro.channel,
        ]):
            return None
        return intro

    def _parse_strategy_report(self, product_name: str, competitor_count: int,
                                result: dict) -> StrategyReport:
        """解析LLM返回的策略报告，提取引用 ID"""
        action_plan = []
        for ap in result.get("action_plan", []):
            ap_cites = self.extract_citation_ids(ap)
            action_plan.append(ActionItem(
                priority=ap.get("priority", "P2"),
                action=ap.get("action", ""),
                timeline=ap.get("timeline", ""),
                expected_impact=ap.get("expected_impact", ""),
                citations=ap_cites,
            ))

        report = StrategyReport(
            product_name=product_name,
            competitor_count=competitor_count,
            overall_positioning=result.get("overall_positioning", ""),
            differentiation_strategy=result.get("differentiation_strategy", {}),
            action_plan=action_plan,
            risk_assessment=result.get("risk_assessment", ""),
            product_analysis_summary=result.get("product_analysis_summary", ""),
            pricing_analysis_summary=result.get("pricing_analysis_summary", ""),
            market_analysis_summary=result.get("market_analysis_summary", ""),
            summary=result.get("summary", ""),
        )
        report.target_product_intro = self._parse_target_product_intro(result)
        report.swot = self._parse_swot(result.get("swot"))
        return report

    def _parse_swot(self, data: dict | None) -> SWOTAnalysis | None:
        """解析 SWOT 分析数据"""
        if not data or not isinstance(data, dict):
            return None

        def parse_quadrant(q_data: dict | None) -> SWOTQuadrant:
            if not q_data or not isinstance(q_data, dict):
                return SWOTQuadrant()
            return SWOTQuadrant(
                items=q_data.get("items", []),
                citations=q_data.get("citations", []),
            )

        cross = data.get("cross_strategies", {})
        if not isinstance(cross, dict):
            cross = {}

        return SWOTAnalysis(
            strengths=parse_quadrant(data.get("strengths")),
            weaknesses=parse_quadrant(data.get("weaknesses")),
            opportunities=parse_quadrant(data.get("opportunities")),
            threats=parse_quadrant(data.get("threats")),
            cross_strategies=SWOTCrossStrategy(
                so=cross.get("so", []),
                wo=cross.get("wo", []),
                st=cross.get("st", []),
                wt=cross.get("wt", []),
            ),
        )

    def _rule_strategy(self, product_name: str, competitor_count: int,
                        product_analysis: ProductAnalysis,
                        pricing_analysis: PricingAnalysis,
                        market_analysis: MarketAnalysis,
                        citation_index: CitationIndex | None = None,
                        target_product_data: CompetitorData | None = None) -> StrategyReport:
        """规则引擎策略建议（SWOT模板）"""
        # 从三维分析中提取关键词
        diff_points = product_analysis.differentiation_points[:3] if product_analysis.differentiation_points else []
        diff_text = "、".join(diff_points) if diff_points else "需进一步分析"

        # 基于三维分析数据生成基础 SWOT
        swot = SWOTAnalysis(
            strengths=SWOTQuadrant(items=diff_points if diff_points else ["需进一步分析产品优势"]),
            weaknesses=SWOTQuadrant(items=["需启用LLM获取深度劣势分析"]),
            opportunities=SWOTQuadrant(items=["需启用LLM获取市场机会分析"]),
            threats=SWOTQuadrant(items=["需启用LLM获取威胁分析"]),
            cross_strategies=SWOTCrossStrategy(
                so=[f"利用{diff_text}优势抓住市场机会"],
                wo=["启用LLM以识别弥补劣势的机会"],
                st=["启用LLM以制定应对威胁的策略"],
                wt=["启用LLM以制定规避风险的策略"],
            ),
        )

        return StrategyReport(
            product_name=product_name,
            competitor_count=competitor_count,
            target_product_data=target_product_data,
            overall_positioning=f"{product_name}应基于{diff_text}等差异化优势进行市场定位",
            differentiation_strategy={
                "core_differentiator": diff_text,
                "supporting_points": diff_points,
            },
            swot=swot,
            action_plan=[
                ActionItem(priority="P0", action="深入调研竞品最新动态", timeline="1-2周",
                           expected_impact="建立竞品情报基线"),
                ActionItem(priority="P1", action="强化差异化功能投入", timeline="1-3月",
                           expected_impact="巩固竞争优势"),
                ActionItem(priority="P2", action="制定针对性市场策略", timeline="3-6月",
                           expected_impact="提升市场份额"),
            ],
            risk_assessment="(规则引擎分析，详情请启用LLM)",
            product_analysis_summary=product_analysis.summary[:100],
            pricing_analysis_summary=pricing_analysis.summary[:100],
            market_analysis_summary=market_analysis.summary[:100],
            summary="基于SWOT模板的简单策略建议（建议启用LLM获得深度分析）",
            citation_index=citation_index or CitationIndex(),
        )

    def format_report(self, report: StrategyReport) -> str:
        """格式化策略报告为可读文本"""
        lines = [
            "═" * 65,
            f"  智能竞品分析报告 — {report.product_name}",
            "═" * 65,
            "",
            f"📋 分析竞品数量: {report.competitor_count}",
            "",
        ]

        if report.target_product_data:
            target = report.target_product_data
            lines.extend([
                "─── 目标产品介绍 ───",
                f"  名称: {target.name or report.product_name}",
            ])
            if target.product_features:
                feature_text = "；".join(
                    f"{fi.name}: {fi.description}" if fi.description else fi.name
                    for fi in target.product_features[:3]
                )
                lines.append(f"  核心功能: {feature_text}")
            if target.pricing_tiers:
                pricing_text = "；".join(
                    f"{pt.tier_name}: {pt.price}" if pt.price else pt.tier_name
                    for pt in target.pricing_tiers[:3]
                )
                lines.append(f"  定价概览: {pricing_text}")
            if target.market_share:
                lines.append(f"  市场信息: {target.market_share}")
            if target.user_reviews:
                lines.append(f"  用户评价: {target.user_reviews}")
            if target.strengths:
                lines.append(f"  优势: {target.strengths}")
            if target.weaknesses:
                lines.append(f"  劣势: {target.weaknesses}")
            if target.channels:
                lines.append(f"  渠道: {target.channels}")
            lines.append("")

        lines.extend([
            "─── 整体定位 ───",
            report.overall_positioning or "暂无",
            "",
            "─── 差异化策略 ───",
        ])

        if report.differentiation_strategy:
            core = report.differentiation_strategy.get("core_differentiator", "")
            points = report.differentiation_strategy.get("supporting_points", [])
            lines.append(f"  核心差异: {core}")
            if points:
                lines.append(f"  支撑点: {', '.join(points)}")

        # SWOT 分析
        if report.swot:
            lines.append("")
            lines.append("─── SWOT 分析 ───")
            swot = report.swot
            if swot.strengths.items:
                lines.append("  💪 优势 (Strengths):")
                for item in swot.strengths.items:
                    lines.append(f"    + {item}")
            if swot.weaknesses.items:
                lines.append("  ⚠️ 劣势 (Weaknesses):")
                for item in swot.weaknesses.items:
                    lines.append(f"    - {item}")
            if swot.opportunities.items:
                lines.append("  🌟 机会 (Opportunities):")
                for item in swot.opportunities.items:
                    lines.append(f"    ○ {item}")
            if swot.threats.items:
                lines.append("  🔴 威胁 (Threats):")
                for item in swot.threats.items:
                    lines.append(f"    × {item}")
            if swot.cross_strategies:
                cs = swot.cross_strategies
                if cs.so or cs.wo or cs.st or cs.wt:
                    lines.append("")
                    lines.append("  交叉矩阵策略:")
                    if cs.so:
                        lines.append("    SO（进攻）: " + "; ".join(cs.so))
                    if cs.wo:
                        lines.append("    WO（改进）: " + "; ".join(cs.wo))
                    if cs.st:
                        lines.append("    ST（防御）: " + "; ".join(cs.st))
                    if cs.wt:
                        lines.append("    WT（规避）: " + "; ".join(cs.wt))

        lines.append("")
        lines.append("─── 行动方案 ───")
        for ap in report.action_plan:
            priority_emoji = {"P0": "🔴", "P1": "🟡", "P2": "🟢", "P3": "⚪"}.get(ap.priority, "⚪")
            lines.append(f"  {priority_emoji} [{ap.priority}] {ap.action}")
            if ap.timeline:
                lines.append(f"     ⏰ 时间: {ap.timeline}")
            if ap.expected_impact:
                lines.append(f"     🎯 预期: {ap.expected_impact}")

        lines.append("")
        lines.append("─── 风险评估 ───")
        lines.append(report.risk_assessment or "暂无")

        lines.append("")
        lines.append("─── 分析摘要 ───")
        if report.product_analysis_summary:
            lines.append(f"  🔧 产品: {report.product_analysis_summary}")
        if report.pricing_analysis_summary:
            lines.append(f"  💰 定价: {report.pricing_analysis_summary}")
        if report.market_analysis_summary:
            lines.append(f"  📈 市场: {report.market_analysis_summary}")

        lines.append("")
        lines.append("─── 综合建议 ───")
        lines.append(report.summary or "暂无")
        lines.append("")
        lines.append("═" * 65)

        return "\n".join(lines)

    def format_html_report(self, report: StrategyReport,
                           product_analysis: 'ProductAnalysis' = None,
                           pricing_analysis: 'PricingAnalysis' = None,
                           market_analysis: 'MarketAnalysis' = None,
                           competitor_list: 'CompetitorList' = None,
                           competitors_data: dict = None,
                           timings: dict = None) -> str:
        """
        格式化策略报告为精美的HTML页面

        重点呈现：
          1. 逐竞品对比表格（我方 vs 每个竞品的多维度对比）
          2. 每个竞品的优劣势分析（独立卡片）
          3. 本产品的差异化定位

        Args:
            report: 策略建议报告
            product_analysis: 产品分析结果
            pricing_analysis: 定价分析结果
            market_analysis: 市场分析结果
            competitor_list: 竞品列表
            competitors_data: 竞品采集数据
            timings: 各阶段耗时

        Returns:
            HTML字符串
        """
        import html as html_mod
        import re
        from datetime import datetime
        from models.domain import CompetitorData, FeatureComparison, CompetitiveAdvantage, PricingItem, MarketShareItem

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # ── 辅助函数 ──
        def esc(text: str) -> str:
            return html_mod.escape(str(text)) if text else ""

        def priority_badge(priority: str) -> str:
            colors = {"P0": "#ef4444", "P1": "#f59e0b", "P2": "#22c55e", "P3": "#94a3b8"}
            bg = colors.get(priority, "#94a3b8")
            return f'<span style="background:{bg};color:#fff;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;">{esc(priority)}</span>'

        def feature_icon(val: str) -> str:
            v = val.strip()
            if not v:
                return '<span style="color:#94a3b8;">—</span>'
            if v in ("✅", "✓", "有", "支持"):
                return '<span style="color:#22c55e;font-size:18px;">✅</span>'
            elif v in ("❌", "✗", "无", "不支持"):
                return '<span style="color:#ef4444;font-size:18px;">❌</span>'
            elif v in ("🔶", "△", "部分", "部分支持"):
                return '<span style="color:#f59e0b;font-size:18px;">🔶</span>'
            elif v in ("⚪", "数据不足"):
                return '<span style="color:#94a3b8;font-size:18px;">⚪</span>'
            else:
                return f'<span style="color:#64748b;">{esc(v)}</span>'

        def find_value(values_dict: dict, target_name: str, product_name: str) -> str:
            """
            从 feature_matrix.values 中查找目标名对应的值。
            支持多种键名格式：
              - 精确匹配: "飞书"
              - 带后缀匹配: "飞书(我方产品)"
              - 模糊前缀匹配: "飞书" 匹配 "飞书文档"
            """
            if not values_dict:
                return ""
            # 1. 精确匹配
            if target_name in values_dict:
                return values_dict[target_name]
            # 2. 带后缀匹配（LLM可能返回 "飞书(我方产品)" 格式）
            for key in values_dict:
                if key.startswith(target_name) and target_name in key:
                    return values_dict[key]
            # 3. 如果查找的是我方产品，尝试包含 product_name 的键
            if target_name == product_name:
                for key in values_dict:
                    if product_name in key:
                        return values_dict[key]
            # 4. 反向：target_name 可能是键的子串
            for key in values_dict:
                if target_name in key or key in target_name:
                    return values_dict[key]
            return ""

        def find_adv(adv_map_dict: dict, comp_name: str) -> 'CompetitiveAdvantage | None':
            """模糊匹配竞品名查找竞争优势"""
            if comp_name in adv_map_dict:
                return adv_map_dict[comp_name]
            for key, val in adv_map_dict.items():
                if comp_name in key or key in comp_name:
                    return val
            return None

        def find_price(price_map_dict: dict, comp_name: str) -> 'PricingItem | None':
            """模糊匹配竞品名查找定价"""
            if comp_name in price_map_dict:
                return price_map_dict[comp_name]
            for key, val in price_map_dict.items():
                if comp_name in key or key in comp_name:
                    return val
            return None

        def find_share(share_map_dict: dict, comp_name: str) -> 'MarketShareItem | None':
            """模糊匹配竞品名查找市场份额"""
            if comp_name in share_map_dict:
                return share_map_dict[comp_name]
            for key, val in share_map_dict.items():
                if comp_name in key or key in comp_name:
                    return val
            return None

        def cite_sup(citation_ids: list[str], competitor: str | None = None) -> str:
            """渲染引用上标，如 [1][2]，可点击跳转到来源附录。
            competitor 不为 None 时，只显示该竞品相关的引用（按 citation ID 前缀过滤）。
            """
            if not citation_ids or not global_cite_num:
                return ""
            parts = []
            for cid in citation_ids:
                if competitor and not cid.startswith(competitor + ":"):
                    continue
                num = global_cite_num.get(cid)
                if num:
                    cite = report.citation_index.get(cid)
                    if cite:
                        used_cite_ids.add(cid)
                        parts.append(
                            f'<sup><a href="#cite-{cid}" title="{esc(cite.title)} - {esc(cite.url)}" '
                            f'style="color:#3b82f6;text-decoration:none;font-size:11px;">[{num}]</a></sup>'
                        )
            return " ".join(parts)

        def strip_source_text(text: str) -> str:
            """移除 LLM 生成的 plain-text 信息来源（如 '信息来源：新浪科技2026-05-26'）"""
            return re.sub(r'[。；;]?\s*信息来源[：:].*$', '', text).rstrip()

        def find_cdata(cdata_map_dict: dict, comp_name: str) -> 'CompetitorData | None':
            """模糊匹配竞品名查找采集数据"""
            if comp_name in cdata_map_dict:
                return cdata_map_dict[comp_name]
            for key, val in cdata_map_dict.items():
                if comp_name in key or key in comp_name:
                    return val
            return None

        def normalize_trend(trend: str) -> str:
            """标准化趋势描述为枚举值：上升/稳定/下降"""
            t = trend.strip()
            if any(k in t for k in ["上升", "增长", "上涨", "↗", "↑", "高速", "快速增长", "大幅增长"]):
                return "上升"
            elif any(k in t for k in ["下降", "下滑", "下跌", "↘", "↓", "小幅下降", "大幅下降"]):
                return "下降"
            else:
                return "稳定"

        def trend_icon(trend: str) -> str:
            normalized = normalize_trend(trend)
            if normalized == "上升":
                return f'<span style="color:#22c55e;">↗ {esc(normalized)}</span>'
            elif normalized == "下降":
                return f'<span style="color:#ef4444;">↘ {esc(normalized)}</span>'
            else:
                return f'<span style="color:#64748b;">→ {esc(normalized)}</span>'

        def render_intro_items(items: list[IntroItem], empty_text: str = "暂无公开信息") -> str:
            if not items:
                return f'<div style="font-size:13px;color:#64748b;line-height:1.7;">{esc(empty_text)}</div>'
            html = ""
            for item in items:
                title_html = f'<div style="font-size:13px;font-weight:700;color:#0f172a;">{esc(item.title)}{cite_sup(item.citations)}</div>' if item.title else ""
                html += f'''
                        <div style="padding:10px 0;border-bottom:1px solid #e2e8f0;">
                            {title_html}
                            <div style="font-size:12px;color:#64748b;line-height:1.55;margin-top:{'4px' if title_html else '0'};">{esc(item.summary)}</div>
                        </div>'''
            return html

        def render_target_product_intro_from_llm(intro: TargetProductIntro | None,
                                                 data: CompetitorData | None) -> str:
            """优先渲染 LLM 生成的目标产品介绍。"""
            if not intro:
                return ""

            name = (data.name if data else "") or report.product_name
            hero_cites = []
            if intro.core_capabilities:
                hero_cites.extend(intro.core_capabilities[0].citations)
            if intro.strengths:
                hero_cites.extend(intro.strengths[0].citations)
            hero_cites = list(dict.fromkeys(hero_cites))[:2]
            intro_source_ids = []
            for item in (
                intro.core_capabilities + intro.monetization + intro.market_user +
                intro.strengths + intro.weaknesses
            ):
                intro_source_ids.extend(item.citations)
            if intro.channel:
                intro_source_ids.extend(intro.channel.citations)
            intro_source_count = len(set(intro_source_ids))

            channel_html = ""
            if intro.channel and (intro.channel.title or intro.channel.summary):
                title = intro.channel.title or "渠道"
                channel_html = f'''
                    <div style="flex:1;min-width:220px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:12px 14px;">
                        <div style="font-size:12px;font-weight:800;color:#1d4ed8;margin-bottom:5px;">{esc(title)}{cite_sup(intro.channel.citations)}</div>
                        <div style="font-size:12px;color:#1e40af;line-height:1.6;">{esc(intro.channel.summary)}</div>
                    </div>'''

            return f'''
            <div style="background:#fff;border-radius:18px;padding:28px;margin-bottom:24px;box-shadow:0 12px 32px rgba(15,23,42,0.07);border:1px solid #e2e8f0;">
                <div style="display:flex;justify-content:space-between;gap:20px;align-items:flex-start;flex-wrap:wrap;margin-bottom:20px;">
                    <div style="max-width:720px;">
                        <div style="font-size:12px;font-weight:700;color:#2563eb;letter-spacing:.08em;margin-bottom:8px;">TARGET PRODUCT</div>
                        <h2 style="font-size:24px;color:#0f172a;margin:0 0 10px 0;">{esc(name)}{cite_sup(hero_cites)}</h2>
                        <div style="font-size:14px;color:#475569;line-height:1.75;">{esc(intro.hero_summary)}</div>
                    </div>
                    <div style="background:linear-gradient(135deg,#0f172a,#1d4ed8);color:#fff;border-radius:14px;padding:14px 18px;min-width:180px;">
                        <div style="font-size:12px;opacity:.72;margin-bottom:6px;">介绍依据</div>
                        <div style="font-size:18px;font-weight:800;">{intro_source_count}</div>
                        <div style="font-size:12px;opacity:.78;">条公开来源可追溯</div>
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-bottom:16px;">
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:16px;">
                        <div style="font-size:12px;font-weight:800;color:#64748b;margin-bottom:8px;">核心能力</div>
                        {render_intro_items(intro.core_capabilities, "暂无核心能力摘要")}
                    </div>
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:16px;">
                        <div style="font-size:12px;font-weight:800;color:#64748b;margin-bottom:8px;">定价 / 商业化</div>
                        {render_intro_items(intro.monetization, "暂无定价/商业化摘要")}
                    </div>
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:16px;">
                        <div style="font-size:12px;font-weight:800;color:#64748b;margin-bottom:8px;">市场 / 用户</div>
                        {render_intro_items(intro.market_user, "暂无市场/用户摘要")}
                    </div>
                </div>

                <div style="display:flex;gap:10px;flex-wrap:wrap;">
                    <div style="flex:1;min-width:220px;background:#ecfdf5;border:1px solid #bbf7d0;border-radius:12px;padding:12px 14px;">
                        <div style="font-size:12px;font-weight:800;color:#15803d;margin-bottom:5px;">优势</div>
                        {render_intro_items(intro.strengths, "暂无优势摘要")}
                    </div>
                    <div style="flex:1;min-width:220px;background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:12px 14px;">
                        <div style="font-size:12px;font-weight:800;color:#c2410c;margin-bottom:5px;">短板</div>
                        {render_intro_items(intro.weaknesses, "暂无短板摘要")}
                    </div>
                    {channel_html or '<div style="flex:1;min-width:220px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:12px 14px;"><div style="font-size:12px;font-weight:800;color:#1d4ed8;margin-bottom:5px;">渠道</div><div style="font-size:12px;color:#1e40af;line-height:1.6;">暂无渠道摘要</div></div>'}
                </div>
            </div>'''

        def render_target_product_intro(data: CompetitorData | None) -> str:
            """渲染目标产品介绍板块（回退逻辑：使用原始采集数据）"""
            if not data:
                return ""

            feature_cards = ""
            for fi in data.product_features[:4]:
                feature_cards += f'''
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;flex:1;min-width:220px;">
                    <div style="font-size:13px;font-weight:600;color:#1e293b;margin-bottom:6px;">{esc(fi.name) if fi.name else '核心能力'}{cite_sup(fi.citations, competitor=report.product_name)}</div>
                    <div style="font-size:12px;color:#64748b;line-height:1.6;">{esc(fi.description) if fi.description else '暂无描述'}</div>
                </div>'''

            pricing_items = ""
            for pt in data.pricing_tiers[:3]:
                feature_text = "；".join(pt.features[:2]) if pt.features else ""
                pricing_items += f'''
                <div style="padding:10px 0;border-bottom:1px solid #f1f5f9;">
                    <div style="font-size:13px;font-weight:600;color:#1e293b;">{esc(pt.tier_name) if pt.tier_name else '定价档位'}{cite_sup(pt.citations, competitor=report.product_name)}</div>
                    <div style="font-size:12px;color:#475569;line-height:1.6;">{esc(pt.price) if pt.price else '暂无价格信息'}</div>
                    {f'<div style="font-size:12px;color:#64748b;line-height:1.6;margin-top:4px;">{esc(feature_text)}</div>' if feature_text else ''}
                </div>'''

            market_intro = data.market_share or "暂无公开市场信息"
            market_intro += cite_sup([c.id for c in data.citations], competitor=report.product_name)
            reviews_html = f'<div style="font-size:13px;color:#64748b;line-height:1.7;margin-top:8px;">{esc(data.user_reviews)}</div>' if data.user_reviews else ""

            return f'''
            <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <h2 style="font-size:20px;color:#1e293b;margin:0 0 16px 0;">🚀 目标产品介绍</h2>
                <div style="background:linear-gradient(135deg,#0f172a,#334155);border-radius:12px;padding:20px;color:#fff;margin-bottom:18px;">
                    <div style="font-size:12px;opacity:0.75;margin-bottom:6px;">目标产品</div>
                    <div style="font-size:22px;font-weight:700;margin-bottom:8px;">{esc(data.name or report.product_name)}</div>
                    <div style="font-size:14px;line-height:1.7;opacity:0.92;">{esc(data.strengths) if data.strengths else '基于公开资料整理目标产品的核心能力、定价、市场和渠道信息。'}</div>
                </div>
                {f"<div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px;'>{feature_cards}</div>" if feature_cards else ''}
                {f"<div style='background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:18px;'><div style='font-size:13px;font-weight:600;color:#1e293b;margin-bottom:8px;'>💰 定价概览</div>{pricing_items}</div>" if pricing_items else ''}
                <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:18px;">
                    <div style="flex:1;min-width:260px;background:#f8fafc;border-radius:12px;padding:16px;">
                        <div style="font-size:13px;font-weight:600;color:#1e293b;margin-bottom:8px;">📈 市场与用户反馈</div>
                        <div style="font-size:13px;color:#475569;line-height:1.7;">{market_intro}</div>
                        {reviews_html}
                    </div>
                    <div style="flex:1;min-width:260px;background:#f8fafc;border-radius:12px;padding:16px;">
                        <div style="font-size:13px;font-weight:600;color:#1e293b;margin-bottom:8px;">🛣️ 渠道</div>
                        <div style="font-size:13px;color:#475569;line-height:1.7;">{esc(data.channels) if data.channels else '暂无公开渠道信息'}</div>
                    </div>
                </div>
                <div style="display:flex;gap:16px;flex-wrap:wrap;">
                    <div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:14px 16px;border-radius:0 8px 8px 0;flex:1;min-width:240px;">
                        <div style="font-size:12px;font-weight:600;color:#16a34a;margin-bottom:6px;">💪 优势</div>
                        <div style="font-size:13px;color:#15803d;line-height:1.6;">{esc(data.strengths) if data.strengths else '暂无'}</div>
                    </div>
                    <div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:14px 16px;border-radius:0 8px 8px 0;flex:1;min-width:240px;">
                        <div style="font-size:12px;font-weight:600;color:#d97706;margin-bottom:6px;">🎯 劣势</div>
                        <div style="font-size:13px;color:#b45309;line-height:1.6;">{esc(data.weaknesses) if data.weaknesses else '暂无'}</div>
                    </div>
                </div>
            </div>'''

        # 构建全局引用编号映射（cid → 1-based 序号）
        global_cite_num: dict[str, int] = {}
        if report.citation_index and report.citation_index.citations:
            for idx, cid in enumerate(report.citation_index.citations.keys(), 1):
                global_cite_num[cid] = idx

        # 跟踪正文中实际引用的来源 ID（用于附录过滤）
        used_cite_ids: set[str] = set()

        # 收集所有竞品名（我方产品排首位）
        all_names = []
        if competitor_list and competitor_list.competitors:
            all_names = [c.name for c in competitor_list.competitors]
        elif product_analysis and product_analysis.feature_matrix:
            seen = set()
            for fm in product_analysis.feature_matrix:
                for name in fm.values:
                    if name not in seen:
                        seen.add(name)
                        all_names.append(name)
        if report.product_name in all_names:
            all_names.remove(report.product_name)
        all_names.insert(0, report.product_name)

        # 构建 竞品名→CompetitorData 映射
        cdata_map: dict[str, CompetitorData] = {}
        if competitors_data:
            for k, v in competitors_data.items():
                cdata_map[k] = v

        # 构建 竞品名→CompetitiveAdvantage 映射
        adv_map: dict[str, CompetitiveAdvantage] = {}
        if product_analysis and product_analysis.competitive_advantages:
            for adv in product_analysis.competitive_advantages:
                adv_map[adv.competitor] = adv

        # 构建 竞品名→PricingItem 映射
        price_map: dict[str, PricingItem] = {}
        if pricing_analysis and pricing_analysis.pricing_comparison:
            for pc in pricing_analysis.pricing_comparison:
                price_map[pc.competitor] = pc

        # 构建 竞品名→MarketShareItem 映射
        share_map: dict[str, MarketShareItem] = {}
        if market_analysis and market_analysis.market_share_data:
            for ms in market_analysis.market_share_data:
                share_map[ms.competitor] = ms

        # ══════════════════════════════════════════════
        # 区块1：竞品发现概览
        # ══════════════════════════════════════════════
        competitor_cards = ""
        if competitor_list and competitor_list.competitors:
            for c in competitor_list.competitors:
                rel_colors = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b", "LOW": "#94a3b8"}
                rel_labels = {"HIGH": "直接竞品", "MEDIUM": "间接竞品", "LOW": "潜在竞品"}
                bg = rel_colors.get(c.relevance, "#94a3b8")
                label = rel_labels.get(c.relevance, c.relevance)
                competitor_cards += f'''
                <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;flex:1;min-width:200px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <strong style="font-size:16px;">{esc(c.name)}</strong>
                        <span style="background:{bg};color:#fff;padding:2px 10px;border-radius:12px;font-size:11px;">{esc(label)}</span>
                    </div>
                    <p style="color:#64748b;font-size:13px;margin:0;line-height:1.6;">{esc(c.brief)}</p>
                </div>'''

        # ══════════════════════════════════════════════
        # 区块2：逐竞品对比表格（我方 vs 每个竞品）
        # ══════════════════════════════════════════════
        competitor_comparison_cards = ""
        competitor_names = [n for n in all_names if n != report.product_name]

        for comp_name in competitor_names:
            cd = find_cdata(cdata_map, comp_name)
            adv = find_adv(adv_map, comp_name)
            pi = find_price(price_map, comp_name)
            ms = find_share(share_map, comp_name)

            # ── 对比表格行 ──
            comparison_rows = ""

            # 功能对比：逐维度对比
            if product_analysis and product_analysis.feature_matrix:
                for fm in product_analysis.feature_matrix:
                    ov = find_value(fm.values, report.product_name, report.product_name)
                    tv = find_value(fm.values, comp_name, report.product_name)
                    comparison_rows += f'''
                    <tr style="border-bottom:1px solid #f1f5f9;">
                        <td style="padding:8px 14px;font-size:13px;color:#64748b;width:100px;">{esc(fm.feature)}{cite_sup(fm.citations, competitor=comp_name)}</td>
                        <td style="padding:8px 14px;text-align:center;">{feature_icon(ov)}</td>
                        <td style="padding:8px 14px;text-align:center;">{feature_icon(tv)}</td>
                    </tr>'''

            # 定价行（从 target_product_data 提取我方数据）
            no_data_label = '<span style="color:#94a3b8;font-size:12px;">暂无公开信息</span>'
            our_free = ""
            our_paid = ""
            our_model = ""
            if report.target_product_data and report.target_product_data.pricing_tiers:
                tiers = report.target_product_data.pricing_tiers
                # 从所有定价层级中提取信息
                free_keywords = ["免费", "免费版", "基础", "0元", "零元", "无年费"]
                for t in tiers:
                    tn = t.tier_name or ""
                    tp = t.price or ""
                    combined = tn + tp
                    if any(k in combined for k in free_keywords) and not our_free:
                        our_free = tp or tn
                    elif tp and not our_paid:
                        our_paid = tp
                # 如果没有明确的免费/付费区分，用第一个tier的价格作为付费信息
                if not our_paid and tiers:
                    for t in tiers:
                        if t.price:
                            our_paid = t.price
                            break
                our_model = "；".join(t.tier_name for t in tiers[:4] if t.tier_name) if tiers else ""

            if pi:
                comparison_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">免费版</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(our_free) if our_free else no_data_label}</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(pi.free_tier) if pi.free_tier else no_data_label}</td>
                </tr>
                <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">付费版</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(our_paid) if our_paid else no_data_label}</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(pi.paid_tier) if pi.paid_tier else no_data_label}</td>
                </tr>
                <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">定价模式</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(our_model) if our_model else no_data_label}</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(pi.pricing_model) if pi.pricing_model else no_data_label}</td>
                </tr>'''
            else:
                comparison_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">定价信息</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;" colspan="2">{no_data_label}</td>
                </tr>'''

            # 市场份额行（从 target_product_data 提取我方数据）
            our_share = ""
            our_trend = ""
            if report.target_product_data and report.target_product_data.market_share:
                our_share = report.target_product_data.market_share[:150]
                our_trend = "上升"

            if ms:
                share_display = esc(ms.share_estimate) if ms.share_estimate else no_data_label
                comparison_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">市场份额</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(our_share) if our_share else no_data_label}</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{share_display}</td>
                </tr>
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">趋势</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{trend_icon(our_trend) if our_trend else no_data_label}</td>
                    <td style="padding:8px 14px;text-align:center;">{trend_icon(ms.trend)}</td>
                </tr>'''
            else:
                comparison_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">市场份额</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;" colspan="2">{no_data_label}</td>
                </tr>'''

            # ── 优劣势分析（仅使用 ProductAgent 的对比分析结果） ──
            our_adv_text = ""
            their_adv_text = ""

            if adv:
                our_adv_text = strip_source_text(adv.our_advantage)
                their_adv_text = strip_source_text(adv.their_advantage)

            # 优劣势区块
            swot_section = ""
            swot_parts = []

            if our_adv_text:
                swot_parts.append(f'''
                <div style="flex:1;min-width:200px;">
                    <div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:8px;">
                        <div style="font-size:12px;font-weight:600;color:#16a34a;margin-bottom:4px;">🛡️ 我方优势</div>
                        <div style="font-size:13px;color:#15803d;line-height:1.6;">{esc(our_adv_text)}</div>
                    </div>
                </div>''')
            if their_adv_text:
                swot_parts.append(f'''
                <div style="flex:1;min-width:200px;">
                    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:8px;">
                        <div style="font-size:12px;font-weight:600;color:#dc2626;margin-bottom:4px;">⚠️ 对方优势</div>
                        <div style="font-size:13px;color:#b91c1c;line-height:1.6;">{esc(their_adv_text)}</div>
                    </div>
                </div>''')

            swot_section = f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:16px;">{"".join(swot_parts)}</div>'

            # 组装单竞品卡片
            competitor_comparison_cards += f'''
            <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                    <h3 style="margin:0;font-size:18px;color:#1e293b;">⚔️ {esc(report.product_name)} vs {esc(comp_name)}</h3>
                    <span style="background:#dbeafe;color:#1d4ed8;padding:4px 12px;border-radius:8px;font-size:12px;font-weight:500;">对比分析</span>
                </div>
                <div style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;">
                        <thead>
                            <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;">
                                <th style="padding:10px 14px;text-align:left;font-size:13px;width:100px;">维度</th>
                                <th style="padding:10px 14px;text-align:center;font-size:13px;color:#1e40af;font-weight:600;">{esc(report.product_name)}</th>
                                <th style="padding:10px 14px;text-align:center;font-size:13px;color:#991b1b;font-weight:600;">{esc(comp_name)}</th>
                            </tr>
                        </thead>
                        <tbody>{comparison_rows}</tbody>
                    </table>
                </div>
                {swot_section}
            </div>'''

        # ══════════════════════════════════════════════
        # 区块3：功能对比矩阵（总览）
        # ══════════════════════════════════════════════
        feature_matrix_html = ""
        if product_analysis and product_analysis.feature_matrix:
            header_cells = "".join(f'<th style="padding:12px 16px;text-align:center;white-space:nowrap;font-size:13px;">{esc(n)}</th>' for n in all_names)
            rows = ""
            for fm in product_analysis.feature_matrix:
                cells = f'<td style="padding:10px 16px;font-weight:500;font-size:13px;border-right:1px solid #e2e8f0;">{esc(fm.feature)}{cite_sup(fm.citations)}</td>'
                for name in all_names:
                    val = find_value(fm.values, name, report.product_name)
                    cells += f'<td style="padding:10px 16px;text-align:center;">{feature_icon(val)}</td>'
                rows += f'<tr style="border-bottom:1px solid #f1f5f9;">{cells}</tr>'

            feature_matrix_html = f'''
            <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <h2 style="margin:0 0 20px 0;font-size:20px;color:#1e293b;">🔧 功能对比矩阵（总览）</h2>
                <div style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;">
                        <thead>
                            <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;">
                                <th style="padding:12px 16px;text-align:left;font-size:13px;border-right:1px solid #e2e8f0;">功能</th>
                                {header_cells}
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
                <div style="margin-top:12px;display:flex;gap:16px;font-size:12px;color:#94a3b8;">
                    <span>✅ 支持</span><span>🔶 部分支持</span><span>⚪ 数据不足</span><span>❌ 不支持</span>
                </div>
            </div>'''

        # ══════════════════════════════════════════════
        # 区块4：定价策略对比
        # ══════════════════════════════════════════════
        pricing_html = ""
        if pricing_analysis and pricing_analysis.pricing_comparison:
            price_rows = ""
            no_data_cell = '<span style="color:#94a3b8;font-size:12px;">暂无公开信息</span>'
            # 先插入我方产品定价行
            if report.target_product_data and report.target_product_data.pricing_tiers:
                tpd = report.target_product_data
                our_free = ""
                our_paid = ""
                our_model = ""
                free_keywords = ["免费", "免费版", "基础", "0元", "零元", "无年费"]
                for t in tpd.pricing_tiers:
                    combined = (t.tier_name or "") + (t.price or "")
                    if any(k in combined for k in free_keywords) and not our_free:
                        our_free = t.price or t.tier_name
                    elif t.price and not our_paid:
                        our_paid = f"{t.tier_name}: {t.price}" if t.tier_name else t.price
                if not our_paid:
                    for t in tpd.pricing_tiers:
                        if t.price:
                            our_paid = f"{t.tier_name}: {t.price}" if t.tier_name else t.price
                            break
                our_model = "；".join(t.tier_name for t in tpd.pricing_tiers[:4] if t.tier_name)
                price_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;background:#f0fdf4;">
                    <td style="padding:10px 16px;font-weight:600;font-size:13px;color:#166534;">⭐ {esc(report.product_name)}（我方）</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(our_free) if our_free else no_data_cell}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(our_paid.rstrip("；")) if our_paid else no_data_cell}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(our_model) if our_model else no_data_cell}</td>
                </tr>'''
            for pc in pricing_analysis.pricing_comparison:
                price_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:10px 16px;font-weight:500;font-size:13px;">{esc(pc.competitor)}{cite_sup(pc.citations)}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(pc.free_tier) if pc.free_tier else no_data_cell}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(pc.paid_tier) if pc.paid_tier else no_data_cell}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(pc.pricing_model) if pc.pricing_model else no_data_cell}</td>
                </tr>'''

            ranking_html = ""
            if pricing_analysis.value_ranking:
                rank_items = ""
                for i, name in enumerate(pricing_analysis.value_ranking, 1):
                    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
                    rank_items += f'<span style="margin-right:12px;font-size:14px;">{medal} {esc(name)}</span>'
                ranking_html = f'''
                <div style="margin-top:16px;padding:12px 16px;background:#f0fdf4;border-radius:8px;font-size:14px;">
                    <strong>性价比排名：</strong>{rank_items}
                </div>'''

            pricing_html = f'''
            <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <h2 style="margin:0 0 20px 0;font-size:20px;color:#1e293b;">💰 定价策略对比</h2>
                <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;">
                    <thead>
                        <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;">
                            <th style="padding:12px 16px;text-align:left;font-size:13px;">竞品</th>
                            <th style="padding:12px 16px;text-align:left;font-size:13px;">免费版</th>
                            <th style="padding:12px 16px;text-align:left;font-size:13px;">付费版</th>
                            <th style="padding:12px 16px;text-align:left;font-size:13px;">定价模式</th>
                        </tr>
                    </thead>
                    <tbody>{price_rows}</tbody>
                </table>
                {ranking_html}
                {'<div style="margin-top:16px;padding:12px 16px;background:#fffbeb;border-radius:8px;font-size:14px;line-height:1.8;"><strong>策略分析：</strong>' + esc(pricing_analysis.pricing_strategy_analysis) + '</div>' if pricing_analysis.pricing_strategy_analysis else ''}
            </div>'''

        # ══════════════════════════════════════════════
        # 区块5：市场格局分析
        # ══════════════════════════════════════════════
        market_html = ""
        if market_analysis and market_analysis.market_share_data:
            # 解析市场份额数值，用于条形图比例
            max_share = 0
            share_data = []
            for ms in market_analysis.market_share_data:
                num_match = re.search(r'([\d.]+)', ms.share_estimate)
                share_num = float(num_match.group(1)) if num_match else 0
                max_share = max(max_share, share_num)
                share_data.append((ms, share_num))

            share_data_sorted = sorted(share_data, key=lambda x: x[1], reverse=True)

            # 份额条形图
            share_bars = ""
            for ms, share_num in share_data_sorted:
                if max_share > 0 and share_num > 0:
                    bar_width = max(share_num / max_share * 85, 8)
                else:
                    bar_width = 8
                share_bars += f'''
                <div style="display:flex;align-items:center;margin-bottom:10px;">
                    <div style="width:140px;font-size:13px;font-weight:500;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{esc(ms.competitor)}">{esc(ms.competitor)}{cite_sup(ms.citations)}</div>
                    <div style="flex:1;margin:0 12px;">
                        <div style="background:#f1f5f9;border-radius:6px;height:26px;overflow:hidden;position:relative;">
                            <div style="background:linear-gradient(90deg,#3b82f6,#6366f1);height:100%;width:{bar_width:.1f}%;border-radius:6px;min-width:8px;"></div>
                        </div>
                    </div>
                    <div style="width:90px;font-size:13px;color:#475569;flex-shrink:0;text-align:right;">{esc(ms.share_estimate)}</div>
                    <div style="width:60px;text-align:center;flex-shrink:0;">{trend_icon(ms.trend)}</div>
                </div>'''

            # 用户口碑
            reputation_html = ""
            if market_analysis.user_reputation:
                rep_cards = ""
                for name, rep in market_analysis.user_reputation.items():
                    kw_tags = ""
                    for kw in (rep.keywords or [])[:5]:
                        kw_tags += f'<span style="background:#ede9fe;color:#6d28d9;padding:2px 8px;border-radius:12px;font-size:11px;display:inline-block;margin:2px 2px 0 0;">{esc(kw)}</span>'
                    rep_cards += f'''
                    <div style="background:#f8fafc;border-radius:10px;padding:14px;min-width:160px;max-width:220px;box-sizing:border-box;">
                        <div style="font-weight:600;font-size:14px;margin-bottom:6px;word-break:break-all;">{esc(name)}</div>
                        <div style="font-size:20px;font-weight:700;color:#f59e0b;margin-bottom:4px;">{esc(rep.score) if rep.score else '—'}{cite_sup(rep.citations)}</div>
                        <div style="line-height:1.8;">{kw_tags}</div>
                    </div>'''
                reputation_html = f'''
                <div style="margin-top:20px;">
                    <h3 style="font-size:16px;color:#475569;margin-bottom:12px;">👥 用户口碑</h3>
                    <div style="display:flex;gap:12px;flex-wrap:wrap;">{rep_cards}</div>
                </div>'''

            # 用户画像
            profiles_html = ""
            if market_analysis.user_profiles:
                profile_cards = ""
                for name, profile in market_analysis.user_profiles.items():
                    def make_tags(items, bg, fg):
                        if not items:
                            return '—'
                        return "".join(
                            f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:12px;font-size:11px;display:inline-block;margin:2px 4px 0 0;">{esc(it)}</span>'
                            for it in items[:4]
                        )
                    occ_tags = make_tags(profile.occupation_distribution, "#dbeafe", "#1e40af")
                    use_tags = make_tags(profile.use_cases, "#dcfce7", "#166534")
                    pain_tags = make_tags(profile.pain_points, "#fee2e2", "#991b1b")
                    profile_cards += f'''
                    <div style="background:#f8fafc;border-radius:10px;padding:14px;min-width:260px;flex:1;box-sizing:border-box;">
                        <div style="font-weight:600;font-size:14px;margin-bottom:8px;word-break:break-all;">{esc(name)}{cite_sup(profile.citations)}</div>
                        <div style="font-size:13px;margin-bottom:6px;"><strong>目标用户：</strong>{esc(profile.target_audience) if profile.target_audience else '—'}</div>
                        <div style="font-size:13px;margin-bottom:6px;"><strong>年龄分布：</strong>{esc(profile.age_range) if profile.age_range else '—'}</div>
                        <div style="font-size:13px;margin-bottom:6px;"><strong>职业分布：</strong>{occ_tags}</div>
                        <div style="font-size:13px;margin-bottom:6px;"><strong>使用场景：</strong>{use_tags}</div>
                        <div style="font-size:13px;"><strong>核心痛点：</strong>{pain_tags}</div>
                    </div>'''
                profiles_html = f'''
                <div style="margin-top:20px;">
                    <h3 style="font-size:16px;color:#475569;margin-bottom:12px;">🎯 用户画像</h3>
                    <div style="display:flex;gap:12px;flex-wrap:wrap;">{profile_cards}</div>
                </div>'''

            # 增长趋势和渠道分析
            trend_html = ""
            if market_analysis.growth_trends:
                trend_html = f'<div style="margin-top:16px;padding:12px 16px;background:#eff6ff;border-radius:8px;font-size:14px;line-height:1.8;word-break:break-all;"><strong>增长趋势：</strong>{esc(market_analysis.growth_trends)}</div>'
            channel_html = ""
            if market_analysis.channel_analysis:
                channel_html = f'<div style="margin-top:10px;padding:12px 16px;background:#fef3c7;border-radius:8px;font-size:14px;line-height:1.8;word-break:break-all;"><strong>渠道分析：</strong>{esc(market_analysis.channel_analysis)}</div>'

            market_html = f'''
            <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);overflow:hidden;">
                <h2 style="margin:0 0 20px 0;font-size:20px;color:#1e293b;">📈 市场格局分析</h2>
                {share_bars}
                {reputation_html}
                {profiles_html}
                {trend_html}
                {channel_html}
            </div>'''

        # ══════════════════════════════════════════════
        # 区块6：本产品差异化定位
        # ══════════════════════════════════════════════
        # 差异化锚点（基于功能矩阵，找出我方独有功能）
        our_unique_features = []
        if product_analysis and product_analysis.feature_matrix:
            for fm in product_analysis.feature_matrix:
                our_val = find_value(fm.values, report.product_name, report.product_name)
                if our_val in ("✅", "✓", "有", "支持"):
                    # 检查是否所有竞品都不支持
                    all_competitors_lack = True
                    for comp_name in competitor_names:
                        comp_val = find_value(fm.values, comp_name, report.product_name)
                        if comp_val in ("✅", "✓", "有", "支持"):
                            all_competitors_lack = False
                            break
                    if all_competitors_lack:
                        our_unique_features.append(fm.feature)

        # 我方胜出维度（我方有，多数竞品没有或只有部分）
        our_advantage_features = []
        if product_analysis and product_analysis.feature_matrix:
            for fm in product_analysis.feature_matrix:
                our_val = find_value(fm.values, report.product_name, report.product_name)
                if our_val in ("✅", "✓", "有", "支持"):
                    lack_count = sum(
                        1 for cn in competitor_names
                        if find_value(fm.values, cn, report.product_name) not in ("✅", "✓", "有", "支持")
                    )
                    if lack_count > len(competitor_names) / 2 and fm.feature not in our_unique_features:
                        our_advantage_features.append(fm.feature)

        # 差异化定位卡
        unique_features_html = ""
        if our_unique_features:
            items = ""
            for f in our_unique_features:
                items += f'<span style="background:#dcfce7;color:#166534;padding:6px 14px;border-radius:8px;font-size:13px;font-weight:500;margin:4px;display:inline-block;">🔥 {esc(f)}</span>'
            unique_features_html = f'''
            <div style="margin-bottom:16px;">
                <div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:8px;">🏆 独占优势（竞品均不具备）</div>
                <div>{items}</div>
            </div>'''

        advantage_features_html = ""
        if our_advantage_features:
            items = ""
            for f in our_advantage_features:
                items += f'<span style="background:#dbeafe;color:#1e40af;padding:6px 14px;border-radius:8px;font-size:13px;font-weight:500;margin:4px;display:inline-block;">⚡ {esc(f)}</span>'
            advantage_features_html = f'''
            <div style="margin-bottom:16px;">
                <div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:8px;">💪 领先优势（多数竞品不具备）</div>
                <div>{items}</div>
            </div>'''

        # 差异化亮点（从product_analysis）
        diff_points_html = ""
        if product_analysis and product_analysis.differentiation_points:
            items = ""
            for dp in product_analysis.differentiation_points:
                items += f'<li style="padding:4px 0;font-size:14px;color:#475569;">✦ {esc(dp)}</li>'
            diff_points_html = f'''
            <div style="margin-bottom:16px;">
                <div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:8px;">💎 核心差异化亮点</div>
                <ul style="margin:0;padding-left:20px;line-height:1.8;">{items}</ul>
            </div>'''

        # 逐竞品差异化定位（我方 vs 每个竞品的差异化锚点）
        per_competitor_positioning = ""
        if product_analysis and product_analysis.competitive_advantages:
            for adv in product_analysis.competitive_advantages:
                per_competitor_positioning += f'''
                <div style="display:flex;gap:12px;margin-bottom:10px;align-items:stretch;">
                    <div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 14px;border-radius:0 8px 8px 0;flex:1;">
                        <div style="font-size:11px;color:#16a34a;font-weight:600;margin-bottom:2px;">vs {esc(adv.competitor)} 我方胜出</div>
                        <div style="font-size:13px;color:#15803d;line-height:1.5;">{esc(adv.our_advantage)}{cite_sup(adv.citations)}</div>
                    </div>
                    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:10px 14px;border-radius:0 8px 8px 0;flex:1;">
                        <div style="font-size:11px;color:#dc2626;font-weight:600;margin-bottom:2px;">vs {esc(adv.competitor)} 需追赶</div>
                        <div style="font-size:13px;color:#b91c1c;line-height:1.5;">{esc(adv.their_advantage)}{cite_sup(adv.citations)}</div>
                    </div>
                </div>'''

        # 差异化定位整体模块
        diff_positioning_html = f'''
        <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <h2 style="margin:0 0 20px 0;font-size:20px;color:#1e293b;">🧭 {esc(report.product_name)} 差异化定位</h2>

            <!-- 定位声明 -->
            <div style="background:linear-gradient(135deg,#1e293b,#334155);border-radius:12px;padding:20px;margin-bottom:20px;color:#fff;">
                <div style="font-size:12px;opacity:0.7;margin-bottom:6px;">定位声明</div>
                <div style="font-size:16px;font-weight:600;line-height:1.6;">{esc(report.overall_positioning) if report.overall_positioning else '暂无'}</div>
            </div>

            {unique_features_html}
            {advantage_features_html}
            {diff_points_html}

            {'<div style="margin-top:20px;"><div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:12px;">⚔️ 逐竞品差异化锚点</div>' + per_competitor_positioning + '</div>' if per_competitor_positioning else ''}
        </div>'''

        # ══════════════════════════════════════════════
        # 区块7：策略建议
        # ══════════════════════════════════════════════
        # 差异化策略（来自report）
        diff_strategy_html = ""
        if report.differentiation_strategy:
            core = report.differentiation_strategy.get("core_differentiator", "")
            points = report.differentiation_strategy.get("supporting_points", [])
            points_items = ""
            for p in points:
                points_items += f'<li style="padding:4px 0;font-size:14px;">✦ {esc(p)}</li>'
            diff_strategy_html = f'''
            <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <h2 style="margin:0 0 16px 0;font-size:20px;color:#1e293b;">🎯 差异化策略</h2>
                <div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:12px;">
                    <strong style="font-size:15px;">核心差异：</strong>
                    <span style="font-size:15px;">{esc(core)}</span>
                </div>
                {'<ul style="margin:0;padding-left:20px;line-height:1.8;">' + points_items + '</ul>' if points_items else ''}
            </div>'''

        # SWOT 分析矩阵
        swot_html = ""
        if report.swot:
            swot = report.swot

            def render_swot_items(items: list[str], color: str) -> str:
                if not items:
                    return f'<div style="color:#94a3b8;font-size:13px;font-style:italic;">暂无数据</div>'
                html = ""
                for item in items:
                    html += f'<div style="padding:4px 0;font-size:13px;color:#334155;">• {esc(item)}</div>'
                return html

            s_items = render_swot_items(swot.strengths.items, "#22c55e")
            w_items = render_swot_items(swot.weaknesses.items, "#f59e0b")
            o_items = render_swot_items(swot.opportunities.items, "#3b82f6")
            t_items = render_swot_items(swot.threats.items, "#ef4444")

            # 交叉矩阵策略
            cross_html = ""
            cs = swot.cross_strategies
            if cs:
                strategies = [
                    ("SO（进攻）", cs.so, "#22c55e", "利用优势抓住机会"),
                    ("WO（改进）", cs.wo, "#f59e0b", "弥补劣势以抓住机会"),
                    ("ST（防御）", cs.st, "#3b82f6", "利用优势应对威胁"),
                    ("WT（规避）", cs.wt, "#ef4444", "减少劣势以规避威胁"),
                ]
                for label, items, color, desc in strategies:
                    if items:
                        items_html = "".join(
                            f'<div style="padding:3px 0;font-size:13px;color:#334155;">• {esc(item)}</div>'
                            for item in items
                        )
                        cross_html += f'''
                        <div style="background:#fff;border:1px solid {color}33;border-left:4px solid {color};border-radius:8px;padding:14px 16px;flex:1;min-width:220px;">
                            <div style="font-size:14px;font-weight:600;color:{color};margin-bottom:4px;">{label}</div>
                            <div style="font-size:12px;color:#64748b;margin-bottom:8px;">{desc}</div>
                            {items_html}
                        </div>'''

            swot_html = f'''
        <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <h2 style="margin:0 0 20px 0;font-size:20px;color:#1e293b;">📊 SWOT 分析矩阵</h2>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;">
                <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:18px;">
                    <div style="font-size:15px;font-weight:700;color:#16a34a;margin-bottom:10px;">💪 优势 Strengths</div>
                    {s_items}
                </div>
                <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:18px;">
                    <div style="font-size:15px;font-weight:700;color:#d97706;margin-bottom:10px;">⚠️ 劣势 Weaknesses</div>
                    {w_items}
                </div>
                <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:18px;">
                    <div style="font-size:15px;font-weight:700;color:#2563eb;margin-bottom:10px;">🌟 机会 Opportunities</div>
                    {o_items}
                </div>
                <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:18px;">
                    <div style="font-size:15px;font-weight:700;color:#dc2626;margin-bottom:10px;">🔴 威胁 Threats</div>
                    {t_items}
                </div>
            </div>

            {'<div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:12px;">🔄 交叉矩阵策略</div><div style="display:flex;gap:12px;flex-wrap:wrap;">' + cross_html + '</div>' if cross_html else ''}
        </div>'''

        # 行动方案
        action_cards = ""
        for ap in report.action_plan:
            action_cards += f'''
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;flex:1;min-width:280px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
                    {priority_badge(ap.priority)}
                    <strong style="font-size:15px;">{esc(ap.action)}{cite_sup(ap.citations)}</strong>
                </div>
                {'<div style="font-size:13px;color:#64748b;margin-bottom:4px;">⏰ ' + esc(ap.timeline) + '</div>' if ap.timeline else ''}
                {'<div style="font-size:13px;color:#475569;">🎯 ' + esc(ap.expected_impact) + '</div>' if ap.expected_impact else ''}
            </div>'''

        action_html = f'''
        <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <h2 style="margin:0 0 20px 0;font-size:20px;color:#1e293b;">📋 行动方案</h2>
            <div style="display:flex;gap:16px;flex-wrap:wrap;">{action_cards}</div>
        </div>'''

        # 风险评估
        risk_html = f'''
        <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <h2 style="margin:0 0 12px 0;font-size:20px;color:#1e293b;">⚠️ 风险评估</h2>
            <p style="font-size:15px;line-height:1.8;color:#475569;margin:0;">{esc(report.risk_assessment) if report.risk_assessment else '暂无'}</p>
        </div>'''

        # 三维摘要
        summary_cards = ""
        if report.product_analysis_summary:
            summary_cards += f'''
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;flex:1;min-width:200px;">
                <div style="font-size:24px;margin-bottom:8px;">🔧</div>
                <div style="font-weight:600;font-size:14px;margin-bottom:6px;">产品分析</div>
                <div style="font-size:13px;color:#64748b;line-height:1.6;">{esc(report.product_analysis_summary)}</div>
            </div>'''
        if report.pricing_analysis_summary:
            summary_cards += f'''
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;flex:1;min-width:200px;">
                <div style="font-size:24px;margin-bottom:8px;">💰</div>
                <div style="font-weight:600;font-size:14px;margin-bottom:6px;">定价分析</div>
                <div style="font-size:13px;color:#64748b;line-height:1.6;">{esc(report.pricing_analysis_summary)}</div>
            </div>'''
        if report.market_analysis_summary:
            summary_cards += f'''
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;flex:1;min-width:200px;">
                <div style="font-size:24px;margin-bottom:8px;">📈</div>
                <div style="font-weight:600;font-size:14px;margin-bottom:6px;">市场分析</div>
                <div style="font-size:13px;color:#64748b;line-height:1.6;">{esc(report.market_analysis_summary)}</div>
            </div>'''

        # 综合建议
        overall_summary_html = ""
        if report.summary:
            overall_summary_html = f'''
            <div style="background:linear-gradient(135deg,#1e3a5f,#1e293b);border-radius:16px;padding:28px;margin-bottom:24px;color:#fff;">
                <h2 style="margin:0 0 12px 0;font-size:20px;">💡 综合建议</h2>
                <p style="font-size:15px;line-height:1.8;margin:0;opacity:0.95;">{esc(report.summary)}</p>
            </div>'''

        # 耗时统计
        timing_html = ""
        if timings:
            timing_items = ""
            labels = {
                "discovery": "竞品发现",
                "collection": "数据采集",
                "parallel_analysis": "并行分析",
                "strategy": "策略建议",
                "total": "总耗时",
            }
            for key, val in timings.items():
                label = labels.get(key, key)
                is_total = key == "total"
                style = 'font-weight:700;font-size:14px;' if is_total else 'font-size:13px;'
                timing_items += f'<div style="display:flex;justify-content:space-between;padding:4px 0;{style}"><span>{label}</span><span>{val:.2f}s</span></div>'
            timing_html = f'''
            <div style="background:#f8fafc;border-radius:12px;padding:16px;margin-top:24px;">
                <div style="font-size:13px;font-weight:600;color:#64748b;margin-bottom:8px;">⏱️ 耗时统计</div>
                {timing_items}
            </div>'''

        # 质量检查板块
        qa_html = ""
        if report.qa_timeline and report.qa_timeline.checks:
            qa_checks_html = ""
            for check in report.qa_timeline.checks:
                status_class = "passed" if check.passed else "failed"
                status_text = "✅ 通过" if check.passed else "❌ 未通过"
                degraded_badge = ' <span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:11px;">⚠️ 降级通过</span>' if check.degraded else ""

                issues_html = ""
                if check.issues:
                    issue_items = ""
                    for issue in check.issues[:5]:
                        severity_color = "#dc2626" if issue.severity == "critical" else "#d97706"
                        issue_items += f'''
                        <div style="padding:6px 12px;border-left:3px solid {severity_color};background:#fafafa;margin:4px 0;border-radius:0 4px 4px 0;">
                            <span style="color:{severity_color};font-weight:600;">[{issue.severity}]</span>
                            <span style="color:#475569;font-size:12px;">{issue.field}: {issue.description}</span>
                            {f'<span style="color:#6b7280;font-size:11px;"> — 建议: {issue.suggestion}</span>' if issue.suggestion else ''}
                        </div>'''
                    issues_html = f'<div style="margin-top:8px;">{issue_items}</div>'

                border_color = "#22c55e" if check.passed else "#ef4444"
                qa_checks_html += f'''
                <div style="background:#fff;border-left:4px solid {border_color};border-radius:0 8px 8px 0;padding:12px 16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                        <div>
                            <span style="font-weight:600;color:#1e293b;">{check.target_agent}</span>
                            <span style="color:#94a3b8;font-size:12px;margin-left:8px;">第{check.attempt}次检查</span>
                            {degraded_badge}
                        </div>
                        <div>
                            <span style="font-size:13px;">{status_text}</span>
                            <span style="color:#94a3b8;font-size:12px;margin-left:8px;">质量分数: {check.score:.0f}/100</span>
                        </div>
                    </div>
                    {issues_html}
                </div>'''

            all_passed = report.qa_timeline.all_passed()
            final_status = "全部通过" if all_passed else "部分降级通过"
            final_color = "#16a34a" if all_passed else "#d97706"

            # 业务闭环指标
            accuracy_rate = report.qa_timeline.get_accuracy_rate()
            coverage_rate = report.qa_timeline.get_coverage_rate()
            correction_rate = report.qa_timeline.get_correction_rate()

            def _metric_color(val: float, invert: bool = False) -> str:
                """指标颜色：>80 绿, >60 黄, <=60 红。invert=True 时越低越好。"""
                v = 100 - val if invert else val
                if v >= 80: return "#16a34a"
                if v >= 60: return "#d97706"
                return "#dc2626"

            def _metric_bar(val: float, color: str) -> str:
                return f'''<div style="background:#e5e7eb;border-radius:4px;height:8px;width:100%;margin-top:6px;">
                    <div style="background:{color};border-radius:4px;height:8px;width:{min(val, 100):.0f}%;transition:width 0.3s;"></div>
                </div>'''

            acc_color = _metric_color(accuracy_rate)
            cov_color = _metric_color(coverage_rate)
            cor_color = _metric_color(correction_rate, invert=True)

            metrics_card_style = "background:#fff;padding:16px 20px;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.06);flex:1;min-width:180px;"
            metrics_html = f'''
            <div style="background:#f0fdf4;border-radius:16px;padding:32px;margin-bottom:24px;">
                <h2 style="font-size:20px;color:#1e293b;margin:0 0 20px 0;">📊 业务闭环指标</h2>
                <div style="display:flex;gap:20px;flex-wrap:wrap;">
                    <div style="{metrics_card_style}">
                        <div style="font-size:12px;color:#94a3b8;">准确率</div>
                        <div style="font-size:28px;font-weight:700;color:{acc_color};">{accuracy_rate:.1f}%</div>
                        <div style="font-size:11px;color:#94a3b8;margin-top:2px;">无幻觉断言占比</div>
                        {_metric_bar(accuracy_rate, acc_color)}
                    </div>
                    <div style="{metrics_card_style}">
                        <div style="font-size:12px;color:#94a3b8;">覆盖率</div>
                        <div style="font-size:28px;font-weight:700;color:{cov_color};">{coverage_rate:.1f}%</div>
                        <div style="font-size:11px;color:#94a3b8;margin-top:2px;">已填充字段占比</div>
                        {_metric_bar(coverage_rate, cov_color)}
                    </div>
                    <div style="{metrics_card_style}">
                        <div style="font-size:12px;color:#94a3b8;">人工修正率</div>
                        <div style="font-size:28px;font-weight:700;color:{cor_color};">{correction_rate:.1f}%</div>
                        <div style="font-size:11px;color:#94a3b8;margin-top:2px;">经重试补充的字段占比</div>
                        {_metric_bar(correction_rate, cor_color)}
                    </div>
                </div>
            </div>'''

            qa_html = f'''
            <div style="background:#f8fafc;border-radius:16px;padding:32px;margin-bottom:24px;">
                <h2 style="font-size:20px;color:#1e293b;margin:0 0 16px 0;">🔍 质量检查</h2>
                <div style="display:flex;gap:24px;margin-bottom:20px;flex-wrap:wrap;">
                    <div style="background:#fff;padding:12px 20px;border-radius:8px;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
                        <div style="font-size:12px;color:#94a3b8;">总检查次数</div>
                        <div style="font-size:20px;font-weight:600;color:#1e293b;">{len(report.qa_timeline.checks)}</div>
                    </div>
                    <div style="background:#fff;padding:12px 20px;border-radius:8px;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
                        <div style="font-size:12px;color:#94a3b8;">重试次数</div>
                        <div style="font-size:20px;font-weight:600;color:#1e293b;">{report.qa_timeline.total_retries}</div>
                    </div>
                    <div style="background:#fff;padding:12px 20px;border-radius:8px;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
                        <div style="font-size:12px;color:#94a3b8;">最终状态</div>
                        <div style="font-size:20px;font-weight:600;color:{final_color};">{final_status}</div>
                    </div>
                </div>
                {qa_checks_html}
            </div>
            {metrics_html}'''

        # 对正文实际引用的来源重新从 1 开始编号，消除序号空洞
        # 构建旧编号→新编号的映射，用于字符串替换
        old_to_new: dict[int, int] = {}
        used_sorted = []
        if used_cite_ids and global_cite_num:
            used_sorted = sorted(
                used_cite_ids,
                key=lambda cid: global_cite_num.get(cid, 99999),
            )
            for new_idx, cid in enumerate(used_sorted, 1):
                old_num = global_cite_num.get(cid)
                if old_num is not None:
                    old_to_new[old_num] = new_idx
                global_cite_num[cid] = new_idx

        # 数据来源附录（只展示正文实际引用的来源）
        references_html = ""
        if report.citation_index and used_cite_ids:
            ref_items = ""
            seen_urls = set()
            used_count = 0
            for cid in used_sorted:
                cite = report.citation_index.get(cid)
                if not cite:
                    continue
                if cite.url and cite.url in seen_urls:
                    continue
                if cite.url:
                    seen_urls.add(cite.url)
                used_count += 1
                num = global_cite_num.get(cid, "")
                num_label = f'<span style="display:inline-block;min-width:28px;font-weight:700;color:#3b82f6;font-size:13px;">[{num}]</span>' if num else ""
                site_label = f' <span style="color:#64748b;font-size:12px;">({esc(cite.site_name)})</span>' if cite.site_name else ""
                query_label = f' <span style="color:#94a3b8;font-size:11px;">搜索词: {esc(cite.query)}</span>' if cite.query else ""
                url_link = f'<a href="{esc(cite.url)}" target="_blank" rel="noopener" style="color:#3b82f6;text-decoration:none;">{esc(cite.title or cite.url)}</a>' if cite.url else esc(cite.title)
                ref_items += f'''
                <div id="cite-{cid}" style="padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:13px;">
                    {num_label}{url_link}{site_label}{query_label}
                </div>'''
            references_html = f'''
            <div style="background:#fff;border-radius:16px;padding:24px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <h2 style="font-size:20px;color:#1e293b;margin-bottom:16px;">📚 数据来源（共 {used_count} 条）</h2>
                <div style="max-height:400px;overflow-y:auto;">{ref_items}</div>
            </div>'''

        # ══════════════════════════════════════════════
        # 组装完整HTML
        # ══════════════════════════════════════════════
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>智能竞品分析报告 — {esc(report.product_name)}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; background: #f1f5f9; color: #1e293b; }}
    </style>
</head>
<body>
<div style="max-width:1100px;margin:0 auto;padding:24px;">

    <!-- 报告头部 -->
    <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);border-radius:20px;padding:40px;margin-bottom:28px;color:#fff;">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;">
            <div>
                <h1 style="font-size:28px;font-weight:700;margin-bottom:8px;">🔍 智能竞品分析报告</h1>
                <div style="font-size:20px;opacity:0.9;margin-bottom:12px;">{esc(report.product_name)}</div>
                <div style="font-size:14px;opacity:0.75;">分析竞品 {report.competitor_count} 个 · 生成时间 {now}</div>
            </div>
            <div style="text-align:right;">
                <div style="background:rgba(255,255,255,0.2);border-radius:12px;padding:12px 20px;">
                    <div style="font-size:12px;opacity:0.8;">协作模式</div>
                    <div style="font-size:15px;font-weight:600;">串行采集 → 并行分析 → 串行汇总</div>
                </div>
            </div>
        </div>
	    </div>

	    <!-- 目标产品介绍 -->
	    {render_target_product_intro_from_llm(report.target_product_intro, report.target_product_data) or render_target_product_intro(report.target_product_data)}

	    <!-- 竞品发现 -->
	    {"<div style='margin-bottom:24px;'><h2 style='font-size:20px;color:#1e293b;margin-bottom:16px;'>🔎 发现竞品</h2><div style='display:flex;gap:16px;flex-wrap:wrap;'>" + competitor_cards + '</div></div>' if competitor_cards else ''}

    <!-- 逐竞品对比（核心板块） -->
    {competitor_comparison_cards}

    <!-- 功能对比矩阵（总览） -->
    {feature_matrix_html}

    <!-- 定价分析 -->
    {pricing_html}

    <!-- 市场分析 -->
    {market_html}

    <!-- 本产品差异化定位 -->
    {diff_positioning_html}

    <!-- 分隔线 -->
    <div style="text-align:center;margin:32px 0;font-size:20px;color:#cbd5e1;">━━━━━━━━━━━  策略建议  ━━━━━━━━━━━</div>

    <!-- 策略建议 -->
    {diff_strategy_html}
    {swot_html}
    {action_html}
    {risk_html}

    <!-- 三维分析摘要 -->
    {"<div style='margin-bottom:24px;'><h2 style='font-size:20px;color:#1e293b;margin-bottom:16px;'>📊 三维分析摘要</h2><div style='display:flex;gap:16px;flex-wrap:wrap;'>" + summary_cards + '</div></div>' if summary_cards else ''}

    {overall_summary_html}

    {timing_html}

    <!-- 质量检查 -->
    {qa_html}

    <!-- 数据来源附录 -->
    {references_html}

    <!-- 页脚 -->
    <div style="text-align:center;padding:24px 0;font-size:12px;color:#94a3b8;">
        智能竞品分析多Agent系统 · 串行采集 → 并行分析 → 串行汇总
    </div>

</div>
</body>
</html>'''

        # 替换正文中已渲染的引用编号（消除空洞，从 1 连续）
        if old_to_new:
            def _replace_cite_num(m):
                old = int(m.group(1))
                new = old_to_new.get(old)
                if new is not None:
                    return f'[{new}]'
                return m.group(0)
            html = re.sub(r'\[(\d+)\](?=(</a></sup>))', _replace_cite_num, html)

        return html
