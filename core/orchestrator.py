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
import os
from datetime import datetime

from models.domain import (
    CompetitorList, CompetitorData,
    ProductAnalysis, PricingAnalysis, MarketAnalysis,
    StrategyReport
)
from core.artifact_store import ArtifactStore
from agents.discovery_agent import DiscoveryAgent
from agents.collection_agent import CollectionAgent
from agents.dimension_agent import DimensionAgent
from agents.product_agent import ProductAgent
from agents.pricing_agent import PricingAgent
from agents.market_agent import MarketAgent
from agents.strategy_agent import StrategyAgent
from agents.quality_agent import QualityAgent
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
        self.dimension_agent = DimensionAgent()
        self.collection_agent = CollectionAgent()
        self.product_agent = ProductAgent()
        self.pricing_agent = PricingAgent()
        self.market_agent = MarketAgent()
        self.strategy_agent = StrategyAgent()
        self.quality_agent = QualityAgent()

        self.timings: dict[str, float] = {}
        self.artifact_store: ArtifactStore | None = None
        self.run_dir: str = ""
        self._run_meta: dict = {}
        self._last_target_product_data: CompetitorData | None = None

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
        self._start_artifacts(product_description, max_competitors)

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
        self._save_artifact_json("01_competitor_list.json", competitor_list)

        if not competitor_list.competitors:
            print("  ⚠️ 未发现竞品，分析终止")
            report = StrategyReport(product_name=competitor_list.product_name)
            self.timings["total"] = time.time() - total_start
            report.raw_llm_logs = self._collect_llm_logs()
            self._save_artifact_json("07_strategy_report.json", report)
            self._save_artifact_json("llm_logs.json", report.raw_llm_logs)
            self._finalize_artifacts(
                status="stopped_no_competitors",
                product_name=report.product_name,
                competitor_count=0,
            )
            return report

        print(f"\n{'█' * 65}")
        print("  🧾 Phase 1.5: 目标产品采集")
        print(f"{'█' * 65}")

        target_collection_start = time.time()
        target_product_data = self.collection_agent.collect_target_product(
            product_description, competitor_list.product_name
        )
        self.timings["target_collection"] = time.time() - target_collection_start

        print(f"\n  ⏱️ 目标产品采集耗时: {self.timings['target_collection']:.2f}s")
        print(f"  🎯 目标产品: {target_product_data.name}")
        self._save_artifact_json("00_target_product_data.json", target_product_data)

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

        product_name = competitor_list.product_name

        # ── Phase 2 QA: 采集数据质检（精细化重做）──
        qa_start = time.time()
        original_search_texts = self.collection_agent.get_search_texts()
        qa_attempt = 1
        while qa_attempt <= QualityAgent.MAX_RETRIES + 1:
            qa_collection = await self.quality_agent.check_collection(
                competitors_data, original_search_texts,
                competitor_list=competitor_list, attempt=qa_attempt
            )
            self.quality_agent.timeline.add_check(qa_collection)

            if qa_collection.passed:
                break

            if qa_attempt <= QualityAgent.MAX_RETRIES:
                # 精细化：定位有问题的竞品，只重做它们
                failed_competitors = self.quality_agent.extract_failed_competitors(qa_collection)
                feedbacks = self.quality_agent.build_targeted_feedback(qa_collection, failed_competitors)

                if failed_competitors and len(failed_competitors) < len(competitors_data):
                    # 精细化修复：只重做出问题的竞品
                    print(f"  ⚠️ 采集质检未通过（第{qa_attempt}次），精细化修复 {len(failed_competitors)} 个竞品: {', '.join(failed_competitors)}")
                    qa_collection.repair_mode = "targeted"
                    qa_collection.repaired_competitors = list(failed_competitors)
                    for comp_name in failed_competitors:
                        competitors_data[comp_name] = self.collection_agent.collect_single(
                            product_name, product_description, comp_name,
                            feedback=feedbacks.get(comp_name, ""),
                        )
                    original_search_texts = self.collection_agent.get_search_texts()
                else:
                    # 大部分竞品都有问题，整体重做
                    print(f"  ⚠️ 采集质检未通过（第{qa_attempt}次），整体重做采集")
                    qa_collection.repair_mode = "full"
                    feedback = self.quality_agent.build_feedback(qa_collection)
                    competitors_data = await self.collection_agent.run(
                        product_description, competitor_list, feedback=feedback
                    )
                    original_search_texts = self.collection_agent.get_search_texts()
            else:
                print(f"  ⚠️ 采集数据质检未通过，已达到最大重试次数，降级通过")
                qa_collection.degraded = True

            qa_attempt += 1

        self.timings["qa_collection"] = time.time() - qa_start
        self._save_artifact_json("02_competitors_data.json", competitors_data)
        self._save_artifact_json("02_search_texts.json", original_search_texts)
        self._save_artifact_json("qa_timeline.json", self.quality_agent.timeline)

        # ── Phase 2.5: 维度生成 ──
        phase2_5_start = time.time()
        dim_config = await self.dimension_agent.run(
            product_description, competitor_list
        )
        self.timings["dimension"] = time.time() - phase2_5_start

        product_sub_dims_text = self._format_sub_dimensions(
            dim_config.product_sub_dimensions
        )
        pricing_sub_dims_text = self._format_sub_dimensions(
            dim_config.pricing_sub_dimensions
        )

        print(f"\n  ⏱️ 维度生成耗时: {self.timings['dimension']:.2f}s")
        print(f"  📐 品类: {dim_config.product_category.level1}/{dim_config.product_category.level2}")
        print(f"  📋 产品子维度: {len(dim_config.product_sub_dimensions)}个")
        print(f"  📋 定价子维度: {len(dim_config.pricing_sub_dimensions)}个")
        self._save_artifact_json("03_dimension_config.json", dim_config)

        # ── Phase 3: 三维并行分析（Fan-out）──
        print(f"\n{'█' * 65}")
        print("  ⚡ Phase 3: 三维并行分析 (Fan-out)")
        print(f"{'█' * 65}")

        phase3_start = time.time()

        # ── 构造降级警告（如有）──
        degradation_warning = ""
        if qa_collection.degraded:
            critical_hallucinations = [
                i for i in qa_collection.issues
                if i.severity == "critical" and i.category == "hallucination"
            ]
            if critical_hallucinations:
                degradation_warning = "⚠️ 上游采集数据存在以下幻觉嫌疑，请在分析时谨慎引用，优先使用有明确来源支撑的数据：\n"
                for i in critical_hallucinations[:5]:
                    degradation_warning += f"- {i.field}: {i.description}\n"

        # 并行执行三个分析Agent
        product_analysis, pricing_analysis, market_analysis = await asyncio.gather(
            self.product_agent.run(product_name, competitors_data,
                                   target_product_data=target_product_data,
                                   sub_dimensions=product_sub_dims_text,
                                   feedback=degradation_warning),
            self.pricing_agent.run(product_name, competitors_data,
                                   target_product_data=target_product_data,
                                   sub_dimensions=pricing_sub_dims_text,
                                   feedback=degradation_warning),
            self.market_agent.run(product_name, competitors_data,
                                  target_product_data=target_product_data,
                                  feedback=degradation_warning),
        )

        self.timings["parallel_analysis"] = time.time() - phase3_start

        print(f"\n  ⏱️ 并行分析总耗时: {self.timings['parallel_analysis']:.2f}s")
        print(f"  🔧 产品分析: {len(product_analysis.feature_matrix)}个功能维度")
        print(f"  💰 定价分析: {len(pricing_analysis.pricing_comparison)}个竞品定价")
        print(f"  📈 市场分析: {len(market_analysis.market_share_data)}个竞品市场数据")

        # ── Phase 3 QA: 三维分析质检 ──
        qa3_start = time.time()
        qa_product, qa_pricing, qa_market = await asyncio.gather(
            self.quality_agent.check_analysis("product", product_analysis, competitors_data),
            self.quality_agent.check_analysis("pricing", pricing_analysis, competitors_data),
            self.quality_agent.check_analysis("market", market_analysis, competitors_data),
        )

        # 打回未通过的分析 Agent
        for qa_result, agent_name, atype in [
            (qa_product, "ProductAgent", "product"),
            (qa_pricing, "PricingAgent", "pricing"),
            (qa_market, "MarketAgent", "market"),
        ]:
            self.quality_agent.timeline.add_check(qa_result)
            qa_attempt = 1
            while not qa_result.passed and qa_attempt <= QualityAgent.MAX_RETRIES:
                print(f"  ⚠️ {agent_name} 质检未通过（第{qa_attempt}次），打回重做")
                feedback = self.quality_agent.build_feedback(qa_result)

                if atype == "product":
                    product_analysis = await self.product_agent.run(
                        product_name, competitors_data,
                        target_product_data=target_product_data,
                        sub_dimensions=product_sub_dims_text, feedback=feedback
                    )
                elif atype == "pricing":
                    pricing_analysis = await self.pricing_agent.run(
                        product_name, competitors_data,
                        target_product_data=target_product_data,
                        sub_dimensions=pricing_sub_dims_text, feedback=feedback
                    )
                else:
                    market_analysis = await self.market_agent.run(
                        product_name, competitors_data,
                        target_product_data=target_product_data, feedback=feedback
                    )

                # 重新质检
                if atype == "product":
                    qa_result = await self.quality_agent.check_analysis("product", product_analysis, competitors_data)
                elif atype == "pricing":
                    qa_result = await self.quality_agent.check_analysis("pricing", pricing_analysis, competitors_data)
                else:
                    qa_result = await self.quality_agent.check_analysis("market", market_analysis, competitors_data)

                self.quality_agent.timeline.add_check(qa_result)
                qa_attempt += 1

            if not qa_result.passed:
                qa_result.degraded = True
                print(f"  ⚠️ {agent_name} 质检未通过，降级通过")

        self.timings["qa_analysis"] = time.time() - qa3_start
        self._save_artifact_json("04_product_analysis.json", product_analysis)
        self._save_artifact_json("05_pricing_analysis.json", pricing_analysis)
        self._save_artifact_json("06_market_analysis.json", market_analysis)
        self._save_artifact_json("qa_timeline.json", self.quality_agent.timeline)

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
            target_product_data=target_product_data,
            competitors_data=competitors_data,
        )
        self.timings["strategy"] = time.time() - phase4_start

        # ── Phase 4 QA: 策略报告质检 ──
        qa4_start = time.time()
        qa_attempt = 1
        while qa_attempt <= QualityAgent.MAX_RETRIES + 1:
            qa_strategy = await self.quality_agent.check_strategy(
                report, product_analysis, pricing_analysis, market_analysis,
                attempt=qa_attempt
            )
            self.quality_agent.timeline.add_check(qa_strategy)

            if qa_strategy.passed:
                break

            if qa_attempt <= QualityAgent.MAX_RETRIES:
                print(f"  ⚠️ 策略报告质检未通过（第{qa_attempt}次），打回 StrategyAgent 重做")
                feedback = self.quality_agent.build_feedback(qa_strategy)
                report = await self.strategy_agent.run(
                    product_name,
                    len(competitor_list.competitors),
                    product_analysis,
                    pricing_analysis,
                    market_analysis,
                    target_product_data=target_product_data,
                    competitors_data=competitors_data,
                    feedback=feedback,
                )
            else:
                qa_strategy.degraded = True
                print(f"  ⚠️ 策略报告质检未通过，降级通过")

            qa_attempt += 1

        # 附加 QA 时间线到报告
        report.qa_timeline = self.quality_agent.timeline
        self.timings["qa_strategy"] = time.time() - qa4_start

        self.timings["total"] = time.time() - total_start

        # 附加LLM调用日志
        report.raw_llm_logs = self._collect_llm_logs()
        self._save_artifact_json("07_strategy_report.json", report)
        self._save_artifact_json("qa_timeline.json", report.qa_timeline)
        self._save_artifact_json("llm_logs.json", report.raw_llm_logs)
        self._finalize_artifacts(
            status="completed",
            product_name=report.product_name,
            competitor_count=report.competitor_count,
        )

        # 缓存三维分析数据（供HTML报告使用）
        self._last_product_analysis = product_analysis
        self._last_pricing_analysis = pricing_analysis
        self._last_market_analysis = market_analysis
        self._last_competitor_list = competitor_list
        self._last_competitors_data = competitors_data
        self._last_target_product_data = target_product_data

        print(f"\n  ⏱️ 策略建议耗时: {self.timings['strategy']:.2f}s")
        print(f"\n{'═' * 65}")
        print(f"  🏁 分析完成 | 总耗时: {self.timings['total']:.2f}s")
        print(f"  🎯 行动方案: {len(report.action_plan)}项")
        cite_count = len(report.citation_index.citations) if report.citation_index else 0
        print(f"  📚 引用来源: {cite_count}条")
        qa_total = len(report.qa_timeline.checks)
        qa_retries = report.qa_timeline.total_retries
        print(f"  🔍 质检次数: {qa_total}次 | 重试: {qa_retries}次")
        print(f"{'═' * 65}")

        # 打印格式化报告
        formatted = self.strategy_agent.format_report(report)
        print(formatted)

        # 打印功能矩阵
        self._print_feature_matrix(product_name, product_analysis, competitor_list)

        return report

    def _start_artifacts(self, product_description: str, max_competitors: int):
        """初始化本次运行的归档目录和元信息。"""
        output_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "output",
        )
        self.artifact_store = ArtifactStore.create_for_product(
            output_root, product_description
        )
        self.run_dir = str(self.artifact_store.run_dir)
        self._run_meta = {
            "status": "running",
            "product_description": product_description,
            "max_competitors": max_competitors,
            "enable_llm": config.ENABLE_LLM,
            "llm_provider": config.LLM_PROVIDER,
            "doubao_model": config.DOUBAO_MODEL,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "ended_at": "",
            "timings": {},
            "output_files": [],
        }
        self._save_run_meta()

    def _finalize_artifacts(self, status: str, product_name: str, competitor_count: int):
        if not self.artifact_store:
            return
        self._run_meta.update({
            "status": status,
            "product_name": product_name,
            "competitor_count": competitor_count,
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "timings": self.get_timings(),
            "output_files": self.artifact_store.saved_files(),
        })
        self._save_run_meta()
        print(f"  📦 运行归档: {self.run_dir}")

    def update_artifact_meta(self):
        """刷新 run_meta 中的文件清单，供入口保存最终报告后调用。"""
        if not self.artifact_store:
            return
        self._run_meta.update({
            "timings": self.get_timings(),
            "output_files": self.artifact_store.saved_files(),
        })
        self._save_run_meta()

    def _save_run_meta(self):
        if self.artifact_store:
            self.artifact_store.save_json("run_meta.json", self._run_meta)

    def _save_artifact_json(self, name: str, data):
        if self.artifact_store:
            self.artifact_store.save_json(name, data)

    def _collect_llm_logs(self) -> list[dict]:
        return (
            self.discovery_agent.llm_logs +
            self.dimension_agent.llm_logs +
            self.collection_agent.llm_logs +
            self.product_agent.llm_logs +
            self.pricing_agent.llm_logs +
            self.market_agent.llm_logs +
            self.strategy_agent.llm_logs +
            self.quality_agent.llm_logs
        )

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
    def _format_sub_dimensions(dims: list) -> str:
        """将子维度列表格式化为 prompt 注入文本"""
        lines = []
        for i, d in enumerate(dims, 1):
            lines.append(f"{i}. **{d.name}**：{d.description}")
        return "\n".join(lines)

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
