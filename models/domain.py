# -*- coding: utf-8 -*-
"""
models/domain.py — 领域模型定义
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Citation:
    """单条引用来源 — 支持信息溯源"""
    id: str                                          # 唯一标识: "{competitor}:q{idx}:r{idx}"
    title: str = ""                                  # 来源标题
    url: str = ""                                    # 来源 URL
    snippet: str = ""                                # 原文摘要
    site_name: str = ""                              # 来源站点名
    query: str = ""                                  # 触发此引用的搜索查询
    competitor: str = ""                             # 关联的竞品名
    collected_at: str = field(default_factory=_now_iso)


@dataclass
class CitationIndex:
    """全局引用索引 — 支持 ID → Citation 反查"""
    citations: dict[str, 'Citation'] = field(default_factory=dict)

    def get(self, citation_id: str) -> 'Citation | None':
        return self.citations.get(citation_id)

    def add(self, citation: 'Citation'):
        self.citations[citation.id] = citation

    def merge(self, other: 'CitationIndex'):
        self.citations.update(other.citations)

    def all_citations(self) -> list['Citation']:
        return list(self.citations.values())


class HallucinationCheckStatus(str, Enum):
    """幻觉检测状态"""
    PASSED = "passed"          # 检测完成，无幻觉
    FOUND = "found"            # 检测完成，发现幻觉
    FAILED = "failed"          # 检测失败（LLM 返回异常）
    SKIPPED = "skipped"        # 未启用（规则引擎模式）


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

    def __post_init__(self):
        valid_levels = {"HIGH", "MEDIUM", "LOW"}
        if self.relevance not in valid_levels:
            raise ValueError(f"relevance must be one of {valid_levels}, got '{self.relevance}'")


@dataclass
class CompetitorList:
    """竞品发现结果"""
    product_name: str                       # 用户产品名称
    product_category: str = ""              # 产品类别
    competitors: list[CompetitorInfo] = field(default_factory=list)
    search_keywords_used: list[str] = field(default_factory=list)


@dataclass
class FeatureItem:
    """产品功能项"""
    name: str = ""                          # 功能名称
    description: str = ""                   # 功能描述
    citations: list[str] = field(default_factory=list)  # 引用 ID 列表


@dataclass
class PricingTier:
    """定价层级"""
    tier_name: str = ""                     # 层级名称（如：免费版、基础版、专业版）
    price: str = ""                         # 价格
    features: list[str] = field(default_factory=list)  # 包含功能
    citations: list[str] = field(default_factory=list)  # 引用 ID 列表


@dataclass
class CompetitorData:
    """单个竞品的采集数据"""
    name: str                               # 竞品名称
    product_features: list[FeatureItem] = field(default_factory=list)  # 产品功能列表
    pricing_tiers: list[PricingTier] = field(default_factory=list)     # 定价层级
    market_share: str = ""                  # 市场份额
    user_reviews: str = ""                  # 用户评价
    strengths: str = ""                     # 优势
    weaknesses: str = ""                    # 劣势
    channels: str = ""                      # 渠道策略
    search_sources: list[str] = field(default_factory=list)  # 搜索原文
    citations: list[Citation] = field(default_factory=list)  # 结构化引用来源


@dataclass
class FeatureComparison:
    """功能对比项"""
    feature: str                            # 功能名称
    values: dict[str, str] = field(default_factory=dict)  # 竞品→状态(✅/🔶/❌)
    citations: list[str] = field(default_factory=list)     # 引用 ID 列表

    def __post_init__(self):
        valid_statuses = {"✅", "🔶", "❌", "✓", "✗", "—", "有", "无", "支持", "不支持", "部分支持"}
        for name, status in self.values.items():
            if status not in valid_statuses:
                # 允许自由文本，但记录警告
                pass


@dataclass
class CompetitiveAdvantage:
    """竞争优势/劣势"""
    competitor: str                         # 竞品名称
    our_advantage: str = ""                 # 我方优势
    their_advantage: str = ""               # 对方优势
    citations: list[str] = field(default_factory=list)     # 引用 ID 列表


@dataclass
class ProductAnalysis:
    """产品分析结果"""
    feature_matrix: list[FeatureComparison] = field(default_factory=list)
    competitive_advantages: list[CompetitiveAdvantage] = field(default_factory=list)
    differentiation_points: list[str] = field(default_factory=list)
    summary: str = ""
    citations: list[str] = field(default_factory=list)     # 汇总引用 ID


@dataclass
class PricingItem:
    """定价信息项"""
    competitor: str                         # 竞品名称
    free_tier: str = ""                     # 免费版内容
    paid_tier: str = ""                     # 付费版内容
    pricing_model: str = ""                 # 定价模型
    citations: list[str] = field(default_factory=list)     # 引用 ID 列表


@dataclass
class PricingAnalysis:
    """定价分析结果"""
    pricing_comparison: list[PricingItem] = field(default_factory=list)
    pricing_strategy_analysis: str = ""
    value_ranking: list[str] = field(default_factory=list)
    summary: str = ""
    citations: list[str] = field(default_factory=list)     # 汇总引用 ID


@dataclass
class MarketShareItem:
    """市场份额项"""
    competitor: str                         # 竞品名称
    share_estimate: str = ""                # 份额估算
    trend: str = ""                         # 趋势
    citations: list[str] = field(default_factory=list)     # 引用 ID 列表


@dataclass
class UserReputation:
    """用户口碑"""
    score: str = ""                         # 评分
    keywords: list[str] = field(default_factory=list)  # 关键词
    citations: list[str] = field(default_factory=list)     # 引用 ID 列表


@dataclass
class UserProfile:
    """用户画像 — 目标用户群体特征"""
    target_audience: str = ""               # 目标用户群体描述
    age_range: str = ""                     # 年龄分布
    occupation_distribution: list[str] = field(default_factory=list)  # 职业分布
    use_cases: list[str] = field(default_factory=list)    # 使用场景
    pain_points: list[str] = field(default_factory=list)  # 核心痛点
    citations: list[str] = field(default_factory=list)    # 引用 ID 列表


@dataclass
class MarketAnalysis:
    """市场分析结果"""
    market_share_data: list[MarketShareItem] = field(default_factory=list)
    growth_trends: str = ""
    user_reputation: dict[str, UserReputation] = field(default_factory=dict)
    user_profiles: dict[str, UserProfile] = field(default_factory=dict)  # 用户画像（新增）
    channel_analysis: str = ""
    summary: str = ""
    citations: list[str] = field(default_factory=list)     # 汇总引用 ID


@dataclass
class ActionItem:
    """行动方案项"""
    priority: str                           # P0/P1/P2/P3
    action: str                             # 行动描述
    timeline: str = ""                      # 时间线
    expected_impact: str = ""               # 预期效果
    citations: list[str] = field(default_factory=list)     # 引用 ID 列表

    def __post_init__(self):
        valid_priorities = {"P0", "P1", "P2", "P3"}
        if self.priority not in valid_priorities:
            raise ValueError(f"priority must be one of {valid_priorities}, got '{self.priority}'")


@dataclass
class QualityIssue:
    """单个质量问题"""
    severity: str          # "critical" / "warning"
    category: str          # "completeness" / "hallucination" / "schema" / "citation"
    field: str             # 问题字段路径
    description: str       # 问题描述
    expected: str = ""     # 期望值
    actual: str = ""       # 实际值
    suggestion: str = ""   # 修复建议


@dataclass
class QualityCheckResult:
    """单次质检结果"""
    phase: str                          # "collection" / "product" / "pricing" / "market" / "strategy"
    target_agent: str                   # 被检查的 Agent ID
    passed: bool                        # 是否通过
    score: float                        # 0-100 质量分数
    issues: list[QualityIssue] = field(default_factory=list)
    checked_at: str = ""                # 检查时间
    attempt: int = 1                    # 第几次检查
    degraded: bool = False              # 是否降级通过
    feedback_to_agent: str = ""         # 给被打回 Agent 的反馈消息
    hallucination_status: str = "skipped"       # HallucinationCheckStatus 的值
    hallucination_score: float = 100.0          # 幻觉检测独立分数


@dataclass
class QATimeline:
    """完整的 QA 时间线 — 嵌入最终报告"""
    checks: list[QualityCheckResult] = field(default_factory=list)
    max_retries: int = 2
    total_retries: int = 0

    def add_check(self, result: QualityCheckResult):
        self.checks.append(result)
        if not result.passed:
            self.total_retries += 1

    def all_passed(self) -> bool:
        return all(c.passed or c.degraded for c in self.checks)


@dataclass
class StrategyReport:
    """策略建议报告（最终输出）"""
    product_name: str                       # 产品名称
    competitor_count: int = 0               # 竞品数量
    target_product_data: CompetitorData | None = None  # 目标产品自身采集数据
    overall_positioning: str = ""           # 整体定位
    differentiation_strategy: dict = field(default_factory=dict)
    action_plan: list[ActionItem] = field(default_factory=list)
    risk_assessment: str = ""
    product_analysis_summary: str = ""      # 产品分析摘要
    pricing_analysis_summary: str = ""      # 定价分析摘要
    market_analysis_summary: str = ""       # 市场分析摘要
    summary: str = ""
    raw_llm_logs: list[dict] = field(default_factory=list)
    citation_index: CitationIndex = field(default_factory=CitationIndex)  # 全局引用索引
    qa_timeline: QATimeline = field(default_factory=QATimeline)           # QA 质检时间线


@dataclass
class SubDimension:
    """单个子维度"""
    name: str                               # 维度名称（2-6字）
    description: str = ""                   # 维度说明


@dataclass
class ProductCategory:
    """产品品类"""
    level1: str = ""                        # 一级品类（如：消费电子）
    level2: str = ""                        # 二级品类（如：智能手机）


@dataclass
class DimensionConfig:
    """动态维度配置 — DimensionAgent 输出"""
    product_category: ProductCategory = field(default_factory=ProductCategory)
    product_sub_dimensions: list[SubDimension] = field(default_factory=list)
    pricing_sub_dimensions: list[SubDimension] = field(default_factory=list)
    reasoning: str = ""                     # 品类推断理由
