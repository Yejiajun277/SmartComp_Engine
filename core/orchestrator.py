# -*- coding: utf-8 -*-
"""
core/orchestrator.py — 主控编排器（混合协作模式）

编排流程：
  1. 竞品发现Agent（串行）
  2. 数据采集Agent（串行，逐竞品采集）
  3. 产品分析 + 定价分析 + 市场分析（并行，asyncio.gather）
  4. 策略建议Agent（串行，汇聚三维结果）
"""

import asyncio
import time
import json

from models.domain import (
    CompetitorList, CompetitorData,
    ProductAnalysis, PricingAnalysis, MarketAnalysis,
    StrategyReport
)
from agents.discovery_agent import DiscoveryAgent
from agents.collection_agent import CollectionAgent
from agents.product_agent import ProductAgent
from agents.pricing_agent import PricingAgent
from agents.market_agent import MarketAgent
from agents.strategy_agent import StrategyAgent
import config


class Orchestrator:
    """
    竞品分析主控编排器

    协作模式：串行采集 → 并行分析 → 串行汇总

                        ┌──────────────┐
                        │  竞品发现     │
                        │  Agent       │
                        └──────┬───────┘
                               │
                        ┌──────────────┐
                        │  数据采集     │
                        │  Agent       │
                        └──────┬───────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
     │  产品分析     │  │  定价分析     │  │  市场分析     │
     │  Agent       │  │  Agent       │  │  Agent       │
     └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
            └────────────────┼─────────────────┘
                             ▼
                    ┌──────────────┐
                    │  策略建议     │
                    │  Agent       │
                    └──────────────┘
    """

    def __init__(self):
        self.discovery_agent = DiscoveryAgent()
        self.collection_agent = CollectionAgent()
        self.product_agent = ProductAgent()
        self.pricing_agent = PricingAgent()
        self.market_agent = MarketAgent()
        self.strategy_agent = StrategyAgent()

        self.timings: dict[str, float] = {}

    async def analyze(self, product_description: str,
                      max_competitors: int = config.DEFAULT_COMPETITOR_COUNT) -> StrategyReport:
        """
        执行完整的竞品分析流程

        Args:
            product_description: 用户产品描述
            max_competitors: 最大竞品数量

        Returns:
            StrategyReport: 完整策略建议报告
        """
        total_start = time.time()

        print("\n" + "═" * 65)
        print("  🔍 智能竞品分析多Agent系统")
        print("  模式: 串行采集 → 并行分析 → 串行汇总 | "
              f"决策: {'🧠 LLM' if config.ENABLE_LLM else '📋 规则引擎'}")
        print("═" * 65)

        # ── Phase 1: 竞品发现（串行）──
        print(f"\n{'█' * 65}")
        print("  🔍 Phase 1: 竞品发现")
        print(f"{'█' * 65}")

        phase1_start = time.time()
        competitor_list = await self.discovery_agent.run(
            product_description, max_competitors
        )
        self.timings["discovery"] = time.time() - phase1_start

        print(f"\n  ⏱️ 发现耗时: {self.timings['discovery']:.2f}s")
        print(f"  📊 发现竞品: {len(competitor_list.competitors)}个")

        if not competitor_list.competitors:
            print("  ⚠️ 未发现竞品，分析终止")
            return StrategyReport(product_name=competitor_list.product_name)

        # ── Phase 2: 数据采集（串行，逐竞品）──
        print(f"\n{'█' * 65}")
        print("  📊 Phase 2: 数据采集（逐竞品）")
        print(f"{'█' * 65}")

        phase2_start = time.time()
        competitors_data = await self.collection_agent.run(
            product_description, competitor_list
        )
        self.timings["collection"] = time.time() - phase2_start

        print(f"\n  ⏱️ 采集耗时: {self.timings['collection']:.2f}s")
        print(f"  📊 采集完成: {len(competitors_data)}个竞品")

        # ── Phase 3: 三维并行分析（Fan-out）──
        print(f"\n{'█' * 65}")
        print("  ⚡ Phase 3: 三维并行分析 (Fan-out)")
        print(f"{'█' * 65}")

        phase3_start = time.time()

        product_name = competitor_list.product_name

        # 并行执行三个分析Agent
        product_analysis, pricing_analysis, market_analysis = await asyncio.gather(
            self.product_agent.run(product_name, competitors_data),
            self.pricing_agent.run(product_name, competitors_data),
            self.market_agent.run(product_name, competitors_data),
        )

        self.timings["parallel_analysis"] = time.time() - phase3_start

        print(f"\n  ⏱️ 并行分析总耗时: {self.timings['parallel_analysis']:.2f}s")
        print(f"  🔧 产品分析: {len(product_analysis.feature_matrix)}个功能维度")
        print(f"  💰 定价分析: {len(pricing_analysis.pricing_comparison)}个竞品定价")
        print(f"  📈 市场分析: {len(market_analysis.market_share_data)}个竞品市场数据")

        # ── Phase 4: 策略建议（Gather）──
        print(f"\n{'█' * 65}")
        print("  🎯 Phase 4: 策略建议 (Gather)")
        print(f"{'█' * 65}")

        phase4_start = time.time()
        report = await self.strategy_agent.run(
            product_name,
            len(competitor_list.competitors),
            product_analysis,
            pricing_analysis,
            market_analysis,
        )
        self.timings["strategy"] = time.time() - phase4_start

        self.timings["total"] = time.time() - total_start

        # 附加LLM调用日志
        report.raw_llm_logs = (
            self.discovery_agent.llm_logs +
            self.collection_agent.llm_logs +
            self.product_agent.llm_logs +
            self.pricing_agent.llm_logs +
            self.market_agent.llm_logs +
            self.strategy_agent.llm_logs
        )

        # 缓存三维分析数据（供HTML报告使用）
        self._last_product_analysis = product_analysis
        self._last_pricing_analysis = pricing_analysis
        self._last_market_analysis = market_analysis
        self._last_competitor_list = competitor_list
        self._last_competitors_data = competitors_data

        print(f"\n  ⏱️ 策略建议耗时: {self.timings['strategy']:.2f}s")
        print(f"\n{'═' * 65}")
        print(f"  🏁 分析完成 | 总耗时: {self.timings['total']:.2f}s")
        print(f"  🎯 行动方案: {len(report.action_plan)}项")
        print(f"{'═' * 65}")

        # 打印格式化报告
        formatted = self.strategy_agent.format_report(report)
        print(formatted)

        # 打印功能矩阵
        self._print_feature_matrix(product_name, product_analysis, competitor_list)

        return report

    def _print_feature_matrix(self, product_name: str,
                               product_analysis: ProductAnalysis,
                               competitor_list: CompetitorList):
        """打印功能对比矩阵"""
        if not product_analysis.feature_matrix:
            return

        print("\n\n" + "─" * 65)
        print("  📋 功能对比矩阵")
        print("─" * 65)

        # 表头
        names = [c.name for c in competitor_list.competitors]
        if product_name not in names:
            names.insert(0, product_name)

        header = f"{'功能':<12}"
        for name in names:
            header += f" {name:<12}"
        print(header)
        print("─" * len(header))

        # 数据行
        for fm in product_analysis.feature_matrix:
            row = f"{fm.feature:<12}"
            for name in names:
                val = self._find_feature_value(fm.values, name, product_name)
                row += f" {val:<12}"
            print(row)

    @staticmethod
    def _find_feature_value(values_dict: dict, target_name: str, product_name: str) -> str:
        """从 feature_matrix.values 中查找目标名对应的值（模糊匹配）"""
        if not values_dict:
            return "❓"
        # 精确匹配
        if target_name in values_dict:
            return values_dict[target_name]
        # 带后缀匹配（LLM可能返回 "飞书(我方产品)" 格式）
        for key in values_dict:
            if key.startswith(target_name) and target_name in key:
                return values_dict[key]
        # 如果查找的是我方产品
        if target_name == product_name:
            for key in values_dict:
                if product_name in key:
                    return values_dict[key]
        # 模糊匹配
        for key in values_dict:
            if target_name in key or key in target_name:
                return values_dict[key]
        return "❓"

    def get_timings(self) -> dict:
        """获取各阶段耗时"""
        return self.timings.copy()

    def print_stats(self):
        """打印统计信息"""
        from core.llm_client import get_llm_stats

        print("\n" + "─" * 65)
        print("  📈 分析统计")
        print("─" * 65)
        print(f"  ⏱️ 各阶段耗时:")
        for name, duration in self.timings.items():
            print(f"    • {name}: {duration:.2f}s")

        if config.ENABLE_LLM:
            stats = get_llm_stats()
            print(f"\n  🧠 LLM调用统计:")
            print(f"    • 总调用: {stats['total']}")
            print(f"    • 成功: {stats['success']}")
            print(f"    • 降级: {stats['fallback']}")
            if stats['total'] > 0:
                rate = stats['success'] / stats['total'] * 100
                print(f"    • 成功率: {rate:.0f}%")
