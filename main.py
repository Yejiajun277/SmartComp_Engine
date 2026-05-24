#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from agents.strategy_agent import StrategyAgent
from core.orchestrator import print_analysis_stats, print_feature_matrix
from workflow.graph import run_analysis_graph


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except ValueError:
                stream.reconfigure(errors="replace")


def print_banner():
    print(
        """
=================================================================
  AI 驱动的竞品分析 Agent 协作系统
  模式: 发现 -> 研究规划 -> 证据采集 -> 并行分析 -> 质检闭环
=================================================================
"""
    )


async def run_analysis(
    product_description: str,
    use_llm: bool = True,
    max_competitors: int = config.DEFAULT_COMPETITOR_COUNT,
):
    config.ENABLE_LLM = use_llm
    print_banner()
    print(f"  分析目标: {product_description}")
    print(f"  最大竞品数: {max_competitors}")
    print(f"  LLM 模式: {'开启' if use_llm else '关闭'}")
    print()

    state = await run_analysis_graph(
        product_description=product_description,
        max_competitors=max_competitors,
        use_llm=use_llm,
    )
    report = state.get("report")
    if report is None:
        raise ValueError("分析流程未生成报告")

    strategy_agent = StrategyAgent()
    print_analysis_stats(state.get("timings", {}))
    print(strategy_agent.format_report(report))
    print_feature_matrix(
        report.product_name,
        state.get("product_analysis"),
        state.get("competitor_list"),
    )

    report_paths = state.get("report_paths", {})
    if report_paths.get("html"):
        print(f"\nHTML 报告已保存: {report_paths['html']}")
    if report_paths.get("json"):
        print(f"JSON 报告已保存: {report_paths['json']}")
    trace_dir = state.get("trace_summary", {}).get("trace_dir")
    if trace_dir:
        print(f"Trace 输出目录: {trace_dir}")
    return report


def print_help():
    print(
        """
用法:
  python main.py "产品描述"
  python main.py --rule "产品描述"
  python main.py --count 5 "产品描述"
  python main.py help
"""
    )


if __name__ == "__main__":
    configure_console()
    args = sys.argv[1:]

    use_rule = "--rule" in args
    if use_rule:
        args.remove("--rule")
    use_llm = not use_rule

    max_competitors = config.DEFAULT_COMPETITOR_COUNT
    if "--count" in args:
        idx = args.index("--count")
        if idx + 1 < len(args):
            max_competitors = int(args[idx + 1])
            args = args[:idx] + args[idx + 2 :]
        else:
            print("--count 需要指定数量")
            sys.exit(1)

    mode = args[0] if args else ""
    if mode in ("help", "-h", "--help"):
        print_help()
        sys.exit(0)
    if not mode:
        print('请提供产品描述，例如: python main.py "飞书"')
        print("运行 python main.py help 查看帮助")
        sys.exit(1)

    if use_llm:
        from core.llm_client import check_llm_backend

        backend = check_llm_backend()
        if not backend["available"]:
            print(f"LLM 后端不可用: {backend['detail']}")
            print("已自动降级为规则模式\n")
            use_llm = False

    asyncio.run(
        run_analysis(
            mode,
            use_llm=use_llm,
            max_competitors=max_competitors,
        )
    )
