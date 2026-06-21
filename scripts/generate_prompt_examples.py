# -*- coding: utf-8 -*-
"""
从 dataclass 定义自动生成 JSON 示例，用于 prompt 模板。

用法：
    python scripts/generate_prompt_examples.py

输出：
    prompts/examples/ 目录下的 JSON 文件
"""

import json
import os
from dataclasses import fields, is_dataclass
from datetime import datetime

# 添加项目根目录到 path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.domain import (
    CompetitorInfo, CompetitorList, CompetitorData,
    FeatureItem, PricingTier, FeatureComparison, CompetitiveAdvantage,
    ProductAnalysis, PricingItem, PricingAnalysis,
    MarketShareItem, UserReputation, UserProfile, MarketAnalysis,
    ActionItem, StrategyReport, SubDimension, ProductCategory, DimensionConfig,
)


def dataclass_to_example(cls, depth=0):
    """将 dataclass 转换为示例 JSON 结构"""
    if depth > 3:
        return "..."

    example = {}
    for f in fields(cls):
        if f.name.startswith("_"):
            continue

        field_type = f.type
        type_str = str(field_type)

        # 处理不同类型的示例值
        if field_type == str:
            example[f.name] = _get_example_str(f.name)
        elif field_type == int:
            example[f.name] = 0
        elif field_type == float:
            example[f.name] = 0.0
        elif field_type == bool:
            example[f.name] = True
        elif type_str == "list[str]":
            example[f.name] = _get_example_list(f.name)
        elif "list[" in type_str:
            # 提取内部类型
            try:
                # 获取 __args__ 属性（Python 3.8+）
                if hasattr(field_type, "__args__"):
                    inner_cls = field_type.__args__[0]
                    if is_dataclass(inner_cls):
                        example[f.name] = [dataclass_to_example(inner_cls, depth+1)]
                    else:
                        example[f.name] = []
                else:
                    example[f.name] = []
            except:
                example[f.name] = []
        elif "dict" in type_str:
            # 提取 value 类型
            try:
                if hasattr(field_type, "__args__"):
                    value_cls = field_type.__args__[1]
                    if is_dataclass(value_cls):
                        example[f.name] = {"竞品名1": dataclass_to_example(value_cls, depth+1)}
                    else:
                        example[f.name] = {}
                else:
                    example[f.name] = {}
            except:
                example[f.name] = {}
        else:
            # 尝试作为 dataclass 处理
            try:
                cls_type = eval(field_type) if isinstance(field_type, str) else field_type
                if is_dataclass(cls_type):
                    example[f.name] = dataclass_to_example(cls_type, depth+1)
                else:
                    example[f.name] = str(field_type)
            except:
                example[f.name] = ""

    return example


def _get_example_str(field_name):
    """根据字段名生成示例字符串"""
    examples = {
        "name": "竞品名称",
        "brief": "简要描述",
        "relevance": "HIGH",
        "product_name": "产品名称",
        "product_category": "产品类别",
        "feature": "功能名称",
        "competitor": "竞品名称",
        "our_advantage": "我方优势描述",
        "their_advantage": "对方优势描述",
        "summary": "分析摘要",
        "free_tier": "免费版内容",
        "paid_tier": "付费版内容",
        "pricing_model": "定价模型",
        "share_estimate": "份额估算",
        "trend": "上升/稳定/下降",
        "score": "评分（如8.5/10）",
        "target_audience": "目标用户群体描述",
        "age_range": "年龄分布（如18-35岁为主）",
        "tier_name": "层级名称（如免费版、基础版）",
        "price": "价格",
        "description": "描述",
        "priority": "P0",
        "action": "行动描述",
        "timeline": "时间线",
        "expected_impact": "预期效果",
        "overall_positioning": "整体定位描述",
        "risk_assessment": "风险评估",
        "level1": "一级品类",
        "level2": "二级品类",
        "reasoning": "推断理由",
    }
    return examples.get(field_name, f"{field_name}示例值")


def _get_example_list(field_name):
    """根据字段名生成示例列表"""
    examples = {
        "search_keywords_used": ["关键词1", "关键词2"],
        "keywords": ["正面关键词1", "负面关键词1"],
        "occupation_distribution": ["职业1", "职业2"],
        "use_cases": ["使用场景1", "使用场景2"],
        "pain_points": ["痛点1", "痛点2"],
        "differentiation_points": ["差异化点1", "差异化点2"],
        "value_ranking": ["最高", "第二"],
        "features": ["包含功能1", "包含功能2"],
    }
    return examples.get(field_name, [f"{field_name}示例1"])


def generate_all_examples():
    """生成所有 dataclass 的示例"""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "examples")
    os.makedirs(output_dir, exist_ok=True)

    # 定义要生成示例的 dataclass
    classes = {
        "competitor_info": CompetitorInfo,
        "competitor_list": CompetitorList,
        "competitor_data": CompetitorData,
        "feature_item": FeatureItem,
        "pricing_tier": PricingTier,
        "feature_comparison": FeatureComparison,
        "competitive_advantage": CompetitiveAdvantage,
        "product_analysis": ProductAnalysis,
        "pricing_item": PricingItem,
        "pricing_analysis": PricingAnalysis,
        "market_share_item": MarketShareItem,
        "user_reputation": UserReputation,
        "user_profile": UserProfile,
        "market_analysis": MarketAnalysis,
        "action_item": ActionItem,
        "strategy_report": StrategyReport,
        "sub_dimension": SubDimension,
        "product_category": ProductCategory,
        "dimension_config": DimensionConfig,
    }

    for name, cls in classes.items():
        example = dataclass_to_example(cls)
        output_path = os.path.join(output_dir, f"{name}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(example, f, ensure_ascii=False, indent=2)
        print(f"Generated: {output_path}")

    print(f"\n共生成 {len(classes)} 个示例文件到 {output_dir}")


if __name__ == "__main__":
    generate_all_examples()
