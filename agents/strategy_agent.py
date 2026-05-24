# -*- coding: utf-8 -*-
"""
agents/strategy_agent.py - 报告汇总 Agent
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from agents.base_agent import BaseAgent
from models.domain import (
    ActionItem,
    Citation,
    CompetitorData,
    CompetitorList,
    CompetitiveAdvantage,
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
        super().__init__(
            agent_id="StrategyAgent",
            system_prompt="你负责整合多维分析并输出结构化策略报告。",
        )

    async def run(
        self,
        product_name: str,
        competitor_count: int,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
    ) -> StrategyReport:
        merged_citations = self._merge_citations(
            product_analysis.citations,
            pricing_analysis.citations,
            market_analysis.citations,
        )
        top_diff_points = product_analysis.differentiation_points[:3]
        product_focus = top_diff_points[0] if top_diff_points else "把高频能力做成可被感知的闭环方案。"
        pricing_focus = pricing_analysis.conclusions[0].statement if pricing_analysis.conclusions else "需要把升级逻辑讲清楚。"
        market_focus = market_analysis.conclusions[0].statement if market_analysis.conclusions else "需要把目标用户群讲清楚。"

        report = StrategyReport(
            product_name=product_name,
            competitor_count=competitor_count,
            overall_positioning=(
                f"{product_name} 不应再按“功能是否齐全”参与正面比拼，而应围绕自动化、集成和高频协作场景重组价值表达。"
                f" 产品层面优先抓 {product_focus}"
                f" 商业化层面则要用更清晰的升级路径承接 {pricing_focus}"
            ),
            differentiation_strategy={
                "core_differentiator": "把高频协作场景里的自动化、集成和可交付能力打包成一条更短的交付路径。",
                "supporting_points": top_diff_points,
            },
            action_plan=[
                ActionItem(
                    priority="P0",
                    action="把最核心的 1-2 个高频场景重新包装成标准方案，先讲清楚输入、输出和交付时长。",
                    timeline="1-2 周",
                    expected_impact="先提升销售与汇报材料的可理解性，降低同质化表达。",
                    citations=[item.id for item in product_analysis.citations[:2]],
                ),
                ActionItem(
                    priority="P1",
                    action="重写价格与升级说明，明确免费入口、升级触发点、席位或按量规则，以及 AI 能力是否单独收费。",
                    timeline="2-3 周",
                    expected_impact="减少价格沟通摩擦，提高试用到付费转化效率。",
                    citations=[item.id for item in pricing_analysis.citations[:2]],
                ),
                ActionItem(
                    priority="P1",
                    action="围绕目标客户做 5-8 个访谈或问卷，验证口碑问题、采购顾虑和真实使用场景。",
                    timeline="2 周",
                    expected_impact="把画像从推测变成证据，补齐产品优先级和卖点证据。",
                    citations=[item.id for item in market_analysis.citations[:2]],
                ),
            ],
            risk_assessment=(
                "当前公开信息对价格、市场份额和用户评价的覆盖深度并不完全一致，因此报告里的强结论必须优先绑定 citation。"
                " 如果后续采集证据仍然集中在媒体转述而不是官方页面，商业化判断的置信度会明显低于功能判断。"
                " 另外，竞品都在加大 AI 与生态能力曝光，如果我方仍用静态功能列表表达，会继续被拉入低区分度竞争。"
            ),
            product_analysis_summary=product_analysis.summary,
            pricing_analysis_summary=pricing_analysis.summary,
            market_analysis_summary=market_analysis.summary,
            citations=merged_citations,
            summary=(
                f"综合来看，{product_name} 的机会不在于再做一份泛化对标，而在于重新定义“为什么选你”。"
                f" 产品上要把 {product_focus} 讲成闭环，价格上要把升级逻辑讲清楚，市场上要围绕 {market_focus} 去验证真实需求。"
                f" 这样报告里的结论才能从信息罗列变成可执行策略。"
            ),
        )
        self._log("策略报告生成完成")
        return report

    @staticmethod
    def _merge_citations(*citation_lists: list[Citation]) -> list[Citation]:
        seen: dict[str, Citation] = {}
        for citations in citation_lists:
            for citation in citations:
                seen.setdefault(citation.id, citation)
        return list(seen.values())

    @staticmethod
    def build_citation_index(citations: list[Citation]) -> dict[str, Citation]:
        return {citation.id: citation for citation in citations if citation.id}

    def render_citation_links(self, citation_ids: list[str], citation_map: dict[str, Citation]) -> str:
        links = []
        for citation_id in list(dict.fromkeys(item for item in citation_ids if item))[:3]:
            citation = citation_map.get(citation_id)
            if not citation or not citation.url:
                continue
            label = escape(citation.title or citation.url)
            links.append(
                f'<a href="{escape(citation.url)}" target="_blank" rel="noopener noreferrer">{label}</a>'
            )
        if not links:
            return ""
        return f'<div class="sources">来源：{" / ".join(links)}</div>'

    def render_section_with_sources(
        self,
        title: str,
        body_html: str,
        citation_ids: list[str],
        citation_map: dict[str, Citation],
    ) -> str:
        return (
            '<section>'
            f"<h2>{escape(title)}</h2>"
            f"{body_html}"
            f"{self.render_citation_links(citation_ids, citation_map)}"
            "</section>"
        )

    def format_report(self, report: StrategyReport) -> str:
        lines = [
            "=" * 60,
            f"竞品分析报告: {report.product_name}",
            "=" * 60,
            f"竞品数量: {report.competitor_count}",
            f"定位: {report.overall_positioning}",
            "",
            "行动方案:",
        ]
        for item in report.action_plan:
            lines.append(f"- [{item.priority}] {item.action} ({item.timeline})")
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
        citation_map = self.build_citation_index(report.citations)
        payload = {
            "report": report,
            "product_analysis": product_analysis,
            "pricing_analysis": pricing_analysis,
            "market_analysis": market_analysis,
            "competitors_data": competitors_data,
            "timings": timings or {},
        }

        discovery_html = self._render_discovery_cards(competitor_list)
        competitor_sections_html = self._render_competitor_sections(
            report.product_name,
            product_analysis,
            pricing_analysis,
            market_analysis,
            competitors_data,
            citation_map,
            competitor_list,
        )
        feature_matrix_html = self._render_feature_matrix(product_analysis.feature_matrix, citation_map, competitor_list)
        pricing_html = self._render_pricing_section(pricing_analysis.pricing_comparison, pricing_analysis, citation_map)
        market_html = self._render_market_section(market_analysis, citation_map)
        persona_html = self._render_persona_section(market_analysis.user_personas, market_analysis, citation_map)
        positioning_html = self._render_positioning_section(report, product_analysis, citation_map)
        action_html = self._render_action_section(report.action_plan, citation_map)
        risk_html = self._render_risk_section(report, citation_map)
        summary_html = self._render_summary_section(report, citation_map, timings or {})
        appendix_html = self._render_source_appendix(report.citations)
        qa_html = self._render_qa_block(report)

        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(report.product_name)} 竞品分析报告</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f1f5f9; color: #1e293b; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    section {{ background: #fff; border-radius: 16px; padding: 28px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
    h1, h2, h3, h4 {{ margin-top: 0; }}
    p {{ line-height: 1.75; color: #334155; }}
    .hero {{ background: linear-gradient(135deg,#1e40af,#3b82f6); color: #fff; }}
    .hero p, .hero .meta, .hero .submeta {{ color: rgba(255,255,255,0.88); }}
    .meta-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:16px; margin-top: 18px; }}
    .meta-card {{ background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.18); border-radius: 14px; padding: 14px 16px; }}
    .card-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:16px; }}
    .mini-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(240px,1fr)); gap:12px; }}
    .card {{ background:#fff; border:1px solid #e2e8f0; border-radius: 12px; padding:16px; }}
    .card-soft {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius: 12px; padding:16px; }}
    .pill {{ display:inline-block; padding: 3px 10px; border-radius:999px; font-size:12px; background:#dbeafe; color:#1d4ed8; }}
    table {{ width:100%; border-collapse: collapse; border:1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 14px; text-align:left; border-bottom:1px solid #eef2f7; vertical-align: top; font-size: 13px; }}
    th {{ background:#f8fafc; color:#334155; }}
    .muted {{ color:#64748b; }}
    .good {{ color:#16a34a; }}
    .warn {{ color:#d97706; }}
    .bad {{ color:#dc2626; }}
    .sources {{ margin-top: 10px; font-size: 12px; color:#475569; line-height:1.6; }}
    .sources a {{ color:#1d4ed8; text-decoration:none; }}
    .sources a:hover {{ text-decoration:underline; }}
    .dim {{ font-size:12px; color:#64748b; margin-top:4px; }}
    .divider {{ text-align:center; margin:32px 0; font-size:20px; color:#94a3b8; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background:#0f172a; color:#e2e8f0; border-radius:12px; padding:18px; overflow:auto; font-size: 12px; }}
    .timeline-item {{ border-left: 4px solid #3b82f6; padding-left: 16px; margin-bottom: 18px; }}
    .summary-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(280px,1fr)); gap:16px; }}
    .compare-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr)); gap:12px; margin-top:16px; }}
    .section-note {{ margin-top: 10px; font-size: 13px; color:#475569; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>智能竞品分析报告</h1>
      <div class="submeta" style="font-size: 20px; margin-bottom: 8px;">{escape(report.product_name)}</div>
      <div class="meta">分析竞品 {report.competitor_count} 个 · 运行状态 {escape(report.status)}</div>
      <p style="margin-top:16px;">{escape(report.overall_positioning)}</p>
      <div class="meta-grid">
        <div class="meta-card">
          <div class="muted">核心差异化</div>
          <div>{escape(str(report.differentiation_strategy.get("core_differentiator", "待补充")))}</div>
        </div>
        <div class="meta-card">
          <div class="muted">报告摘要</div>
          <div>{escape(report.summary)}</div>
        </div>
      </div>
    </section>

    {discovery_html}
    {competitor_sections_html}
    {feature_matrix_html}
    {pricing_html}
    {market_html}
    {persona_html}
    {positioning_html}
    <div class="divider">━━━━━━━━━━━ 策略建议 ━━━━━━━━━━━</div>
    {action_html}
    {risk_html}
    {summary_html}
    {qa_html}
    <section>
      <h2>来源索引</h2>
      {appendix_html}
    </section>
    <section>
      <h2>结构化数据快照</h2>
      <pre>{escape(json.dumps(payload, ensure_ascii=False, default=lambda obj: getattr(obj, "__dict__", str(obj)), indent=2))}</pre>
    </section>
  </main>
</body>
</html>"""

    def _render_discovery_cards(self, competitor_list: CompetitorList | None) -> str:
        if not competitor_list or not competitor_list.competitors:
            return "<section><h2>发现竞品</h2><p>当前未发现可展示的竞品列表。</p></section>"
        cards = []
        for competitor in competitor_list.competitors:
            relevance = {
                "HIGH": ("直接竞品", "#ef4444"),
                "MEDIUM": ("间接竞品", "#f59e0b"),
                "LOW": ("潜在竞品", "#94a3b8"),
            }.get(competitor.relevance, ("竞品", "#94a3b8"))
            cards.append(
                '<div class="card">'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
                f"<strong>{escape(competitor.name)}</strong>"
                f'<span style="background:{relevance[1]};color:#fff;padding:2px 10px;border-radius:12px;font-size:11px;">{relevance[0]}</span>'
                "</div>"
                f'<div class="muted">{escape(competitor.brief or "暂无简介")}</div>'
                "</div>"
            )
        return (
            "<section><h2>🔎 发现竞品</h2>"
            '<div class="card-grid">'
            + "".join(cards)
            + "</div></section>"
        )

    def _render_competitor_sections(
        self,
        product_name: str,
        product_analysis: ProductAnalysis,
        pricing_analysis: PricingAnalysis,
        market_analysis: MarketAnalysis,
        competitors_data: dict[str, CompetitorData],
        citation_map: dict[str, Citation],
        competitor_list: CompetitorList | None,
    ) -> str:
        competitor_names = (
            [competitor.name for competitor in competitor_list.competitors]
            if competitor_list and competitor_list.competitors
            else list(competitors_data.keys())
        )
        sections = []
        for competitor_name in competitor_names:
            rows = []
            for item in product_analysis.feature_matrix[:6]:
                competitor_value = item.values.get(competitor_name, "unknown")
                target_value = "建议覆盖" if competitor_value == "supported" else "可选择性跟进"
                rows.append(
                    "<tr>"
                    f"<td>{escape(item.feature)}{self.render_citation_links(item.citations, citation_map)}</td>"
                    f"<td>{escape(target_value)}</td>"
                    f"<td>{escape(self._feature_value_text(competitor_value))}</td>"
                    "</tr>"
                )
            pricing_item = self._find_pricing_item(pricing_analysis.pricing_comparison, competitor_name)
            market_item = self._find_market_item(market_analysis.market_share_data, competitor_name)
            if pricing_item:
                rows.append(
                    "<tr>"
                    f"<td>定价模式{self.render_citation_links(pricing_item.citations, citation_map)}</td>"
                    "<td>建议把升级路径讲清楚</td>"
                    f"<td>{escape(pricing_item.pricing_model)} / {escape(pricing_item.free_tier[:50])}</td>"
                    "</tr>"
                )
            if market_item:
                rows.append(
                    "<tr>"
                    f"<td>市场份额{self.render_citation_links(market_item.citations, citation_map)}</td>"
                    "<td>重点说明切入位置</td>"
                    f"<td>{escape(market_item.share_estimate[:80])} / {escape(market_item.trend)}</td>"
                    "</tr>"
                )

            advantage = self._find_advantage(product_analysis.competitive_advantages, competitor_name)
            competitor_data = competitors_data.get(competitor_name)
            sections.append(
                "<section>"
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">'
                f"<h2>⚔️ {escape(product_name)} vs {escape(competitor_name)}</h2>"
                '<span class="pill">对比分析</span>'
                "</div>"
                "<div style=\"overflow-x:auto;\">"
                "<table><thead><tr>"
                "<th style=\"width: 180px;\">维度</th>"
                f"<th>{escape(product_name)}</th>"
                f"<th>{escape(competitor_name)}</th>"
                "</tr></thead><tbody>"
                + "".join(rows)
                + "</tbody></table></div>"
                '<div class="compare-grid">'
                + self._render_compare_card("🛡️ 我方优势", advantage.our_advantage if advantage else "建议围绕更短交付路径表达价值。", "good", advantage.citations if advantage else [], citation_map)
                + self._render_compare_card("⚠️ 对方优势", advantage.their_advantage if advantage else "暂无明确描述。", "bad", advantage.citations if advantage else [], citation_map)
                + self._render_compare_card("💪 对方长处", (competitor_data.strengths if competitor_data else "") or "当前证据更偏向能力曝光与生态表达。", "good", advantage.citations if advantage else [], citation_map)
                + self._render_compare_card("🎯 对方短板", (competitor_data.weaknesses if competitor_data else "") or "当前公开评价中未提炼出明确短板。", "warn", advantage.citations if advantage else [], citation_map)
                + "</div>"
                "</section>"
            )
        return "".join(sections)

    def _render_feature_matrix(
        self,
        feature_matrix: list[FeatureComparison],
        citation_map: dict[str, Citation],
        competitor_list: CompetitorList | None,
    ) -> str:
        competitor_names = (
            [competitor.name for competitor in competitor_list.competitors]
            if competitor_list and competitor_list.competitors
            else sorted({name for item in feature_matrix for name in item.values})
        )
        header = "".join(f"<th>{escape(name)}</th>" for name in competitor_names) + "<th>覆盖竞品数</th>"
        rows = []
        for item in feature_matrix:
            cells = "".join(
                f"<td>{escape(self._feature_value_text(item.values.get(name, 'unknown')))}</td>"
                for name in competitor_names
            )
            supported_count = sum(1 for value in item.values.values() if value == "supported")
            rows.append(
                "<tr>"
                f"<td>{escape(item.feature)}{self.render_citation_links(item.citations, citation_map)}</td>"
                f"{cells}"
                f"<td>{supported_count}</td>"
                "</tr>"
            )
        return (
            "<section><h2>🔧 功能对比矩阵（总览）</h2>"
            "<div style=\"overflow-x:auto;\"><table><thead><tr><th>功能维度</th>"
            + header
            + "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div></section>"
        )

    def _render_pricing_section(
        self,
        pricing_items: list[PricingItem],
        pricing_analysis: PricingAnalysis,
        citation_map: dict[str, Citation],
    ) -> str:
        rows = []
        for item in pricing_items:
            rows.append(
                "<tr>"
                f"<td>{escape(item.competitor)}</td>"
                f"<td>{escape(item.free_tier or '未知')}{self.render_citation_links(item.citations, citation_map)}</td>"
                f"<td>{escape(item.paid_tier or '未知')}</td>"
                f"<td>{escape(item.pricing_model or '未知')}</td>"
                "</tr>"
            )
        body = (
            f"<p>{escape(pricing_analysis.pricing_strategy_analysis)}</p>"
            "<div style=\"overflow-x:auto;\"><table><thead><tr>"
            "<th>竞品</th><th>免费层</th><th>付费层</th><th>定价模型</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )
        citations = [citation.id for citation in pricing_analysis.citations[:3]]
        return self.render_section_with_sources("💰 定价策略对比", body, citations, citation_map)

    def _render_market_section(self, market_analysis: MarketAnalysis, citation_map: dict[str, Citation]) -> str:
        cards = []
        for item in market_analysis.market_share_data:
            cards.append(
                '<div class="card-soft">'
                f"<h3>{escape(item.competitor)}</h3>"
                f"<p>{escape(item.share_estimate or '未知')}</p>"
                f'<div class="dim">趋势：{escape(item.trend or "待核验")}</div>'
                f"{self.render_citation_links(item.citations, citation_map)}"
                "</div>"
            )
        body = (
            f"<p>{escape(market_analysis.growth_trends)}</p>"
            '<div class="mini-grid">'
            + "".join(cards)
            + "</div>"
            f'<div class="section-note">{escape(market_analysis.channel_analysis)}</div>'
        )
        citations = [citation.id for citation in market_analysis.citations[:3]]
        return self.render_section_with_sources("📈 市场格局分析", body, citations, citation_map)

    def _render_persona_section(
        self,
        personas: list[UserPersona],
        market_analysis: MarketAnalysis,
        citation_map: dict[str, Citation],
    ) -> str:
        reputation_cards = []
        for competitor, reputation in market_analysis.user_reputation.items():
            reputation_cards.append(
                '<div class="card">'
                f"<h3>👥 {escape(competitor)} 用户口碑</h3>"
                f'<div class="muted">评分倾向：{escape(reputation.score or "未知")}</div>'
                f"<p>{escape('、'.join(reputation.keywords) or '暂无关键词')}</p>"
                f"{self.render_citation_links(reputation.citations, citation_map)}"
                "</div>"
            )
        persona_cards = []
        for persona in personas:
            persona_cards.append(
                '<div class="card">'
                f"<h3>{escape(persona.name)}</h3>"
                f'<div class="muted">用户段：{escape(persona.segment or "未知")}</div>'
                f"<p>需求：{escape('、'.join(persona.needs) or '暂无')}</p>"
                f"<p>抱怨：{escape('、'.join(persona.complaints) or '暂无')}</p>"
                f"<p>偏好渠道：{escape('、'.join(persona.preferred_channels) or '暂无')}</p>"
                f"{self.render_citation_links(persona.citations, citation_map)}"
                "</div>"
            )
        return (
            "<section><h2>👥 用户口碑与画像</h2>"
            '<div class="card-grid">' + "".join(reputation_cards) + "</div>"
            '<div class="card-grid" style="margin-top:16px;">' + "".join(persona_cards) + "</div>"
            "</section>"
        )

    def _render_positioning_section(
        self,
        report: StrategyReport,
        product_analysis: ProductAnalysis,
        citation_map: dict[str, Citation],
    ) -> str:
        supporting_points = "".join(
            f"<li>{escape(point)}</li>" for point in report.differentiation_strategy.get("supporting_points", [])
        )
        conclusions = "".join(
            '<div class="card-soft" style="margin-bottom:12px;">'
            f"<p>{escape(item.statement)}</p>"
            f"{self.render_citation_links(item.citations, citation_map)}"
            "</div>"
            for item in product_analysis.conclusions
        )
        return (
            "<section>"
            f"<h2>🧭 {escape(report.product_name)} 差异化定位</h2>"
            f"<p>{escape(report.overall_positioning)}</p>"
            '<div class="card-soft" style="margin-bottom:16px;">'
            f"<h3>🎯 核心差异化</h3><p>{escape(str(report.differentiation_strategy.get('core_differentiator', '待补充')))}</p>"
            f"<ul>{supporting_points}</ul>"
            "</div>"
            f"{conclusions}"
            "</section>"
        )

    def _render_action_section(self, action_plan: list[ActionItem], citation_map: dict[str, Citation]) -> str:
        items = []
        for item in action_plan:
            items.append(
                '<div class="timeline-item">'
                f"<div><strong>{escape(item.priority)}</strong> · {escape(item.action)}</div>"
                f'<div class="dim">时间线：{escape(item.timeline)} · 预期效果：{escape(item.expected_impact)}</div>'
                f"{self.render_citation_links(item.citations, citation_map)}"
                "</div>"
            )
        return "<section><h2>📋 行动方案</h2>" + "".join(items) + "</section>"

    def _render_risk_section(self, report: StrategyReport, citation_map: dict[str, Citation]) -> str:
        citation_ids = [citation.id for citation in report.citations[:3]]
        body = f"<p>{escape(report.risk_assessment)}</p>"
        if report.coverage_gaps:
            body += "<div class=\"card-soft\"><h3>Coverage Gap</h3><ul>"
            body += "".join(
                f"<li>{escape(gap.competitor)} / {escape(gap.topic)}：{escape(gap.reason)}</li>"
                for gap in report.coverage_gaps
            )
            body += "</ul></div>"
        return self.render_section_with_sources("⚠️ 风险评估", body, citation_ids, citation_map)

    def _render_summary_section(
        self,
        report: StrategyReport,
        citation_map: dict[str, Citation],
        timings: dict[str, Any],
    ) -> str:
        timing_rows = "".join(
            f'<div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;"><span>{escape(str(name))}</span><span>{float(value):.2f}s</span></div>'
            for name, value in timings.items()
            if isinstance(value, (int, float))
        )
        return (
            "<section><h2>📊 三维分析摘要</h2>"
            '<div class="summary-grid">'
            f'<div class="card"><h3>产品</h3>{self._render_paragraphs(report.product_analysis_summary)}{self.render_citation_links([citation.id for citation in report.citations[:3]], citation_map)}</div>'
            f'<div class="card"><h3>定价</h3>{self._render_paragraphs(report.pricing_analysis_summary)}{self.render_citation_links([citation.id for citation in report.citations[1:4] or report.citations[:2]], citation_map)}</div>'
            f'<div class="card"><h3>市场</h3>{self._render_paragraphs(report.market_analysis_summary)}{self.render_citation_links([citation.id for citation in report.citations[2:5] or report.citations[:2]], citation_map)}</div>'
            "</div>"
            '<div class="card-soft" style="margin-top:16px;">'
            "<h3>💡 综合建议</h3>"
            f"<p>{escape(report.summary)}</p>"
            f"{self.render_citation_links([citation.id for citation in report.citations[:3]], citation_map)}"
            "</div>"
            + (
                '<div class="card-soft" style="margin-top:16px;"><h3>运行耗时</h3>'
                + timing_rows
                + "</div>"
                if timing_rows
                else ""
            )
            + "</section>"
        )

    def _render_source_appendix(self, citations: list[Citation]) -> str:
        if not citations:
            return "<p>暂无来源索引。</p>"
        items = []
        for citation in citations:
            if not citation.url:
                continue
            items.append(
                "<li>"
                f'<a href="{escape(citation.url)}" target="_blank" rel="noopener noreferrer">{escape(citation.title or citation.url)}</a>'
                f'<div class="dim">{escape(citation.snippet[:180])}</div>'
                "</li>"
            )
        return "<ol>" + "".join(items) + "</ol>"

    def _render_qa_block(self, report: StrategyReport) -> str:
        if not report.qa_issues:
            return ""
        issues = "".join(
            '<div class="card-soft" style="margin-bottom:12px;">'
            f"<strong>{escape(issue.target_agent)}</strong>"
            f"<p>{escape(issue.reason)}</p>"
            f'<div class="dim">修复建议：{escape(issue.required_fix)}</div>'
            "</div>"
            for issue in report.qa_issues
        )
        return f"<section><h2>QA 复核记录</h2>{issues}</section>"

    @staticmethod
    def _render_paragraphs(text: str) -> str:
        chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
        if not chunks:
            return "<p>暂无摘要。</p>"
        return "".join(f"<p>{escape(chunk)}</p>" for chunk in chunks)

    @staticmethod
    def _feature_value_text(value: str) -> str:
        mapping = {
            "supported": "支持",
            "unknown": "待核验",
        }
        return mapping.get(value, value)

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
            f"{self.render_citation_links(citation_ids, citation_map)}"
            "</div>"
        )
