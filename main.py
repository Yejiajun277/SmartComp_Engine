#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — 智能竞品分析多Agent系统 主入口

运行示例:
  python3 main.py "飞书"                        # 默认：豆包LLM + 百度搜索
  python3 main.py --rule "飞书"                 # 规则引擎模式（零依赖）
  python3 main.py --count 5 "飞书"              # 指定竞品数量
  python3 main.py --verbose "飞书"              # 详细模式
  python3 main.py help                          # 显示帮助
"""

import asyncio
import sys
import os
import json

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.artifact_store import to_jsonable
from core.orchestrator import Orchestrator
import config


def print_banner():
    banner = """
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║     智能竞品分析 — 多Agent协同系统                                ║
║     Intelligent Competitor Analysis MAS                          ║
║                                                                  ║
║     ◆ 串行采集  ◆ 并行分析  ◆ 差异化策略                        ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
    print(banner)


async def run_analysis(product_description: str,
                       use_llm: bool = True,
                       max_competitors: int = config.DEFAULT_COMPETITOR_COUNT):
    """运行竞品分析"""
    config.ENABLE_LLM = use_llm

    print_banner()
    decision_mode = "🧠 LLM智能分析" if use_llm else "📋 规则引擎分析"
    print(f"  决策模式: {decision_mode}")
    if use_llm:
        from core.llm_client import check_llm_backend
        backend = check_llm_backend()
        provider_label = {"doubao": "豆包"}.get(
            backend["provider"], backend["provider"])
        print(f"  LLM后端: {provider_label}")
        print(f"  模型: {backend['model']}")
        avail_mark = "✅" if backend["available"] else "❌"
        print(f"  后端状态: {avail_mark} {backend['detail']}")
    print(f"  分析目标: {product_description}")
    print(f"  最大竞品数: {max_competitors}")
    print()

    orchestrator = Orchestrator()
    report = await orchestrator.analyze(product_description, max_competitors)

    # 打印统计
    orchestrator.print_stats()

    # 保存报告
    report_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "output"
    )
    os.makedirs(report_dir, exist_ok=True)

    # 保存HTML报告
    html_content = orchestrator.strategy_agent.format_html_report(
        report,
        product_analysis=getattr(orchestrator, "_last_product_analysis", None),
        pricing_analysis=getattr(orchestrator, "_last_pricing_analysis", None),
        market_analysis=getattr(orchestrator, "_last_market_analysis", None),
        competitor_list=getattr(orchestrator, "_last_competitor_list", None),
        competitors_data=getattr(orchestrator, "_last_competitors_data", None),
        timings=orchestrator.get_timings(),
    )

    if orchestrator.artifact_store:
        run_html_path = orchestrator.artifact_store.save_text("report.html", html_content)
        run_json_path = orchestrator.artifact_store.save_json("report.json", report)
        orchestrator.update_artifact_meta()
        print(f"\n💾 本次HTML报告: {run_html_path}")
        print(f"💾 本次JSON报告: {run_json_path}")
        print(f"📦 完整运行归档: {orchestrator.run_dir}")

    # 兼容旧输出路径
    html_path = os.path.join(report_dir, report.product_name + "_analysis_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"💾 兼容HTML报告: {html_path}")

    json_path = os.path.join(report_dir, report.product_name + "_analysis_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(to_jsonable(report), f, ensure_ascii=False, indent=2)
    print(f"💾 兼容JSON报告: {json_path}")

    return report


if __name__ == "__main__":
    args = sys.argv[1:]

    # 解析 --rule 标志
    use_rule = "--rule" in args
    if use_rule:
        args.remove("--rule")
    use_llm = not use_rule

    # 解析 --count 标志
    max_competitors = config.DEFAULT_COMPETITOR_COUNT
    if "--count" in args:
        idx = args.index("--count")
        if idx + 1 < len(args):
            max_competitors = int(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        else:
            print("❌ --count 需要指定数量")
            sys.exit(1)

    # 解析 --verbose 标志
    verbose = "--verbose" in args
    if verbose:
        args.remove("--verbose")

    # 获取产品描述
    mode = args[0] if args else ""

    # 帮助
    if mode in ("help", "-h", "--help"):
        print("""
╔══════════════════════════════════════════════════════════════╗
║  智能竞品分析多Agent系统 — 运行模式                           ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  python3 main.py "产品名"       默认：豆包LLM智能分析        ║
║  python3 main.py --rule "产品名"  规则引擎模式（零依赖）     ║
║  python3 main.py --count 5 "产品名" 指定竞品数量(3~8)       ║
║  python3 main.py --verbose "产品名" 详细模式                 ║
║  python3 main.py help           显示帮助                     ║
║                                                              ║
║  协作架构:                                                   ║
║    串行采集: 竞品发现 → 数据采集                              ║
║    并行分析: 产品分析 + 定价分析 + 市场分析                   ║
║    串行汇总: 策略建议                                        ║
║                                                              ║
║  LLM后端:                                                    ║
║    豆包(默认): 方舟兼容接口，失败自动降级到规则引擎          ║
║    规则引擎(--rule): 关键词匹配+模板，零依赖                 ║
║                                                              ║
║  配置方式(config.py 或环境变量):                             ║
║    LLM_PROVIDER=doubao          选择LLM后端                  ║
║    DOUBAO_API_KEY=xxx           豆包API密钥                  ║
║    DOUBAO_BASE_URL=https://...  方舟接口地址                 ║
║    DOUBAO_MODEL=ep-xxxx         豆包接入点ID                 ║
╚══════════════════════════════════════════════════════════════╝
""")
        sys.exit(0)

    if not mode:
        print("❌ 请提供产品描述，例如: python3 main.py \"飞书\"")
        print("   运行 python3 main.py help 查看帮助")
        sys.exit(1)

    product_description = mode

    # LLM模式校验
    if use_llm:
        from core.llm_client import check_llm_backend
        backend = check_llm_backend()
        if not backend["available"]:
            print(f"⚠️  LLM后端不可用：{backend['detail']}")
            if backend["provider"] == "doubao":
                print("   请设置环境变量：")
                print("     export DOUBAO_API_KEY=your_api_key")
            print("   降级为规则引擎模式运行...\n")
            use_llm = False

    # 运行分析
    asyncio.run(run_analysis(product_description, use_llm=use_llm,
                              max_competitors=max_competitors))
