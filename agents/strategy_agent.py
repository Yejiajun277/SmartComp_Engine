# -*- coding: utf-8 -*-
"""
agents/strategy_agent.py - 策略报告 Agent
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import urlparse

import config
from agents.base_agent import BaseAgent
from core.prompt_loader import load as load_prompts
from models.domain import (
    ActionItem,
    Citation,
    CompetitorData,
    CompetitorList,
    CompetitiveAdvantage,
    EvidenceBundle,
    FeatureComparison,
    MarketAnalysis,
    MarketShareItem,
    PricingAnalysis,
    PricingItem,
    ProductAnalysis,
    StrategyReport,
    UserPersona,
)


class StrategyAgent(BaseAgent):
    def __init__(self):
        prompts = load_prompts("strategy_agent")
        super().__init__(
            agent_id="StrategyAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_strategy = prompts["prompt_strategy"]
        self._citation_number_map: dict[str, int] = {}

    async def run(
        self,
        product_name: str,
        competitor_count: int,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        evidence_bundles: dict[str, list[EvidenceBundle]] | None = None,
        competitors_data: dict[str, CompetitorData] | None = None,
    ) -> StrategyReport:
        evidence_bundles = evidence_bundles or {}
        competitors_data = competitors_data or {}
        merged_citations = self._merge_citations(
            product_analysis.citations,
            pricing_analysis.citations,
            market_analysis.citations,
        )

        if config.ENABLE_LLM:
            prompt = self._prompt_strategy.format(
                product_name=product_name,
                analysis_text=self._build_analysis_text(
                    product_name,
                    product_analysis,
                    pricing_analysis,
                    market_analysis,
                    evidence_bundles,
                    competitors_data,
                ),
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                report = self._parse_strategy_report(
                    product_name=product_name,
                    competitor_count=competitor_count,
                    result=result,
                    product_analysis=product_analysis,
                    pricing_analysis=pricing_analysis,
                    market_analysis=market_analysis,
                    citations=merged_citations,
                    evidence_bundles=evidence_bundles,
                )
                if report.action_plan and report.overall_positioning:
                    self._log(f"策略 LLM 报告生成完成，行动项={len(report.action_plan)}")
                    return report
            self._log("策略 LLM 汇总失败，降级到规则引擎")

        report = self._rule_strategy(
            product_name,
            competitor_count,
            product_analysis,
            pricing_analysis,
            market_analysis,
            merged_citations,
        )
        self._log("策略规则报告生成完成")
        return report

    def _rule_strategy(
        self,
        product_name: str,
        competitor_count: int,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        merged_citations: list[Citation],
    ) -> StrategyReport:
        top_diff_points = product_analysis.differentiation_points[:3]
        product_focus = (
            product_analysis.conclusions[0].statement
            if product_analysis.conclusions
            else (top_diff_points[0] if top_diff_points else "把高频场景说清楚，并压缩交付路径。")
        )
        pricing_focus = (
            pricing_analysis.conclusions[0].statement
            if pricing_analysis.conclusions
            else "把免费入口、升级触发点和计费单位讲清楚。"
        )
        market_focus = (
            market_analysis.conclusions[0].statement
            if market_analysis.conclusions
            else "围绕目标客户、使用场景和真实采购顾虑补证据。"
        )

        product_citation_ids = self._take_conclusion_citations(product_analysis.conclusions, limit=3)
        pricing_citation_ids = self._take_conclusion_citations(pricing_analysis.conclusions, limit=3)
        market_citation_ids = self._take_conclusion_citations(market_analysis.conclusions, limit=3)

        risk_points = [
            "市场份额和趋势更适合支持相对位置判断，强结论应优先绑定高可信来源。",
            "如果定价信息主要来自聚合页或转述页，商业化判断会比功能判断更容易失真。",
            "多数竞品都在强化 AI、集成和场景表达，继续堆功能名词会落回低区分度竞争。",
        ]

        return StrategyReport(
            product_name=product_name,
            competitor_count=competitor_count,
            overall_positioning=(
                f"{product_name} 不应继续按“功能是否齐全”去拼表，而应围绕自动化、开放集成和高频协作场景重组价值表达。"
                f" 产品层优先回答：{product_focus}"
                f" 商业化层优先回答：{pricing_focus}"
            ),
            differentiation_strategy={
                "core_differentiator": "把自动化、开放集成和高频协作打包成更短的交付路径，而不是继续堆功能名词。",
                "supporting_points": top_diff_points,
            },
            action_plan=[
                ActionItem(
                    priority="P0",
                    action="把最核心的 1-2 个高频场景重写成标准方案，明确输入、输出和交付时长。",
                    timeline="1-2 周",
                    expected_impact="提升销售材料可理解性，降低与竞品的同质化对比。",
                    citations=product_citation_ids,
                ),
                ActionItem(
                    priority="P1",
                    action="重写价格与升级说明，明确免费入口、升级触发点、计费单位，以及 AI 能力是否单独收费。",
                    timeline="2-3 周",
                    expected_impact="减少价格沟通摩擦，提升试用到付费的转化效率。",
                    citations=pricing_citation_ids,
                ),
                ActionItem(
                    priority="P1",
                    action="围绕目标客户做 5-8 个访谈或问卷，验证口碑问题、采购顾虑和真实使用场景。",
                    timeline="2 周",
                    expected_impact="把用户画像从推测变成证据，补齐产品优先级和卖点依据。",
                    citations=market_citation_ids,
                ),
            ],
            risk_assessment=" ".join(risk_points),
            product_analysis_summary=product_analysis.summary,
            pricing_analysis_summary=pricing_analysis.summary,
            market_analysis_summary=market_analysis.summary,
            citations=merged_citations,
            summary=(
                f"综合来看，{product_name} 的机会不在于继续做一份泛化对标，而在于重写“为什么现在应该选你”。"
                f" 产品上要把 {product_focus} 讲成结果，价格上要把升级逻辑讲清楚，市场上要围绕 {market_focus} 验证真实需求。"
                " 只有这样，报告里的结论才会从信息罗列变成可执行策略。"
            ),
        )

    @staticmethod
    def _build_analysis_text(
        product_name: str,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        evidence_bundles: dict[str, list[EvidenceBundle]],
        competitors_data: dict[str, CompetitorData] | None = None,
    ) -> str:
        lines: list[str] = []
        competitors_data = competitors_data or {}

        lines.append("## 一、产品分析")
        lines.append(f"摘要: {product_analysis.summary}")
        if product_analysis.feature_matrix:
            lines.append("功能矩阵:")
            for item in product_analysis.feature_matrix[:15]:
                values = "；".join(f"{name}={value}" for name, value in item.values.items())
                lines.append(f"- {item.feature}: {values}")
        if product_analysis.competitive_advantages:
            lines.append("逐竞品优劣:")
            for item in product_analysis.competitive_advantages[:8]:
                lines.append(
                    f"- vs {item.competitor}: 我方优势={item.our_advantage}; "
                    f"对方优势={item.their_advantage or item.their_strength}; "
                    f"对方短板={item.their_weakness}; 应对={item.recommended_countermove}"
                )
        if product_analysis.differentiation_points:
            lines.append(f"差异化点: {'；'.join(product_analysis.differentiation_points[:6])}")

        lines.append("\n## 二、定价分析")
        lines.append(f"摘要: {pricing_analysis.summary}")
        for item in pricing_analysis.pricing_comparison[:8]:
            lines.append(
                f"- {item.competitor}: 免费={item.free_tier}; 付费={item.paid_tier}; "
                f"模式={item.pricing_model}; 入口={item.entry_offer}; 升级={item.upgrade_trigger}"
            )
        lines.append(f"策略分析: {pricing_analysis.pricing_strategy_analysis}")
        if pricing_analysis.value_ranking:
            lines.append(f"性价比排序: {' > '.join(pricing_analysis.value_ranking)}")

        lines.append("\n## 三、市场分析")
        lines.append(f"摘要: {market_analysis.summary}")
        for item in market_analysis.market_share_data[:8]:
            lines.append(
                f"- {item.competitor}: 份额/规模={item.share_estimate}; 趋势={item.trend}; "
                f"位置={item.market_position}; 增长信号={item.growth_signal}; 渠道动作={item.channel_motion}"
            )
        lines.append(f"增长趋势: {market_analysis.growth_trends}")
        lines.append(f"渠道分析: {market_analysis.channel_analysis}")
        if market_analysis.user_personas:
            lines.append("用户画像:")
            for item in market_analysis.user_personas[:5]:
                lines.append(
                    f"- {item.name}: {item.segment}; 需求={','.join(item.needs)}; "
                    f"抱怨={','.join(item.complaints)}; 渠道={','.join(item.preferred_channels)}"
                )
        competitor_synthesis = StrategyAgent._build_competitor_synthesis_snapshot(competitors_data)
        if competitor_synthesis:
            lines.append("\n## 四、竞品级证据综合画像")
            lines.extend(competitor_synthesis)
        evidence_snapshot = StrategyAgent._build_evidence_snapshot(evidence_bundles)
        if evidence_snapshot:
            lines.append("\n## 五、原始证据快照")
            lines.extend(evidence_snapshot)
        return "\n".join(lines)

    def _parse_strategy_report(
        self,
        product_name: str,
        competitor_count: int,
        result: dict,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        citations: list[Citation],
        evidence_bundles: dict[str, list[EvidenceBundle]],
    ) -> StrategyReport:
        product_citation_ids = self._take_conclusion_citations(product_analysis.conclusions, limit=3)
        pricing_citation_ids = self._take_conclusion_citations(pricing_analysis.conclusions, limit=3)
        market_citation_ids = self._take_conclusion_citations(market_analysis.conclusions, limit=3)
        citation_groups = [product_citation_ids, pricing_citation_ids, market_citation_ids]

        action_plan: list[ActionItem] = []
        for index, item in enumerate(result.get("action_plan", [])[:5]):
            citation_ids = citation_groups[min(index, len(citation_groups) - 1)]
            action = str(item.get("action", "")).strip()
            if not action:
                continue
            action_plan.append(
                ActionItem(
                    priority=str(item.get("priority", "P2")).strip() or "P2",
                    action=action,
                    timeline=str(item.get("timeline", "")).strip(),
                    expected_impact=str(item.get("expected_impact", "")).strip(),
                    citations=citation_ids,
                )
            )

        report = StrategyReport(
            product_name=product_name,
            competitor_count=competitor_count,
            overall_positioning=str(result.get("overall_positioning", "")).strip(),
            differentiation_strategy=(
                result.get("differentiation_strategy", {})
                if isinstance(result.get("differentiation_strategy", {}), dict)
                else {}
            ),
            action_plan=action_plan,
            risk_assessment=str(result.get("risk_assessment", "")).strip(),
            product_analysis_summary=str(result.get("product_analysis_summary", "")).strip() or product_analysis.summary,
            pricing_analysis_summary=str(result.get("pricing_analysis_summary", "")).strip() or pricing_analysis.summary,
            market_analysis_summary=str(result.get("market_analysis_summary", "")).strip() or market_analysis.summary,
            citations=citations,
            summary=str(result.get("summary", "")).strip(),
        )
        return self._post_validate_report(report, evidence_bundles)

    def _post_validate_report(
        self,
        report: StrategyReport,
        evidence_bundles: dict[str, list[EvidenceBundle]],
    ) -> StrategyReport:
        evidence_text = self._build_evidence_reference_text(evidence_bundles)
        report.overall_positioning = self._sanitize_claim_text(report.overall_positioning, evidence_text)
        report.risk_assessment = self._sanitize_claim_text(report.risk_assessment, evidence_text)
        report.product_analysis_summary = self._sanitize_claim_text(report.product_analysis_summary, evidence_text)
        report.pricing_analysis_summary = self._sanitize_claim_text(report.pricing_analysis_summary, evidence_text)
        report.market_analysis_summary = self._sanitize_claim_text(report.market_analysis_summary, evidence_text)
        report.summary = self._sanitize_claim_text(report.summary, evidence_text)
        for item in report.action_plan:
            item.action = self._sanitize_claim_text(item.action, evidence_text)
            item.expected_impact = self._sanitize_claim_text(item.expected_impact, evidence_text)
        return report

    @staticmethod
    def _build_evidence_snapshot(evidence_bundles: dict[str, list[EvidenceBundle]]) -> list[str]:
        lines: list[str] = []
        for competitor, bundles in evidence_bundles.items():
            for bundle in bundles[:5]:
                facts = "；".join(bundle.key_facts[:2])
                quotes = "；".join(bundle.evidence_quotes[:2])
                citation_ids = ",".join(citation.id for citation in bundle.citations[:3] if citation.id)
                snapshot = " | ".join(
                    part
                    for part in [
                        f"{competitor}/{bundle.topic}",
                        facts,
                        quotes,
                        f"citations={citation_ids}" if citation_ids else "",
                    ]
                    if part
                )
                if snapshot:
                    lines.append(f"- {snapshot}")
        return lines[:20]

    @staticmethod
    def _build_competitor_synthesis_snapshot(competitors_data: dict[str, CompetitorData]) -> list[str]:
        lines: list[str] = []
        for name, data in competitors_data.items():
            parts = [
                f"综合画像={data.evidence_digest}" if data.evidence_digest else "",
                f"证据质量={data.evidence_quality_notes}" if data.evidence_quality_notes else "",
                f"未消解冲突={data.unresolved_conflicts}" if data.unresolved_conflicts else "",
            ]
            text = " | ".join(part for part in parts if part)
            if text:
                lines.append(f"- {name}: {text[:1200]}")
        return lines[:12]

    @staticmethod
    def _build_evidence_reference_text(evidence_bundles: dict[str, list[EvidenceBundle]]) -> str:
        parts: list[str] = []
        for bundles in evidence_bundles.values():
            for bundle in bundles:
                parts.append(bundle.summary)
                parts.extend(bundle.key_facts[:4])
                parts.extend(bundle.evidence_quotes[:3])
                parts.extend(citation.snippet for citation in bundle.citations[:3])
        return " ".join(part for part in parts if part).lower()

    @staticmethod
    def _sanitize_claim_text(text: str, evidence_text: str) -> str:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return cleaned

        exclusive_terms = ("首个", "唯一", "第一", "全面领先", "全系标配")
        for term in exclusive_terms:
            if term in cleaned:
                cleaned = cleaned.replace(term, "")

        claim_pattern = re.compile(
            r"\d+(?:\.\d+)?\s*(?:"
            r"万\+?(?:订单|单|辆|台)?|"
            r"万元|元|"
            r"订单|单|辆|台|"
            r"%|km|公里|TOPS|秒"
            r")"
        )
        unsupported_claims = [
            match.group(0)
            for match in claim_pattern.finditer(cleaned)
            if match.group(0).lower() not in evidence_text
        ]
        for claim in unsupported_claims:
            cleaned = cleaned.replace(claim, "待验证")

        cleaned = re.sub(r"[，,]?\s*待验证(?:到|以上|以下|左右)?", "，待验证", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ，,;；")
        return cleaned or "待验证"

    @staticmethod
    def _merge_citations(*citation_lists: list[Citation]) -> list[Citation]:
        seen: dict[str, Citation] = {}
        for citations in citation_lists:
            for citation in citations:
                seen.setdefault(citation.id, citation)

        priority = {
            "official": 5,
            "media": 4,
            "community": 3,
            "complaint": 2,
            "aggregator": 1,
            "low_quality": 0,
        }
        return sorted(
            seen.values(),
            key=lambda item: (priority.get(item.source_quality, 0), item.confidence, item.title),
            reverse=True,
        )

    @staticmethod
    def build_citation_index(citations: list[Citation]) -> dict[str, Citation]:
        return {citation.id: citation for citation in citations if citation.id}

    def _build_citation_number_map(self, citations: list[Citation]) -> dict[str, int]:
        numbered: dict[str, int] = {}
        counter = 1
        for citation in citations:
            if not citation.id or not citation.url or citation.id in numbered:
                continue
            numbered[citation.id] = counter
            counter += 1
        return numbered

    def render_citation_links(
        self,
        citation_ids: list[str],
        citation_map: dict[str, Citation],
        empty_label: str = "",
    ) -> str:
        badges = []
        for citation_id in list(dict.fromkeys(item for item in citation_ids if item))[:3]:
            citation = citation_map.get(citation_id)
            number = self._citation_number_map.get(citation_id)
            if not citation or not citation.url or not number:
                continue
            title = escape(citation.title or citation.url)
            badges.append(
                f'<a class="cite-badge" href="#citation-{number}" title="{title}">[{number}]</a>'
            )
        if not badges:
            if empty_label:
                return f'<span class="cite-empty">{escape(empty_label)}</span>'
            return ""
        return '<span class="cite-list">' + "".join(badges) + "</span>"

    def format_report(self, report: StrategyReport) -> str:
        lines = [
            "=" * 60,
            f"竞品分析报告: {report.product_name}",
            "=" * 60,
            f"竞品数量: {report.competitor_count}",
            f"定位: {report.overall_positioning or '暂无'}",
            "",
            "行动方案:",
        ]
        for item in report.action_plan:
            lines.append(f"- [{item.priority}] {item.action} ({item.timeline or '时间待定'})")
        if report.coverage_gaps:
            lines.append("")
            lines.append("证据缺口:")
            for gap in report.coverage_gaps:
                lines.append(f"- {gap.competitor}/{gap.topic}: {gap.reason}")
        if report.qa_issues:
            lines.append("")
            lines.append("QA 问题:")
            for issue in report.qa_issues:
                lines.append(f"- {issue.target_agent}: {issue.reason}")
        return "\n".join(lines)

    def format_html_report(
        self,
        report: StrategyReport,
        product_analysis: ProductAnalysis | None = None,
        pricing_analysis: PricingAnalysis | None = None,
        market_analysis: MarketAnalysis | None = None,
        competitor_list: CompetitorList | None = None,
        competitors_data: dict[str, CompetitorData] | None = None,
        timings: dict | None = None,
    ) -> str:
        product_analysis = product_analysis or ProductAnalysis()
        pricing_analysis = pricing_analysis or PricingAnalysis()
        market_analysis = market_analysis or MarketAnalysis()
        competitors_data = competitors_data or {}
        timings = timings or {}

        citation_map = self.build_citation_index(report.citations)
        self._citation_number_map = self._build_citation_number_map(report.citations)
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        payload = {
            "report": report,
            "product_analysis": product_analysis,
            "pricing_analysis": pricing_analysis,
            "market_analysis": market_analysis,
            "competitors_data": competitors_data,
            "timings": timings,
        }

        # 区块1：竞品发现概览
        discovery_html = self._render_discovery_cards(competitor_list)

        # 区块2：逐竞品对比表格（我方 vs 每个竞品）
        competitor_sections_html = self._render_competitor_sections(
            report.product_name,
            product_analysis,
            pricing_analysis,
            market_analysis,
            citation_map,
            competitor_list,
            competitors_data,
        )

        # 区块3：功能对比矩阵（总览）
        feature_matrix_html = self._render_feature_matrix(
            product_analysis.feature_matrix,
            citation_map,
            competitor_list,
            report.product_name,
        )

        # 区块4：定价策略对比
        pricing_html = self._render_pricing_section(pricing_analysis.pricing_comparison, pricing_analysis, citation_map)

        # 区块5：市场格局分析
        market_html = self._render_market_section(market_analysis, citation_map)

        # 区块6：本产品差异化定位
        positioning_html = self._render_positioning_section(
            report,
            product_analysis,
            citation_map,
            competitor_list,
            competitors_data,
        )

        # 区块7：策略建议
        strategy_html = self._render_strategy_section(
            report,
            product_analysis,
            pricing_analysis,
            market_analysis,
            citation_map,
            timings,
        )

        qa_html = self._render_qa_block(report)
        appendix_html = self._render_source_appendix(report.citations)
        snapshot_html = self._render_data_snapshot(payload)

        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(report.product_name)} 竞品分析报告</title>
  <style>
    :root {{
      --bg: #f1f5f9;
      --card: #ffffff;
      --card-soft: #f8fafc;
      --line: #e2e8f0;
      --text: #1e293b;
      --muted: #64748b;
      --blue: #2563eb;
      --blue-dark: #1d4ed8;
      --green: #16a34a;
      --amber: #d97706;
      --red: #dc2626;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    section {{
      background: var(--card);
      border-radius: 16px;
      padding: 28px;
      margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
    }}
    h1, h2, h3, h4 {{ margin-top: 0; }}
    p, li {{ color: #334155; line-height: 1.75; }}
    .hero {{
      background: linear-gradient(135deg, #1e40af, #3b82f6);
      color: #fff;
      border-radius: 20px;
      padding: 36px;
      margin-bottom: 28px;
      box-shadow: 0 10px 30px rgba(37, 99, 235, 0.18);
    }}
    .hero-meta,
    .hero-submeta,
    .hero p {{ color: rgba(255, 255, 255, 0.92); }}
    .hero-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .hero-card {{
      background: rgba(255, 255, 255, 0.14);
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 14px;
      padding: 14px 16px;
    }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }}
    .card-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}
    .compare-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
    }}
    .card-soft {{
      background: var(--card-soft);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
    }}
    .pill {{
      display: inline-block;
      padding: 4px 12px;
      border-radius: 999px;
      font-size: 12px;
      background: #dbeafe;
      color: var(--blue-dark);
      font-weight: 600;
    }}
    .status-pill {{
      display: inline-block;
      padding: 2px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: rgba(255, 255, 255, 0.2);
      color: #fff;
      font-weight: 600;
    }}
    .muted {{ color: var(--muted); }}
    .good {{ color: var(--green); }}
    .warn {{ color: var(--amber); }}
    .bad {{ color: var(--red); }}
    .section-note {{
      margin-top: 10px;
      font-size: 13px;
      color: #475569;
      line-height: 1.7;
    }}
    .divider {{
      text-align: center;
      margin: 32px 0;
      font-size: 20px;
      color: #94a3b8;
      letter-spacing: 1px;
    }}
    .empty-state {{
      padding: 18px;
      border-radius: 12px;
      background: var(--card-soft);
      color: var(--muted);
      font-size: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #fff;
    }}
    th, td {{
      padding: 10px 14px;
      text-align: left;
      border-bottom: 1px solid #eef2f7;
      vertical-align: top;
      font-size: 13px;
    }}
    th {{
      background: var(--card-soft);
      color: #334155;
    }}
    .cell-note {{
      display: block;
      margin-top: 4px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.6;
    }}
    .feature-legend {{
      margin-top: 12px;
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      font-size: 12px;
      color: #64748b;
    }}
    .chip-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
    }}
    .chip-green {{ background: #dcfce7; color: #166534; }}
    .chip-blue {{ background: #dbeafe; color: #1d4ed8; }}
    .timeline-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .cite-list {{
      display: inline-flex;
      gap: 6px;
      margin-left: 6px;
      vertical-align: middle;
      flex-wrap: wrap;
    }}
    .cite-badge {{
      display: inline-block;
      min-width: 24px;
      padding: 1px 7px;
      border-radius: 999px;
      border: 1px solid #bfdbfe;
      background: #eff6ff;
      color: var(--blue-dark);
      font-size: 11px;
      line-height: 1.8;
      text-align: center;
      text-decoration: none;
      font-weight: 700;
    }}
    .cite-badge:hover {{
      background: #dbeafe;
      text-decoration: none;
    }}
    .cite-empty {{
      display: inline-block;
      margin-left: 6px;
      color: var(--amber);
      font-size: 12px;
      vertical-align: middle;
    }}
    .citation-list {{
      display: grid;
      gap: 14px;
    }}
    .citation-card {{
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
      background: var(--card-soft);
    }}
    .citation-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      flex-wrap: wrap;
    }}
    .citation-number {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 999px;
      background: #dbeafe;
      color: var(--blue-dark);
      font-size: 12px;
      font-weight: 700;
    }}
    .citation-meta {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--muted);
      margin-top: 6px;
    }}
    .pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 12px;
      padding: 18px;
      overflow: auto;
      font-size: 12px;
      line-height: 1.7;
    }}
    @media (max-width: 720px) {{
      main {{ padding: 16px; }}
      section {{ padding: 20px; }}
      .hero {{ padding: 24px; }}
      th, td {{ padding: 8px 10px; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap;">
        <div>
          <h1 style="font-size:28px;font-weight:700;margin-bottom:8px;">智能竞品分析报告</h1>
          <div class="hero-submeta" style="font-size:20px;margin-bottom:10px;">{escape(report.product_name)}</div>
          <div class="hero-meta" style="font-size:14px;">分析竞品 {report.competitor_count} 个 · 生成时间 {generated_at}</div>
        </div>
        <div>
          <span class="status-pill">{escape(report.status or "success")}</span>
        </div>
      </div>
      <p style="margin-top:16px;font-size:15px;">{escape(report.overall_positioning or "暂无整体定位结论。")}</p>
      <div class="hero-grid">
        <div class="hero-card">
          <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">核心差异化</div>
          <div>{escape(str(report.differentiation_strategy.get("core_differentiator", "待补充")))}</div>
        </div>
        <div class="hero-card">
          <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">报告摘要</div>
          <div>{escape(report.summary or "暂无")}</div>
        </div>
      </div>
    </section>

    {discovery_html}
    {competitor_sections_html}
    {feature_matrix_html}
    {pricing_html}
    {market_html}
    {positioning_html}

    <div class="divider">──────── 策略建议 ────────</div>

    {strategy_html}
    {qa_html}

    <section>
      <div class="section-title">
        <h2>来源索引</h2>
        <span class="pill">编号脚注</span>
      </div>
      {appendix_html}
    </section>

    {snapshot_html}
  </main>
</body>
</html>"""

    def _render_discovery_cards(self, competitor_list: CompetitorList | None) -> str:
        # 区块1：竞品发现概览
        if not competitor_list or not competitor_list.competitors:
            return (
                "<section>"
                '<div class="section-title"><h2>🔎 竞品发现概览</h2><span class="pill">区块 1</span></div>'
                f"{self._render_empty_state('当前没有可展示的竞品列表。')}"
                "</section>"
            )

        cards = []
        for competitor in competitor_list.competitors:
            relevance = {
                "HIGH": ("直接竞品", "#ef4444"),
                "MEDIUM": ("间接竞品", "#f59e0b"),
                "LOW": ("潜在竞品", "#94a3b8"),
            }.get(competitor.relevance, ("竞品", "#94a3b8"))
            cards.append(
                '<div class="card">'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:12px;">'
                f"<strong>{escape(competitor.name)}</strong>"
                f'<span style="background:{relevance[1]};color:#fff;padding:2px 10px;border-radius:12px;font-size:11px;">{escape(relevance[0])}</span>'
                "</div>"
                f'<div class="muted">{escape(competitor.brief or "暂无简介")}</div>'
                "</div>"
            )

        return (
            "<section>"
            '<div class="section-title"><h2>🔎 竞品发现概览</h2><span class="pill">区块 1</span></div>'
            '<div class="card-grid">' + "".join(cards) + "</div>"
            "</section>"
        )

    def _render_competitor_sections(
        self,
        product_name: str,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        citation_map: dict[str, Citation],
        competitor_list: CompetitorList | None,
        competitors_data: dict[str, CompetitorData],
    ) -> str:
        # 区块2：逐竞品对比表格（我方 vs 每个竞品）
        competitor_names = self._collect_competitor_names(
            product_name,
            product_analysis,
            pricing_analysis,
            market_analysis,
            competitor_list,
        )
        competitor_names = [name for name in competitor_names if name != product_name]

        if not competitor_names:
            return (
                "<section>"
                '<div class="section-title"><h2>🆚 逐竞品对比</h2><span class="pill">区块 2</span></div>'
                f"{self._render_empty_state('当前没有可用于逐竞品对比的数据。')}"
                "</section>"
            )

        sections = []
        for competitor_name in competitor_names:
            rows = []
            for item in product_analysis.feature_matrix[:12]:
                product_value = self._find_matrix_value(item.values, product_name)
                competitor_value = self._find_matrix_value(item.values, competitor_name)
                competitor_citations = self._feature_citation_ids_for(item, competitor_name)
                rows.append(
                    "<tr>"
                    f"<td>{escape(item.feature)}{self.render_citation_links(competitor_citations, citation_map, '（暂无直接引用）')}</td>"
                    f'<td style="text-align:center;">{escape(self._feature_value_text(product_value))}</td>'
                    f'<td style="text-align:center;">{escape(self._feature_value_text(competitor_value))}</td>'
                    "</tr>"
                )

            pricing_item = self._find_pricing_item(pricing_analysis.pricing_comparison, competitor_name)
            if pricing_item:
                rows.append(
                    "<tr>"
                    f"<td>定价策略{self.render_citation_links(pricing_item.citations, citation_map, '（暂无直接引用）')}</td>"
                    "<td>—</td>"
                    f"<td>{escape(pricing_item.free_tier or pricing_item.entry_offer or '暂无')}<span class=\"cell-note\">付费：{escape(pricing_item.paid_tier or '暂无')} · 升级：{escape(pricing_item.upgrade_trigger or '暂无')}</span></td>"
                    "</tr>"
                )

            market_item = self._find_market_item(market_analysis.market_share_data, competitor_name)
            if market_item:
                rows.append(
                    "<tr>"
                    f"<td>市场位置{self.render_citation_links(market_item.citations, citation_map, '（暂无直接引用）')}</td>"
                    "<td>—</td>"
                    f"<td>{escape(market_item.share_estimate or market_item.market_position or '暂无')}<span class=\"cell-note\">趋势：{escape(market_item.trend or '待补充')} · 位置：{escape(market_item.market_position or '待补充')}</span></td>"
                    "</tr>"
                )

            if not rows:
                rows.append(
                    "<tr><td colspan=\"3\">暂无可展示的逐竞品对比数据。</td></tr>"
                )

            advantage = self._find_advantage(product_analysis.competitive_advantages, competitor_name)
            competitor_data = self._find_competitor_data(competitors_data, competitor_name)
            product_strength = self._competitor_product_strength(competitor_data, advantage)
            product_weakness = self._competitor_product_weakness(competitor_data, advantage)
            compare_cards = [
                self._render_compare_card(
                    "我方优势",
                    advantage.our_advantage if advantage else "",
                    "good",
                    advantage.citations if advantage else [],
                    citation_map,
                ),
                self._render_compare_card(
                    "对方优势",
                    advantage.their_advantage or advantage.their_strength if advantage else "",
                    "bad",
                    advantage.citations if advantage else [],
                    citation_map,
                ),
                self._render_compare_card(
                    "对方长处",
                    product_strength,
                    "good",
                    advantage.citations if advantage else [],
                    citation_map,
                ),
                self._render_compare_card(
                    "对方短板",
                    product_weakness,
                    "warn",
                    advantage.citations if advantage else [],
                    citation_map,
                ),
                self._render_compare_card(
                    "渠道优势",
                    self._competitor_channel_strength(competitor_data),
                    "muted",
                    advantage.citations if advantage else [],
                    citation_map,
                ),
                self._render_compare_card(
                    "口碑信号",
                    self._competitor_reputation_signal(competitor_data),
                    "muted",
                    advantage.citations if advantage else [],
                    citation_map,
                ),
                self._render_compare_card(
                    "应对动作",
                    advantage.recommended_countermove if advantage else "",
                    "muted",
                    advantage.citations if advantage else [],
                    citation_map,
                ),
            ]
            evidence_html = self._render_competitor_evidence_card(competitor_data)

            sections.append(
                "<section>"
                '<div class="section-title">'
                f"<h2>🆚 {escape(product_name)} vs {escape(competitor_name)}</h2>"
                '<span class="pill">区块 2</span>'
                "</div>"
                '<div style="overflow-x:auto;">'
                "<table><thead><tr>"
                '<th style="width:180px;">维度</th>'
                f"<th>{escape(product_name)}</th>"
                f"<th>{escape(competitor_name)}</th>"
                "</tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table></div>"
                + evidence_html
                + '<div class="compare-grid">' + "".join(compare_cards) + "</div>"
                "</section>"
            )

        return "".join(sections)

    def _render_feature_matrix(
        self,
        feature_matrix: list[FeatureComparison],
        citation_map: dict[str, Citation],
        competitor_list: CompetitorList | None,
        product_name: str,
    ) -> str:
        # 区块3：功能对比矩阵（总览）
        if not feature_matrix:
            return (
                "<section>"
                '<div class="section-title"><h2>🧩 功能对比矩阵</h2><span class="pill">区块 3</span></div>'
                f"{self._render_empty_state('当前没有功能矩阵数据。')}"
                "</section>"
            )

        competitor_names = [product_name]
        if competitor_list and competitor_list.competitors:
            competitor_names.extend(competitor.name for competitor in competitor_list.competitors)
        else:
            competitor_names.extend(
                name
                for item in feature_matrix
                for name in item.values
            )
        competitor_names = list(dict.fromkeys(name for name in competitor_names if name))

        header_cells = "".join(f"<th>{escape(name)}</th>" for name in competitor_names)
        rows = []
        for item in feature_matrix:
            cells = []
            for name in competitor_names:
                cell_citations = self._feature_citation_ids_for(item, name)
                cells.append(
                    f'<td style="text-align:center;">{escape(self._feature_value_text(self._find_matrix_value(item.values, name)))}{self.render_citation_links(cell_citations, citation_map)}</td>'
                )
            supported_count = sum(
                1 for name in competitor_names if self._is_supported(self._find_matrix_value(item.values, name))
            )
            rows.append(
                "<tr>"
                f"<td>{escape(item.feature)}</td>"
                + "".join(cells)
                + f"<td>{supported_count}</td>"
                "</tr>"
            )

        return (
            "<section>"
            '<div class="section-title"><h2>🧩 功能对比矩阵</h2><span class="pill">区块 3</span></div>'
            '<div style="overflow-x:auto;">'
            "<table><thead><tr><th>功能</th>"
            + header_cells
            + "<th>覆盖数</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
            '<div class="feature-legend"><span>✅ 支持</span><span>🟡 部分支持</span><span>❌ 不支持</span><span>— 未知</span></div>'
            "</section>"
        )

    def _render_pricing_section(
        self,
        pricing_items: list[PricingItem],
        pricing_analysis: PricingAnalysis,
        citation_map: dict[str, Citation],
    ) -> str:
        # 区块4：定价策略对比
        if not pricing_items and not pricing_analysis.pricing_strategy_analysis and not pricing_analysis.value_ranking:
            return (
                "<section>"
                '<div class="section-title"><h2>💰 定价策略对比</h2><span class="pill">区块 4</span></div>'
                f"{self._render_empty_state('当前没有定价分析数据。')}"
                "</section>"
            )

        rows = []
        for item in pricing_items:
            rows.append(
                "<tr>"
                f"<td>{escape(item.competitor)}{self.render_citation_links(item.citations, citation_map, '（暂无直接引用）')}</td>"
                f"<td>{escape(item.free_tier or '暂无')}<span class=\"cell-note\">入口：{escape(item.entry_offer or '暂无')}</span></td>"
                f"<td>{escape(item.paid_tier or '暂无')}<span class=\"cell-note\">升级：{escape(item.upgrade_trigger or '暂无')}</span></td>"
                f"<td>{escape(item.pricing_model or item.billing_unit or '暂无')}<span class=\"cell-note\">风险：{escape(item.pricing_risk or '未见明显风险')}</span></td>"
                "</tr>"
            )

        ranking_html = ""
        if pricing_analysis.value_ranking:
            rank_items = "".join(
                f'<span class="chip chip-green">{escape(name)}</span>'
                for name in pricing_analysis.value_ranking
            )
            ranking_html = (
                '<div class="card-soft" style="margin-top:16px;">'
                "<strong>性价比排序：</strong>"
                f'<div class="chip-row">{rank_items}</div>'
                "</div>"
            )

        analysis_citations = self._take_conclusion_citations(pricing_analysis.conclusions, limit=3)
        analysis_note = ""
        if pricing_analysis.pricing_strategy_analysis:
            analysis_note = (
                '<div class="card-soft" style="margin-top:16px;">'
                f"<strong>策略分析：</strong>{escape(pricing_analysis.pricing_strategy_analysis)}"
                f"{self.render_citation_links(analysis_citations, citation_map)}"
                "</div>"
            )

        return (
            "<section>"
            '<div class="section-title"><h2>💰 定价策略对比</h2><span class="pill">区块 4</span></div>'
            + (
                '<div style="overflow-x:auto;">'
                "<table><thead><tr>"
                "<th>竞品</th><th>免费层</th><th>付费层</th><th>定价模式</th>"
                "</tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table></div>"
                if rows
                else self._render_empty_state("当前没有竞品级别的定价明细。")
            )
            + ranking_html
            + analysis_note
            + "</section>"
        )

    def _render_market_section(self, market_analysis: MarketAnalysis, citation_map: dict[str, Citation]) -> str:
        # 区块5：市场格局分析
        has_market_data = any(
            [
                market_analysis.market_share_data,
                market_analysis.user_reputation,
                market_analysis.user_personas,
                market_analysis.growth_trends,
                market_analysis.channel_analysis,
            ]
        )
        if not has_market_data:
            return (
                "<section>"
                '<div class="section-title"><h2>📈 市场格局分析</h2><span class="pill">区块 5</span></div>'
                f"{self._render_empty_state('当前没有市场分析数据。')}"
                "</section>"
            )

        max_share = 0.0
        share_data: list[tuple[MarketShareItem, float]] = []
        for item in market_analysis.market_share_data:
            share_num = self._extract_share_number(item.share_estimate)
            max_share = max(max_share, share_num)
            share_data.append((item, share_num))
        share_data.sort(key=lambda value: value[1], reverse=True)

        share_bars = ""
        for item, share_num in share_data:
            bar_width = (share_num / max_share * 100) if max_share > 0 else 50
            bar_width = max(bar_width, 5)
            detail_parts = [part for part in [item.market_position, item.growth_signal, item.channel_motion] if part]
            share_bars += (
                '<div style="margin-bottom:14px;">'
                '<div style="display:flex;align-items:center;">'
                f'<div style="width:120px;font-size:14px;font-weight:500;flex-shrink:0;">{escape(item.competitor)}</div>'
                '<div style="flex:1;margin:0 12px;">'
                '<div style="background:#f1f5f9;border-radius:6px;height:28px;overflow:hidden;">'
                f'<div style="background:linear-gradient(90deg,#3b82f6,#6366f1);height:100%;width:{bar_width:.1f}%;border-radius:6px;display:flex;align-items:center;padding:0 10px;">'
                f'<span style="color:#fff;font-size:12px;font-weight:600;white-space:nowrap;">{escape(item.share_estimate or "待补充")}</span>'
                "</div></div></div>"
                f'<div style="width:80px;text-align:right;flex-shrink:0;">{self._render_trend_badge(item.trend)}</div>'
                "</div>"
                + (
                    f'<div class="section-note" style="margin-left:132px;">{escape("；".join(detail_parts))}{self.render_citation_links(item.citations, citation_map, "（暂无直接引用）")}</div>'
                    if detail_parts or item.citations
                    else ""
                )
                + "</div>"
            )

        reputation_html = ""
        if market_analysis.user_reputation:
            rep_cards = []
            for name, reputation in market_analysis.user_reputation.items():
                kw_tags = "".join(
                    f'<span class="chip chip-blue">{escape(keyword)}</span>'
                    for keyword in (reputation.keywords or [])[:5]
                )
                kw_block = kw_tags or '<span class="muted">暂无关键词</span>'
                rep_cards.append(
                    '<div class="card-soft">'
                    f'<div style="font-weight:600;font-size:14px;margin-bottom:6px;">{escape(name)}</div>'
                    f'<div style="font-size:20px;font-weight:700;color:#f59e0b;margin-bottom:4px;">{escape(reputation.score) if reputation.score else "—"}</div>'
                    f'<div class="chip-row">{kw_block}</div>'
                    f"{self.render_citation_links(reputation.citations, citation_map)}"
                    "</div>"
                )
            reputation_html = (
                '<div style="margin-top:20px;">'
                '<h3 style="font-size:16px;color:#475569;margin-bottom:12px;">👥 用户口碑</h3>'
                '<div class="card-grid">' + "".join(rep_cards) + "</div>"
                "</div>"
            )

        persona_html = ""
        if market_analysis.user_personas:
            persona_cards = []
            for persona in market_analysis.user_personas:
                persona_cards.append(
                    '<div class="card">'
                    f"<h3>{escape(persona.name)}</h3>"
                    f'<div class="muted">用户分层：{escape(persona.segment or "未知")}</div>'
                    f"<p>{escape(persona.persona_summary or '当前画像描述有限。')}</p>"
                    f"<p>需求：{escape(self._join_text(persona.needs))}</p>"
                    f"<p>抱怨：{escape(self._join_text(persona.complaints))}</p>"
                    f"<p>偏好渠道：{escape(self._join_text(persona.preferred_channels))}</p>"
                    f"{self.render_citation_links(persona.citations, citation_map)}"
                    "</div>"
                )
            persona_html = (
                '<div style="margin-top:20px;">'
                '<h3 style="font-size:16px;color:#475569;margin-bottom:12px;">👤 用户画像</h3>'
                '<div class="card-grid">' + "".join(persona_cards) + "</div>"
                "</div>"
            )

        notes_html = ""
        if market_analysis.growth_trends:
            notes_html += (
                '<div class="card-soft" style="margin-top:16px;">'
                f"<strong>增长趋势：</strong>{escape(market_analysis.growth_trends)}"
                f"{self.render_citation_links(self._take_conclusion_citations(market_analysis.conclusions, limit=3), citation_map)}"
                "</div>"
            )
        if market_analysis.channel_analysis:
            notes_html += (
                '<div class="card-soft" style="margin-top:10px;">'
                f"<strong>渠道分析：</strong>{escape(market_analysis.channel_analysis)}"
                "</div>"
            )

        return (
            "<section>"
            '<div class="section-title"><h2>📈 市场格局分析</h2><span class="pill">区块 5</span></div>'
            + (share_bars or self._render_empty_state("当前没有可展示的市场份额数据。"))
            + reputation_html
            + persona_html
            + notes_html
            + "</section>"
        )

    def _render_positioning_section(
        self,
        report: StrategyReport,
        product_analysis: ProductAnalysis,
        citation_map: dict[str, Citation],
        competitor_list: CompetitorList | None,
        competitors_data: dict[str, CompetitorData],
    ) -> str:
        # 区块6：本产品差异化定位
        competitor_names = self._collect_competitor_names(
            report.product_name,
            product_analysis,
            PricingAnalysis(),
            MarketAnalysis(),
            competitor_list,
        )
        competitor_names = [name for name in competitor_names if name != report.product_name]

        unique_features: list[str] = []
        advantage_features: list[str] = []
        feature_citation_map: dict[str, list[str]] = {}
        for feature in product_analysis.feature_matrix:
            feature_citation_map[feature.feature] = feature.citations
            our_value = self._find_matrix_value(feature.values, report.product_name)
            if not self._is_supported(our_value):
                continue
            competitor_supported = [
                self._is_supported(self._find_matrix_value(feature.values, name))
                for name in competitor_names
            ]
            if competitor_names and not any(competitor_supported):
                unique_features.append(feature.feature)
            elif competitor_names and competitor_supported.count(False) > len(competitor_names) / 2:
                advantage_features.append(feature.feature)

        unique_html = ""
        if unique_features:
            unique_html = (
                '<div style="margin-bottom:18px;">'
                '<div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:8px;">独占优势（竞品均不具备）</div>'
                '<div class="chip-row">'
                + "".join(
                    f'<span class="chip chip-green">{escape(name)}{self.render_citation_links(feature_citation_map.get(name, []), citation_map)}</span>'
                    for name in unique_features
                )
                + "</div></div>"
            )

        advantage_html = ""
        if advantage_features:
            advantage_html = (
                '<div style="margin-bottom:18px;">'
                '<div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:8px;">领先优势（多数竞品不具备）</div>'
                '<div class="chip-row">'
                + "".join(
                    f'<span class="chip chip-blue">{escape(name)}{self.render_citation_links(feature_citation_map.get(name, []), citation_map)}</span>'
                    for name in advantage_features
                )
                + "</div></div>"
            )

        supporting_points = report.differentiation_strategy.get("supporting_points", []) or product_analysis.differentiation_points
        point_items = "".join(f"<li>{escape(point)}</li>" for point in supporting_points[:8])
        diff_points_html = (
            '<div style="margin-bottom:18px;">'
            '<div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:8px;">核心差异化亮点</div>'
            + (f"<ul>{point_items}</ul>" if point_items else '<div class="muted">暂无可展示的差异化亮点。</div>')
            + "</div>"
        )

        per_competitor_positioning = ""
        if product_analysis.competitive_advantages:
            cards = []
            for advantage in product_analysis.competitive_advantages:
                competitor_data = self._find_competitor_data(competitors_data, advantage.competitor)
                cards.append(
                    '<div class="card-soft" style="margin-bottom:12px;">'
                    f'<div style="font-size:13px;font-weight:700;margin-bottom:8px;">vs {escape(advantage.competitor)}</div>'
                    f'<div class="good" style="margin-bottom:6px;"><strong>我方胜出：</strong>{escape(advantage.our_advantage or "待补充")}</div>'
                    f'<div class="bad" style="margin-bottom:6px;"><strong>产品长处：</strong>{escape(self._competitor_product_strength(competitor_data, advantage) or "待补充")}</div>'
                    f'<div class="section-note"><strong>渠道优势：</strong>{escape(self._competitor_channel_strength(competitor_data) or "待补充")}</div>'
                    f'<div class="section-note"><strong>口碑信号：</strong>{escape(self._competitor_reputation_signal(competitor_data) or "待补充")}</div>'
                    f'<div class="section-note"><strong>应对动作：</strong>{escape(advantage.recommended_countermove or "待补充")}{self.render_citation_links(advantage.citations, citation_map, "（暂无直接引用）")}</div>'
                    "</div>"
                )
            per_competitor_positioning = (
                '<div style="margin-top:20px;">'
                '<div style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:12px;">逐竞品差异化锚点</div>'
                + "".join(cards)
                + "</div>"
            )

        section_citations = self._collect_citation_ids(
            self._take_conclusion_citations(product_analysis.conclusions, limit=3),
            *[advantage.citations for advantage in product_analysis.competitive_advantages],
        )[:3]

        return (
            "<section>"
            '<div class="section-title"><h2>🧭 本产品差异化定位</h2><span class="pill">区块 6</span></div>'
            '<div style="background:linear-gradient(135deg,#1e293b,#334155);border-radius:12px;padding:20px;margin-bottom:20px;color:#fff;">'
            '<div style="font-size:12px;opacity:0.75;margin-bottom:6px;">定位声明</div>'
            f'<div style="font-size:16px;font-weight:600;line-height:1.6;">{escape(report.overall_positioning or "暂无整体定位结论。")}</div>'
            f"{self.render_citation_links(section_citations, citation_map)}"
            "</div>"
            + unique_html
            + advantage_html
            + diff_points_html
            + (
                '<div class="card-soft" style="margin-bottom:16px;">'
                f"<strong>核心差异：</strong>{escape(str(report.differentiation_strategy.get('core_differentiator', '待补充')))}"
                "</div>"
            )
            + per_competitor_positioning
            + "</section>"
        )

    def _render_strategy_section(
        self,
        report: StrategyReport,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        citation_map: dict[str, Citation],
        timings: dict[str, Any],
    ) -> str:
        # 区块7：策略建议
        diff_strategy_html = ""
        if report.differentiation_strategy:
            points_html = "".join(
                f"<li>{escape(point)}</li>"
                for point in report.differentiation_strategy.get("supporting_points", [])
            )
            diff_strategy_html = (
                '<div class="card-soft" style="margin-bottom:18px;">'
                "<h3>差异化策略</h3>"
                f"<p><strong>核心差异：</strong>{escape(str(report.differentiation_strategy.get('core_differentiator', '待补充')))}</p>"
                + (f"<ul>{points_html}</ul>" if points_html else "")
                + "</div>"
            )

        action_cards = []
        for item in report.action_plan:
            action_cards.append(
                '<div class="card">'
                '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">'
                f"{self._priority_badge(item.priority)}"
                f"<strong style=\"font-size:15px;\">{escape(item.action)}</strong>"
                f"{self.render_citation_links(item.citations, citation_map)}"
                "</div>"
                + (
                    f'<div class="muted" style="margin-bottom:4px;">时间：{escape(item.timeline)}</div>'
                    if item.timeline
                    else ""
                )
                + (
                    f'<div class="section-note">预期影响：{escape(item.expected_impact)}</div>'
                    if item.expected_impact
                    else ""
                )
                + "</div>"
            )

        risk_citations = self._collect_citation_ids(
            self._take_conclusion_citations(product_analysis.conclusions, limit=2),
            self._take_conclusion_citations(pricing_analysis.conclusions, limit=2),
            self._take_conclusion_citations(market_analysis.conclusions, limit=2),
        )[:3]
        risk_items = "".join(f"<li>{escape(item)}</li>" for item in self._sentence_to_bullets(report.risk_assessment))
        risk_html = (
            '<div class="card-soft" style="margin-top:18px;">'
            "<h3>风险评估</h3>"
            f"<ul>{risk_items}</ul>"
            f"{self.render_citation_links(risk_citations, citation_map)}"
            "</div>"
        )
        if report.coverage_gaps:
            risk_html += (
                '<div class="card-soft" style="margin-top:12px;">'
                "<h4>证据缺口</h4><ul>"
                + "".join(
                    f"<li>{escape(gap.competitor)} / {escape(gap.topic)}：{escape(gap.reason)}</li>"
                    for gap in report.coverage_gaps
                )
                + "</ul></div>"
            )

        product_citations = self._take_conclusion_citations(product_analysis.conclusions, limit=3)
        pricing_citations = self._take_conclusion_citations(pricing_analysis.conclusions, limit=3)
        market_citations = self._take_conclusion_citations(market_analysis.conclusions, limit=3)
        summary_cards = (
            '<div class="summary-grid" style="margin-top:18px;">'
            f'<div class="card"><h3>产品分析</h3>{self._render_paragraphs(report.product_analysis_summary)}{self.render_citation_links(product_citations, citation_map)}</div>'
            f'<div class="card"><h3>定价分析</h3>{self._render_paragraphs(report.pricing_analysis_summary)}{self.render_citation_links(pricing_citations, citation_map)}</div>'
            f'<div class="card"><h3>市场分析</h3>{self._render_paragraphs(report.market_analysis_summary)}{self.render_citation_links(market_citations, citation_map)}</div>'
            "</div>"
        )

        overall_citations = self._collect_citation_ids(product_citations, pricing_citations, market_citations)[:3]
        overall_summary_html = (
            '<div style="background:linear-gradient(135deg,#1e3a5f,#1e293b);border-radius:16px;padding:24px;margin-top:18px;color:#fff;">'
            "<h3 style=\"color:#fff;\">综合建议</h3>"
            f'<p style="color:rgba(255,255,255,0.92);">{escape(report.summary or "暂无综合建议。")}</p>'
            f"{self.render_citation_links(overall_citations, citation_map)}"
            "</div>"
        )

        timing_html = ""
        timing_rows = []
        labels = {
            "discovery": "竞品发现",
            "collection": "数据采集",
            "parallel_analysis": "并行分析",
            "strategy": "策略建议",
            "total": "总耗时",
        }
        for key, value in timings.items():
            if not isinstance(value, (int, float)):
                continue
            label = labels.get(str(key), str(key))
            timing_rows.append(
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;"><span>{escape(label)}</span><span>{float(value):.2f}s</span></div>'
            )
        if timing_rows:
            timing_html = (
                '<div class="card-soft" style="margin-top:18px;">'
                "<h3>耗时统计</h3>"
                + "".join(timing_rows)
                + "</div>"
            )

        return (
            "<section>"
            '<div class="section-title"><h2>🧠 策略建议</h2><span class="pill">区块 7</span></div>'
            + diff_strategy_html
            + (
                '<div class="timeline-grid">'
                + "".join(action_cards)
                + "</div>"
                if action_cards
                else self._render_empty_state("当前没有行动方案。")
            )
            + risk_html
            + summary_cards
            + overall_summary_html
            + timing_html
            + "</section>"
        )

    def _render_qa_block(self, report: StrategyReport) -> str:
        if not report.qa_issues:
            return ""
        issues = "".join(
            '<div class="card-soft" style="margin-bottom:12px;">'
            f"<strong>{escape(issue.target_agent)}</strong>"
            f"<p>{escape(issue.reason)}</p>"
            f'<div class="muted">修复建议：{escape(issue.required_fix)}</div>'
            "</div>"
            for issue in report.qa_issues
        )
        return (
            "<section>"
            '<div class="section-title"><h2>QA 复核记录</h2><span class="pill">附加区块</span></div>'
            + issues
            + "</section>"
        )

    def _render_source_appendix(self, citations: list[Citation]) -> str:
        valid_citations = [citation for citation in citations if citation.url and citation.id in self._citation_number_map]
        if not valid_citations:
            return self._render_empty_state("当前没有可展示的来源。")

        cards = []
        quality_labels = {
            "official": "官方",
            "media": "媒体",
            "community": "社区",
            "complaint": "投诉",
            "aggregator": "聚合",
            "low_quality": "低质量",
        }
        for citation in valid_citations:
            number = self._citation_number_map[citation.id]
            quality = quality_labels.get(citation.source_quality, citation.source_quality or "未知")
            domain = self._extract_domain(citation.url)
            cards.append(
                f'<div class="citation-card" id="citation-{number}">'
                '<div class="citation-head">'
                f'<span class="citation-number">[{number}]</span>'
                f'<a href="{escape(citation.url)}" target="_blank" rel="noopener noreferrer">{escape(citation.title or citation.url)}</a>'
                "</div>"
                '<div class="citation-meta">'
                f"<span>质量：{escape(quality)}</span>"
                f"<span>域名：{escape(domain)}</span>"
                f"<span>置信度：{citation.confidence:.2f}</span>"
                "</div>"
                f'<div class="section-note">{escape(citation.snippet[:220] or "暂无摘要。")}</div>'
                "</div>"
            )
        return '<div class="citation-list">' + "".join(cards) + "</div>"

    def _render_data_snapshot(self, payload: dict[str, Any]) -> str:
        return (
            "<section>"
            '<div class="section-title"><h2>结构化数据快照</h2><span class="pill">附加区块</span></div>'
            f'<div class="pre">{escape(json.dumps(payload, ensure_ascii=False, default=lambda obj: getattr(obj, "__dict__", str(obj)), indent=2))}</div>'
            "</section>"
        )

    @staticmethod
    def _render_empty_state(text: str) -> str:
        return f'<div class="empty-state">{escape(text)}</div>'

    @staticmethod
    def _render_paragraphs(text: str) -> str:
        chunks = [chunk.strip() for chunk in str(text or "").split("\n\n") if chunk.strip()]
        if not chunks:
            return "<p>暂无摘要。</p>"
        return "".join(f"<p>{escape(chunk)}</p>" for chunk in chunks)

    @staticmethod
    def _priority_badge(priority: str) -> str:
        colors = {"P0": "#ef4444", "P1": "#f59e0b", "P2": "#22c55e", "P3": "#94a3b8"}
        bg = colors.get(priority, "#94a3b8")
        return (
            f'<span style="background:{bg};color:#fff;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;">'
            f"{escape(priority or 'P2')}</span>"
        )

    @staticmethod
    def _feature_value_text(value: str) -> str:
        raw = str(value or "").strip()
        mapping = {
            "supported": "✅",
            "partial": "🟡",
            "unknown": "—",
            "✅": "✅",
            "🟡": "🟡",
            "❌": "❌",
            "支持": "✅",
            "完整支持": "✅",
            "有": "✅",
            "部分支持": "🟡",
            "部分": "🟡",
            "不支持": "❌",
            "无": "❌",
            "": "—",
        }
        return mapping.get(raw, raw or "—")

    @staticmethod
    def _is_supported(value: str) -> bool:
        return StrategyAgent._feature_value_text(value) == "✅"

    @staticmethod
    def _find_matrix_value(values: dict[str, str], target_name: str) -> str:
        if not values:
            return ""
        if target_name in values:
            return values[target_name]
        for key, value in values.items():
            if target_name and (key.startswith(target_name) or target_name in key or key in target_name):
                return value
        return ""

    @staticmethod
    def _find_pricing_item(pricing_items: list[PricingItem], competitor_name: str) -> PricingItem | None:
        for item in pricing_items:
            if item.competitor == competitor_name:
                return item
        return None

    @staticmethod
    def _find_market_item(market_items: list[MarketShareItem], competitor_name: str) -> MarketShareItem | None:
        for item in market_items:
            if item.competitor == competitor_name:
                return item
        return None

    @staticmethod
    def _find_advantage(advantages: list[CompetitiveAdvantage], competitor_name: str) -> CompetitiveAdvantage | None:
        for item in advantages:
            if item.competitor == competitor_name:
                return item
        return None

    @staticmethod
    def _find_competitor_data(
        competitors_data: dict[str, CompetitorData],
        competitor_name: str,
    ) -> CompetitorData | None:
        if competitor_name in competitors_data:
            return competitors_data[competitor_name]
        for key, value in competitors_data.items():
            if competitor_name in key or key in competitor_name:
                return value
        return None

    @staticmethod
    def _extract_share_number(share_text: str) -> float:
        match = re.search(r"([\d.]+)", share_text or "")
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0

    @staticmethod
    def _render_trend_badge(trend: str) -> str:
        raw = (trend or "").strip()
        lowered = raw.lower()
        if any(token in lowered for token in ("up", "grow", "increase", "增长", "上升", "提升", "走强")):
            return '<span class="good" style="font-weight:600;">▲ 上升</span>'
        if any(token in lowered for token in ("down", "decline", "drop", "下降", "下滑", "走弱")):
            return '<span class="bad" style="font-weight:600;">▼ 下滑</span>'
        return f'<span class="muted" style="font-weight:600;">● {escape(raw or "持平")}</span>'

    @staticmethod
    def _competitor_product_strength(
        competitor_data: CompetitorData | None,
        advantage: CompetitiveAdvantage | None,
    ) -> str:
        if competitor_data and competitor_data.product_strengths:
            return competitor_data.product_strengths
        return (advantage.their_strength if advantage else "") or ""

    @staticmethod
    def _competitor_product_weakness(
        competitor_data: CompetitorData | None,
        advantage: CompetitiveAdvantage | None,
    ) -> str:
        if competitor_data and competitor_data.product_weaknesses:
            return competitor_data.product_weaknesses
        return (advantage.their_weakness if advantage else "") or ""

    @staticmethod
    def _competitor_channel_strength(competitor_data: CompetitorData | None) -> str:
        if not competitor_data:
            return ""
        return competitor_data.channel_strengths or ""

    @staticmethod
    def _competitor_reputation_signal(competitor_data: CompetitorData | None) -> str:
        if not competitor_data:
            return ""
        return competitor_data.reputation_strengths or competitor_data.reputation_weaknesses or ""

    def _render_compare_card(
        self,
        title: str,
        text: str,
        tone: str,
        citation_ids: list[str],
        citation_map: dict[str, Citation],
    ) -> str:
        tone_class = {"good": "good", "warn": "warn", "bad": "bad"}.get(tone, "muted")
        return (
            '<div class="card-soft">'
            f'<div class="{tone_class}" style="font-weight:600;margin-bottom:8px;">{escape(title)}</div>'
            f"<div>{escape(text or '暂无')}</div>"
            f"{self.render_citation_links(citation_ids, citation_map, '（暂无直接引用）')}"
            "</div>"
        )

    @staticmethod
    def _render_competitor_evidence_card(competitor_data: CompetitorData | None) -> str:
        if not competitor_data:
            return ""
        rows = [
            ("综合证据画像", competitor_data.evidence_digest),
            ("证据质量提示", competitor_data.evidence_quality_notes),
            ("未消解冲突", competitor_data.unresolved_conflicts),
        ]
        body = "".join(
            '<div class="section-note" style="margin-top:8px;">'
            f"<strong>{escape(label)}：</strong>{escape(value)}"
            "</div>"
            for label, value in rows
            if value
        )
        if not body:
            return ""
        return (
            '<div class="card-soft" style="margin:14px 0;">'
            '<div style="font-size:14px;font-weight:700;margin-bottom:8px;">Agent 证据综合</div>'
            f"{body}"
            "</div>"
        )

    def _collect_competitor_names(
        self,
        product_name: str,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        competitor_list: CompetitorList | None,
    ) -> list[str]:
        names = [product_name]
        if competitor_list and competitor_list.competitors:
            names.extend(competitor.name for competitor in competitor_list.competitors)
        names.extend(item.competitor for item in pricing_analysis.pricing_comparison)
        names.extend(item.competitor for item in market_analysis.market_share_data)
        names.extend(item.competitor for item in product_analysis.competitive_advantages)
        for feature in product_analysis.feature_matrix:
            names.extend(feature.values.keys())
        return list(dict.fromkeys(name for name in names if name))

    @staticmethod
    def _take_conclusion_citations(conclusions: list, limit: int = 3) -> list[str]:
        ids: list[str] = []
        for item in conclusions:
            ids.extend(item.citations)
            if len(ids) >= limit:
                break
        return list(dict.fromkeys(item for item in ids if item))[:limit]

    @staticmethod
    def _collect_citation_ids(*groups: list[str]) -> list[str]:
        ids: list[str] = []
        for group in groups:
            ids.extend(group)
        return list(dict.fromkeys(item for item in ids if item))

    @staticmethod
    def _feature_citation_ids_for(feature: FeatureComparison, competitor_name: str) -> list[str]:
        competitor_citations = getattr(feature, "competitor_citations", {}) or {}
        if competitor_name in competitor_citations:
            return list(dict.fromkeys(item for item in competitor_citations.get(competitor_name, []) if item))
        return feature.citations if len(feature.values) <= 2 else []

    @staticmethod
    def _sentence_to_bullets(text: str) -> list[str]:
        normalized = str(text or "").replace("。", "|").replace("\n", "|")
        parts = [part.strip(" ；;|") for part in normalized.split("|") if part.strip(" ；;|")]
        return parts or ["暂无风险说明。"]

    @staticmethod
    def _join_text(values: list[str]) -> str:
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        return "；".join(cleaned) if cleaned else "暂无"

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            return urlparse(url).netloc or url
        except ValueError:
            return url
