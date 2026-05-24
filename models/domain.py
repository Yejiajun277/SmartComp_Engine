# -*- coding: utf-8 -*-
"""
models/domain.py — 领域模型定义
"""

from dataclasses import dataclass, field
from enum import Enum


class RelevanceLevel(Enum):
    """竞品相关性等级"""
    HIGH = "HIGH"       # 直接竞品
    MEDIUM = "MEDIUM"   # 间接竞品
    LOW = "LOW"         # 潜在竞品


class Priority(Enum):
    """行动优先级"""
    P0 = "P0"   # 最高优先级，立即行动
    P1 = "P1"   # 高优先级，短期行动
    P2 = "P2"   # 中优先级，中期规划
    P3 = "P3"   # 低优先级，长期关注


@dataclass
class CompetitorInfo:
    """竞品基本信息"""
    name: str                               # 竞品名称
    brief: str = ""                         # 简要描述
    relevance: str = "HIGH"                 # 相关性等级


@dataclass
class CompetitorList:
    """竞品发现结果"""
    product_name: str                       # 用户产品名称
    product_category: str = ""              # 产品类别
    competitors: list[CompetitorInfo] = field(default_factory=list)
    search_keywords_used: list[str] = field(default_factory=list)


@dataclass
class CompetitorData:
    """单个竞品的采集数据"""
    name: str                               # 竞品名称
    product_features: str = ""              # 产品功能描述
    pricing_info: str = ""                  # 定价信息
    market_share: str = ""                  # 市场份额
    user_reviews: str = ""                  # 用户评价
    strengths: str = ""                     # 优势
    weaknesses: str = ""                    # 劣势
    channels: str = ""                      # 渠道策略
    search_sources: list[str] = field(default_factory=list)  # 搜索原文


@dataclass
class FeatureComparison:
    """功能对比项"""
    feature: str                            # 功能名称
    values: dict[str, str] = field(default_factory=dict)  # 竞品→状态(✅/🔶/❌)


@dataclass
class CompetitiveAdvantage:
    """竞争优势/劣势"""
    competitor: str                         # 竞品名称
    our_advantage: str = ""                 # 我方优势
    their_advantage: str = ""               # 对方优势


@dataclass
class ProductAnalysis:
    """产品分析结果"""
    feature_matrix: list[FeatureComparison] = field(default_factory=list)
    competitive_advantages: list[CompetitiveAdvantage] = field(default_factory=list)
    differentiation_points: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class PricingItem:
    """定价信息项"""
    competitor: str                         # 竞品名称
    free_tier: str = ""                     # 免费版内容
    paid_tier: str = ""                     # 付费版内容
    pricing_model: str = ""                 # 定价模型


@dataclass
class PricingAnalysis:
    """定价分析结果"""
    pricing_comparison: list[PricingItem] = field(default_factory=list)
    pricing_strategy_analysis: str = ""
    value_ranking: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class MarketShareItem:
    """市场份额项"""
    competitor: str                         # 竞品名称
    share_estimate: str = ""                # 份额估算
    trend: str = ""                         # 趋势


@dataclass
class UserReputation:
    """用户口碑"""
    score: str = ""                         # 评分
    keywords: list[str] = field(default_factory=list)  # 关键词


@dataclass
class MarketAnalysis:
    """市场分析结果"""
    market_share_data: list[MarketShareItem] = field(default_factory=list)
    growth_trends: str = ""
    user_reputation: dict[str, UserReputation] = field(default_factory=dict)
    channel_analysis: str = ""
    summary: str = ""


@dataclass
class ActionItem:
    """行动方案项"""
    priority: str                           # P0/P1/P2/P3
    action: str                             # 行动描述
    timeline: str = ""                      # 时间线
    expected_impact: str = ""               # 预期效果


@dataclass
class StrategyReport:
    """策略建议报告（最终输出）"""
    product_name: str                       # 产品名称
    competitor_count: int = 0               # 竞品数量
    overall_positioning: str = ""           # 整体定位
    differentiation_strategy: dict = field(default_factory=dict)
    action_plan: list[ActionItem] = field(default_factory=list)
    risk_assessment: str = ""
    product_analysis_summary: str = ""      # 产品分析摘要
    pricing_analysis_summary: str = ""      # 定价分析摘要
    market_analysis_summary: str = ""       # 市场分析摘要
    summary: str = ""
    raw_llm_logs: list[dict] = field(default_factory=list)
