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
    StrategyReport, ActionItem
)
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

    async def run(self, product_name: str,
                  competitor_count: int,
                  product_analysis: ProductAnalysis,
                  pricing_analysis: PricingAnalysis,
                  market_analysis: MarketAnalysis) -> StrategyReport:
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

        # 构建三维分析汇总文本
        analysis_text = self._build_analysis_text(
            product_name, product_analysis, pricing_analysis, market_analysis
        )

        if config.ENABLE_LLM:
            prompt = self._prompt_strategy.format(
                product_name=product_name,
                analysis_text=analysis_text,
            )
            result = self.ask_llm_json(prompt, max_tokens=4096)
            if result:
                report = self._parse_strategy_report(product_name, competitor_count, result)
                self._log(f"✅ 策略建议完成: {len(report.action_plan)}项行动方案")
                return report
            else:
                self._log("⚠️ LLM策略建议失败，降级到规则引擎")

        return self._rule_strategy(product_name, competitor_count,
                                    product_analysis, pricing_analysis, market_analysis)

    def _build_analysis_text(self, product_name: str,
                              product_analysis: ProductAnalysis,
                              pricing_analysis: PricingAnalysis,
                              market_analysis: MarketAnalysis) -> str:
        """构建三维分析汇总文本"""
        lines = []

        # 产品分析
        lines.append("## 一、产品分析")
        if product_analysis.feature_matrix:
            features = [fm.feature for fm in product_analysis.feature_matrix]
            lines.append(f"对比功能维度: {', '.join(features[:10])}")
        if product_analysis.competitive_advantages:
            for adv in product_analysis.competitive_advantages[:5]:
                lines.append(f"- vs {adv.competitor}: 我方优势={adv.our_advantage}, 对方优势={adv.their_advantage}")
        if product_analysis.differentiation_points:
            lines.append(f"差异化点: {', '.join(product_analysis.differentiation_points[:5])}")
        lines.append(f"摘要: {product_analysis.summary}")

        # 定价分析
        lines.append("\n## 二、定价分析")
        if pricing_analysis.pricing_comparison:
            for pc in pricing_analysis.pricing_comparison[:5]:
                lines.append(f"- {pc.competitor}: 免费={pc.free_tier}, 付费={pc.paid_tier}, 模式={pc.pricing_model}")
        lines.append(f"策略分析: {pricing_analysis.pricing_strategy_analysis}")
        if pricing_analysis.value_ranking:
            lines.append(f"性价比排名: {' > '.join(pricing_analysis.value_ranking)}")
        lines.append(f"摘要: {pricing_analysis.summary}")

        # 市场分析
        lines.append("\n## 三、市场分析")
        if market_analysis.market_share_data:
            for ms in market_analysis.market_share_data[:5]:
                lines.append(f"- {ms.competitor}: 份额={ms.share_estimate}, 趋势={ms.trend}")
        lines.append(f"增长趋势: {market_analysis.growth_trends}")
        lines.append(f"渠道分析: {market_analysis.channel_analysis}")
        lines.append(f"摘要: {market_analysis.summary}")

        return "\n".join(lines)

    def _parse_strategy_report(self, product_name: str, competitor_count: int,
                                result: dict) -> StrategyReport:
        """解析LLM返回的策略报告"""
        action_plan = []
        for ap in result.get("action_plan", []):
            action_plan.append(ActionItem(
                priority=ap.get("priority", "P2"),
                action=ap.get("action", ""),
                timeline=ap.get("timeline", ""),
                expected_impact=ap.get("expected_impact", ""),
            ))

        return StrategyReport(
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

    def _rule_strategy(self, product_name: str, competitor_count: int,
                        product_analysis: ProductAnalysis,
                        pricing_analysis: PricingAnalysis,
                        market_analysis: MarketAnalysis) -> StrategyReport:
        """规则引擎策略建议（SWOT模板）"""
        # 从三维分析中提取关键词
        diff_points = product_analysis.differentiation_points[:3] if product_analysis.differentiation_points else []
        diff_text = "、".join(diff_points) if diff_points else "需进一步分析"

        return StrategyReport(
            product_name=product_name,
            competitor_count=competitor_count,
            overall_positioning=f"{product_name}应基于{diff_text}等差异化优势进行市场定位",
            differentiation_strategy={
                "core_differentiator": diff_text,
                "supporting_points": diff_points,
            },
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
            "─── 整体定位 ───",
            report.overall_positioning or "暂无",
            "",
            "─── 差异化策略 ───",
        ]

        if report.differentiation_strategy:
            core = report.differentiation_strategy.get("core_differentiator", "")
            points = report.differentiation_strategy.get("supporting_points", [])
            lines.append(f"  核心差异: {core}")
            if points:
                lines.append(f"  支撑点: {', '.join(points)}")

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

        def find_cdata(cdata_map_dict: dict, comp_name: str) -> 'CompetitorData | None':
            """模糊匹配竞品名查找采集数据"""
            if comp_name in cdata_map_dict:
                return cdata_map_dict[comp_name]
            for key, val in cdata_map_dict.items():
                if comp_name in key or key in comp_name:
                    return val
            return None

        def trend_icon(trend: str) -> str:
            t = trend.strip()
            if any(k in t for k in ["上升", "增长", "上涨", "↗", "↑"]):
                return f'<span style="color:#22c55e;">↗ {esc(t)}</span>'
            elif any(k in t for k in ["下降", "下滑", "下跌", "↘", "↓"]):
                return f'<span style="color:#ef4444;">↘ {esc(t)}</span>'
            else:
                return f'<span style="color:#64748b;">→ {esc(t)}</span>'

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
                        <td style="padding:8px 14px;font-size:13px;color:#64748b;width:100px;">{esc(fm.feature)}</td>
                        <td style="padding:8px 14px;text-align:center;">{feature_icon(ov)}</td>
                        <td style="padding:8px 14px;text-align:center;">{feature_icon(tv)}</td>
                    </tr>'''

            # 定价行
            if pi:
                comparison_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">免费版</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">—</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(pi.free_tier) if pi.free_tier else '—'}</td>
                </tr>
                <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">付费版</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">—</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(pi.paid_tier) if pi.paid_tier else '—'}</td>
                </tr>
                <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">定价模式</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">—</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(pi.pricing_model) if pi.pricing_model else '—'}</td>
                </tr>'''

            # 市场份额行
            if ms:
                comparison_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">市场份额</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">—</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">{esc(ms.share_estimate)}</td>
                </tr>
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:8px 14px;font-size:13px;color:#64748b;">趋势</td>
                    <td style="padding:8px 14px;font-size:13px;text-align:center;">—</td>
                    <td style="padding:8px 14px;text-align:center;">{trend_icon(ms.trend)}</td>
                </tr>'''

            # ── 优劣势分析 ──
            strengths_text = ""
            weaknesses_text = ""
            our_adv_text = ""
            their_adv_text = ""

            if cd:
                if cd.strengths:
                    strengths_text = cd.strengths
                if cd.weaknesses:
                    weaknesses_text = cd.weaknesses
            if adv:
                our_adv_text = adv.our_advantage
                their_adv_text = adv.their_advantage

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
            if strengths_text:
                swot_parts.append(f'''
                <div style="flex:1;min-width:200px;">
                    <div style="background:#eff6ff;border-left:4px solid #3b82f6;padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:8px;">
                        <div style="font-size:12px;font-weight:600;color:#2563eb;margin-bottom:4px;">💪 对方长处</div>
                        <div style="font-size:13px;color:#1d4ed8;line-height:1.6;">{esc(strengths_text)}</div>
                    </div>
                </div>''')
            if weaknesses_text:
                swot_parts.append(f'''
                <div style="flex:1;min-width:200px;">
                    <div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:8px;">
                        <div style="font-size:12px;font-weight:600;color:#d97706;margin-bottom:4px;">🎯 对方短板</div>
                        <div style="font-size:13px;color:#b45309;line-height:1.6;">{esc(weaknesses_text)}</div>
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
                cells = f'<td style="padding:10px 16px;font-weight:500;font-size:13px;border-right:1px solid #e2e8f0;">{esc(fm.feature)}</td>'
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
                    <span>✅ 支持</span><span>🔶 部分支持</span><span>❌ 不支持</span><span>❓ 未知</span>
                </div>
            </div>'''

        # ══════════════════════════════════════════════
        # 区块4：定价策略对比
        # ══════════════════════════════════════════════
        pricing_html = ""
        if pricing_analysis and pricing_analysis.pricing_comparison:
            price_rows = ""
            for pc in pricing_analysis.pricing_comparison:
                price_rows += f'''
                <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:10px 16px;font-weight:500;font-size:13px;">{esc(pc.competitor)}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(pc.free_tier) if pc.free_tier else '<span style="color:#94a3b8;">—</span>'}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(pc.paid_tier) if pc.paid_tier else '<span style="color:#94a3b8;">—</span>'}</td>
                    <td style="padding:10px 16px;font-size:13px;">{esc(pc.pricing_model) if pc.pricing_model else '<span style="color:#94a3b8;">—</span>'}</td>
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
            max_share = 0
            share_data = []
            for ms in market_analysis.market_share_data:
                num_match = re.search(r'([\d.]+)', ms.share_estimate)
                share_num = float(num_match.group(1)) if num_match else 0
                max_share = max(max_share, share_num)
                share_data.append((ms, share_num))

            share_data_sorted = sorted(share_data, key=lambda x: x[1], reverse=True)

            share_bars = ""
            for ms, share_num in share_data_sorted:
                bar_width = (share_num / max_share * 100) if max_share > 0 else 50
                bar_width = max(bar_width, 5)
                share_bars += f'''
                <div style="display:flex;align-items:center;margin-bottom:12px;">
                    <div style="width:120px;font-size:14px;font-weight:500;flex-shrink:0;">{esc(ms.competitor)}</div>
                    <div style="flex:1;margin:0 12px;">
                        <div style="background:#f1f5f9;border-radius:6px;height:28px;overflow:hidden;">
                            <div style="background:linear-gradient(90deg,#3b82f6,#6366f1);height:100%;width:{bar_width:.1f}%;border-radius:6px;display:flex;align-items:center;padding:0 10px;">
                                <span style="color:#fff;font-size:12px;font-weight:600;white-space:nowrap;">{esc(ms.share_estimate)}</span>
                            </div>
                        </div>
                    </div>
                    <div style="width:80px;text-align:right;flex-shrink:0;">{trend_icon(ms.trend)}</div>
                </div>'''

            # 用户口碑
            reputation_html = ""
            if market_analysis.user_reputation:
                rep_cards = ""
                for name, rep in market_analysis.user_reputation.items():
                    kw_tags = ""
                    for kw in (rep.keywords or [])[:5]:
                        kw_tags += f'<span style="background:#ede9fe;color:#6d28d9;padding:2px 8px;border-radius:12px;font-size:11px;margin:2px;">{esc(kw)}</span>'
                    rep_cards += f'''
                    <div style="background:#f8fafc;border-radius:10px;padding:14px;flex:1;min-width:150px;">
                        <div style="font-weight:600;font-size:14px;margin-bottom:6px;">{esc(name)}</div>
                        <div style="font-size:20px;font-weight:700;color:#f59e0b;margin-bottom:4px;">{esc(rep.score) if rep.score else '—'}</div>
                        <div>{kw_tags}</div>
                    </div>'''
                reputation_html = f'''
                <div style="margin-top:20px;">
                    <h3 style="font-size:16px;color:#475569;margin-bottom:12px;">👥 用户口碑</h3>
                    <div style="display:flex;gap:12px;flex-wrap:wrap;">{rep_cards}</div>
                </div>'''

            market_html = f'''
            <div style="background:#fff;border-radius:16px;padding:28px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                <h2 style="margin:0 0 20px 0;font-size:20px;color:#1e293b;">📈 市场格局分析</h2>
                {share_bars}
                {reputation_html}
                {'<div style="margin-top:16px;padding:12px 16px;background:#eff6ff;border-radius:8px;font-size:14px;line-height:1.8;"><strong>增长趋势：</strong>' + esc(market_analysis.growth_trends) + '</div>' if market_analysis.growth_trends else ''}
                {'<div style="margin-top:10px;padding:12px 16px;background:#fef3c7;border-radius:8px;font-size:14px;line-height:1.8;"><strong>渠道分析：</strong>' + esc(market_analysis.channel_analysis) + '</div>' if market_analysis.channel_analysis else ''}
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
                        <div style="font-size:13px;color:#15803d;line-height:1.5;">{esc(adv.our_advantage)}</div>
                    </div>
                    <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:10px 14px;border-radius:0 8px 8px 0;flex:1;">
                        <div style="font-size:11px;color:#dc2626;font-weight:600;margin-bottom:2px;">vs {esc(adv.competitor)} 需追赶</div>
                        <div style="font-size:13px;color:#b91c1c;line-height:1.5;">{esc(adv.their_advantage)}</div>
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

        # 行动方案
        action_cards = ""
        for ap in report.action_plan:
            action_cards += f'''
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;flex:1;min-width:280px;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
                    {priority_badge(ap.priority)}
                    <strong style="font-size:15px;">{esc(ap.action)}</strong>
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
    {action_html}
    {risk_html}

    <!-- 三维分析摘要 -->
    {"<div style='margin-bottom:24px;'><h2 style='font-size:20px;color:#1e293b;margin-bottom:16px;'>📊 三维分析摘要</h2><div style='display:flex;gap:16px;flex-wrap:wrap;'>" + summary_cards + '</div></div>' if summary_cards else ''}

    {overall_summary_html}

    {timing_html}

    <!-- 页脚 -->
    <div style="text-align:center;padding:24px 0;font-size:12px;color:#94a3b8;">
        智能竞品分析多Agent系统 · 串行采集 → 并行分析 → 串行汇总
    </div>

</div>
</body>
</html>'''

        return html
