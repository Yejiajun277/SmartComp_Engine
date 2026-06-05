# 智能竞品分析多Agent系统

## 一、系统总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      竞品分析协同环境                              │
│                                                                  │
│                        ┌──────────────┐                          │
│                        │  竞品发现     │                          │
│                        │  Agent       │                          │
│                        │ (搜索+筛选)  │                          │
│                        └──────┬───────┘                          │
│                               │ 发现N个竞品                      │
│                               ▼                                  │
│                        ┌──────────────┐                          │
│                        │  数据采集     │                          │
│                        │  Agent       │                          │
│                        │ (多源抓取)   │                          │
│                        └──────┬───────┘                          │
│                               │ 逐竞品采集数据                    │
│                               ▼                                  │
│                    ┌─────────────────────┐                       │
│                    │  质量检查 Agent      │ ← QA Gate 2           │
│                    │ (完整性+幻觉检测)    │   不通过则打回重做       │
│                    └─────────┬───────────┘                       │
│                               ▼                                  │
│                        ┌──────────────┐                          │
│                        │  维度生成     │                          │
│                        │  Agent       │                          │
│                        │ (品类推断)   │                          │
│                        └──────┬───────┘                          │
│                               │ 动态子维度                       │
│              ┌────────────────┼────────────────┐                 │
│              ▼                ▼                ▼                 │
│     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│     │  产品分析     │  │  定价分析     │  │  市场分析     │       │
│     │  Agent       │  │  Agent       │  │  Agent       │       │
│     │ (功能矩阵)   │  │ (价格策略)   │  │ (份额趋势)   │       │
│     └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│            │                 │                 │                │
│            └────────────────┼─────────────────┘                │
│                             ▼                                   │
│                    ┌─────────────────────┐                       │
│                    │  质量检查 Agent      │ ← QA Gate 3           │
│                    │ (三路并行质检)       │   不通过则打回重做       │
│                    └─────────┬───────────┘                       │
│                             ▼                                   │
│                    ┌──────────────┐                             │
│                    │  策略建议     │                             │
│                    │  Agent       │                             │
│                    │ (综合+建议)  │                             │
│                    └──────┬───────┘                             │
│                           ▼                                     │
│                    ┌─────────────────────┐                       │
│                    │  质量检查 Agent      │ ← QA Gate 4           │
│                    │ (策略报告质检)       │   不通过则打回重做       │
│                    └─────────┬───────────┘                       │
│                             ▼                                   │
│                    StrategyReport                                │
│                  (HTML + JSON + 纯文本)                          │
│                                                                  │
│    ┌─────────────────────────┐                                  │
│    │ 豆包 (Volcengine)       │                                  │
│    │ LLM + 联网搜索          │                                  │
│    └─────────────────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
```

**协作模式**：混合（串行采集 → QA质检 → 串行维度生成 → 并行分析 → QA质检 → 串行汇总 → QA质检）

**核心理念**：
- **两段式采集**：先发现竞品列表，再逐竞品深度采集，避免盲目搜索
- **动态维度生成**：根据产品品类自动生成分析子维度，替代硬编码维度
- **三维并行分析**：产品/定价/市场三个维度独立，结果JSON格式传递给策略Agent
- **竞品矩阵表**：产品分析Agent输出功能对比矩阵（✅/❌/🔶）
- **策略Agent看到全貌**：三份分析报告汇聚后一次性输入，保证策略建议的系统性
- **全链路溯源**：每条数据附带引用ID（Citation），贯穿采集→分析→报告全流程
- **全流程质量保障**：QualityAgent在采集、分析、策略三个阶段设置QA Gate，支持打回重做和降级通过

## 二、Agent角色定义

### 1. 竞品发现Agent（DiscoveryAgent）
- **职责**：根据用户产品描述，搜索并筛选出3~8个核心竞品
- **LLM调用**：2次（关键词生成 + 结果筛选）
- **外部工具**：豆包Responses API联网搜索
- **输入**：用户产品描述（string）、最大竞品数（int）
- **输出**：CompetitorList（竞品名称+简介列表）
- **降级策略**：直接使用产品描述作为搜索关键词，取搜索结果前5个

### 2. 数据采集Agent（CollectionAgent）
- **职责**：对每个竞品，采集产品功能、定价、用户评价、市场份额等信息
- **LLM调用**：1+N次（逐竞品汇总，N=竞品数）
- **外部工具**：豆包Responses API联网搜索
- **输入**：CompetitorList + 用户产品描述 + 可选feedback（QA打回时的改进提示）
- **输出**：dict[str, CompetitorData]（每竞品一份数据，含结构化Citation列表）
- **降级策略**：直接使用固定搜索模板采集
- **特殊能力**：`get_search_texts()` 返回原始搜索文本，供QualityAgent做幻觉检测

### 3. 维度生成Agent（DimensionAgent）
- **职责**：推断产品品类，为产品分析和定价分析生成动态子维度
- **LLM调用**：1次
- **外部工具**：无
- **输入**：用户产品描述 + CompetitorList
- **输出**：DimensionConfig（含ProductCategory + product_sub_dimensions + pricing_sub_dimensions）
- **降级策略**：使用预设的通用维度模板

### 4. 产品分析Agent（ProductAgent）
- **职责**：逐竞品对比功能矩阵，标注优势/劣势/差异点
- **LLM调用**：1次
- **外部工具**：无
- **输入**：全部竞品数据 + DimensionAgent生成的产品子维度 + 可选feedback
- **输出**：ProductAnalysis（含功能对比矩阵 feature_matrix: list[FeatureComparison]）
- **降级策略**：基于关键词匹配生成简单对比

### 5. 定价分析Agent（PricingAgent）
- **职责**：对比各竞品定价策略、促销模式、性价比
- **LLM调用**：1次
- **外部工具**：无
- **输入**：全部竞品数据 + DimensionAgent生成的定价子维度 + 可选feedback
- **输出**：PricingAnalysis（含定价对比表 pricing_comparison: list[PricingItem]）
- **降级策略**：提取价格数字进行简单排序

### 6. 市场分析Agent（MarketAgent）
- **职责**：分析市场份额、增长趋势、用户口碑、用户画像、渠道策略
- **LLM调用**：1次
- **外部工具**：无
- **输入**：全部竞品数据 + 可选feedback
- **输出**：MarketAnalysis（含market_share_data、user_reputation、user_profiles、channel_analysis）
- **降级策略**：基于采集数据中的关键词统计

### 7. 策略建议Agent（StrategyAgent）
- **职责**：综合三维分析，输出差异化定位建议和行动方案，生成HTML/JSON报告
- **LLM调用**：1次
- **外部工具**：无
- **输入**：ProductAnalysis + PricingAnalysis + MarketAnalysis + 全部竞品数据 + 可选feedback
- **输出**：StrategyReport（含纯文本报告 + HTML报告 + JSON报告）
- **降级策略**：基于SWOT模板生成简单建议
- **特殊能力**：`format_html_report()` 生成独立HTML页面（~1100行内联CSS模板）

### 8. 质量检查Agent（QualityAgent）
- **职责**：全流程质量保障——完整性检查、幻觉检测、引用验证
- **LLM调用**：每次检查1次（幻觉检测）
- **外部工具**：无
- **输入**：被检查Agent的输出数据 + 原始采集数据
- **输出**：QualityCheckResult（含score、issues列表、passed/degraded状态）
- **类常量**：`MAX_RETRIES = 2`，`PASS_SCORE = 70`
- **评分规则**：critical问题-20分，warning问题-5分，满分100分，底线0分
- **检查方法**：
  - `check_collection()` — 采集数据完整性 + 幻觉检测
  - `check_analysis()` — 分析结果完整性 + 幻觉检测（产品/定价/市场三路共用）
  - `check_strategy()` — 策略报告完整性 + 幻觉检测
- **反馈机制**：`build_feedback()` 将质检问题转化为给被打回Agent的改进提示

## 三、数据流与JSON格式

### 3.1 竞品发现结果（Phase 1）

```json
{
    "product_name": "飞书",
    "product_category": "企业协同办公平台",
    "competitors": [
        {
            "name": "钉钉",
            "brief": "阿里巴巴旗下企业协同平台，市占率领先",
            "relevance": "HIGH"
        },
        {
            "name": "企业微信",
            "brief": "腾讯旗下企业通讯与协同平台",
            "relevance": "HIGH"
        }
    ],
    "search_keywords_used": ["飞书竞品", "企业协同办公平台对比"]
}
```

### 3.2 数据采集结果（Phase 2）

```json
{
    "钉钉": {
        "name": "钉钉",
        "product_features": [
            {
                "name": "即时通讯",
                "description": "支持文字、语音、视频通话，群组管理",
                "citations": ["钉钉:q0:r0"]
            },
            {
                "name": "审批流程",
                "description": "自定义审批模板，支持OA流程自动化",
                "citations": ["钉钉:q0:r1"]
            }
        ],
        "pricing_tiers": [
            {
                "tier_name": "免费版",
                "price": "0元",
                "features": ["基础通讯", "考勤打卡"],
                "citations": ["钉钉:q1:r0"]
            },
            {
                "tier_name": "专业版",
                "price": "9800元/年",
                "features": ["高级审批", "数据报表"],
                "citations": ["钉钉:q1:r1"]
            }
        ],
        "market_share": "超过6亿用户，1000万+企业组织",
        "user_reviews": "流程审批功能强大，但界面较复杂...",
        "strengths": "生态完善、用户基数大、阿里背书",
        "weaknesses": "体验偏重、学习成本高",
        "channels": "直销+渠道代理+阿里云生态",
        "search_sources": ["搜索结果1...", "搜索结果2..."],
        "citations": [
            {
                "id": "钉钉:q0:r0",
                "title": "钉钉产品功能介绍",
                "url": "https://...",
                "snippet": "...",
                "site_name": "钉钉官网",
                "query": "钉钉产品功能",
                "competitor": "钉钉",
                "collected_at": "2026-06-05T10:00:00"
            }
        ]
    }
}
```

### 3.3 维度生成结果（Phase 2.5）

```json
{
    "product_category": {
        "level1": "企业服务",
        "level2": "协同办公平台"
    },
    "product_sub_dimensions": [
        {"name": "即时通讯", "description": "消息、群组、音视频通话能力"},
        {"name": "文档协作", "description": "在线文档、表格、演示的协同编辑"},
        {"name": "流程审批", "description": "OA审批、自定义流程、电子签章"},
        {"name": "开放生态", "description": "API、插件市场、第三方集成"}
    ],
    "pricing_sub_dimensions": [
        {"name": "定价模式", "description": "免费增值/纯订阅/按量付费"},
        {"name": "免费版能力", "description": "免费版包含的功能范围"},
        {"name": "企业版价格", "description": "面向企业的大客户定价"},
        {"name": "增值服务", "description": "额外付费的功能模块或服务"}
    ],
    "reasoning": "该品类的核心差异化维度是..."
}
```

### 3.4 产品分析结果（Phase 3）

```json
{
    "feature_matrix": [
        {
            "feature": "即时通讯",
            "values": {"飞书": "✅", "钉钉": "✅", "企业微信": "✅"},
            "citations": []
        },
        {
            "feature": "文档协作",
            "values": {"飞书": "✅", "钉钉": "🔶", "企业微信": "🔶"},
            "citations": ["钉钉:q0:r2"]
        }
    ],
    "competitive_advantages": [
        {
            "competitor": "钉钉",
            "our_advantage": "文档协作体验远超",
            "their_advantage": "审批流程更成熟",
            "citations": ["钉钉:q0:r0"]
        }
    ],
    "differentiation_points": ["AI助手深度集成", "跨国协作能力"],
    "summary": "飞书在协作体验上领先，钉钉在流程管控上更强...",
    "citations": ["钉钉:q0:r0", "企业微信:q0:r0"]
}
```

### 3.5 定价分析结果（Phase 3）

```json
{
    "pricing_comparison": [
        {
            "competitor": "飞书",
            "free_tier": "基础功能免费",
            "paid_tier": "商业版50元/人/月",
            "pricing_model": "按人头订阅",
            "citations": ["飞书:q0:r0"]
        }
    ],
    "pricing_strategy_analysis": "整体市场从免费增值模式向订阅制转变...",
    "value_ranking": ["飞书", "钉钉", "企业微信"],
    "summary": "飞书定价中等偏上，但功能覆盖面广...",
    "citations": []
}
```

### 3.6 市场分析结果（Phase 3）

```json
{
    "market_share_data": [
        {
            "competitor": "钉钉",
            "share_estimate": "40%",
            "trend": "稳定",
            "citations": ["钉钉:q2:r0"]
        }
    ],
    "growth_trends": "整体市场年增长率约25%...",
    "user_reputation": {
        "钉钉": {
            "score": "7.5/10",
            "keywords": ["流程强", "界面重"],
            "citations": ["钉钉:q3:r0"]
        },
        "飞书": {
            "score": "8.2/10",
            "keywords": ["体验好", "功能新"],
            "citations": []
        }
    },
    "user_profiles": {
        "钉钉": {
            "target_audience": "中小企业管理者",
            "age_range": "25-45岁",
            "occupation_distribution": ["行政管理", "HR", "项目经理"],
            "use_cases": ["考勤管理", "审批流程", "团队沟通"],
            "pain_points": ["流程复杂", "跨部门协同困难"],
            "citations": ["钉钉:q4:r0"]
        }
    },
    "channel_analysis": "直销为主，渠道代理为辅...",
    "summary": "钉钉市占率领先但增速放缓，飞书增速最快...",
    "citations": []
}
```

### 3.7 策略建议报告（Phase 4）

```json
{
    "product_name": "飞书",
    "competitor_count": 5,
    "overall_positioning": "飞书应定位为'体验优先的智能协同平台'...",
    "differentiation_strategy": {
        "core_differentiator": "AI原生协同体验",
        "supporting_points": ["智能文档", "多维表格", "AI助手"]
    },
    "action_plan": [
        {
            "priority": "P0",
            "action": "强化AI助手差异化，打造'AI原生办公'心智",
            "timeline": "Q1-Q2",
            "expected_impact": "建立技术领先认知",
            "citations": []
        }
    ],
    "risk_assessment": "钉钉可能跟进AI功能，需保持迭代速度...",
    "product_analysis_summary": "飞书在协作体验上领先...",
    "pricing_analysis_summary": "飞书定价中等偏上...",
    "market_analysis_summary": "钉钉市占率领先但增速放缓...",
    "summary": "基于三维分析，建议飞书走'AI原生+体验优先'差异化路线...",
    "raw_llm_logs": [],
    "citation_index": {
        "citations": {
            "钉钉:q0:r0": {"id": "钉钉:q0:r0", "title": "...", "url": "..."}
        }
    },
    "qa_timeline": {
        "checks": [
            {
                "phase": "collection",
                "target_agent": "collection_agent",
                "passed": true,
                "score": 85.0,
                "issues": [],
                "checked_at": "2026-06-05T10:05:00",
                "attempt": 1,
                "degraded": false,
                "feedback_to_agent": ""
            }
        ],
        "max_retries": 2,
        "total_retries": 0
    }
}
```

### 3.8 质量检查结果（QA Gate）

```json
{
    "phase": "product",
    "target_agent": "product_agent",
    "passed": false,
    "score": 60.0,
    "issues": [
        {
            "severity": "critical",
            "category": "hallucination",
            "field": "feature_matrix[0].values.钉钉",
            "description": "标注钉钉支持'AI写作'功能，但原始搜索数据中未找到相关证据",
            "expected": "有搜索来源支撑",
            "actual": "无对应引用",
            "suggestion": "移除无证据支持的功能标注或补充搜索验证"
        },
        {
            "severity": "warning",
            "category": "completeness",
            "field": "feature_matrix",
            "description": "功能矩阵仅包含3个维度，建议补充至6-8个",
            "expected": "6-8个功能维度",
            "actual": "3个功能维度",
            "suggestion": "参考DimensionAgent生成的子维度扩展矩阵"
        }
    ],
    "checked_at": "2026-06-05T10:10:00",
    "attempt": 1,
    "degraded": false,
    "feedback_to_agent": "请修复以下问题：1. [critical] 标注钉钉支持'AI写作'功能..."
}
```

## 四、各Agent核心提示词推导

### 4.1 竞品发现Agent提示词推导

**推导思路**：竞品发现是整个流程的起点，需要"两步走"策略——先生成搜索关键词，再从搜索结果中筛选竞品。一次性让LLM完成"生成关键词+搜索+筛选"容易信息过载。

**推导过程**：

1. **第一步：生成搜索关键词**（prompt_keywords模板）
   - 输入：用户产品描述 + 目标数量
   - 核心指令：根据产品描述，生成3-5组竞品搜索关键词
   - 关键约束：关键词要覆盖不同维度（同类产品、替代方案、上下游产品）
   - 输出格式：关键词列表JSON

2. **第二步：筛选核心竞品**（prompt_filter模板）
   - 输入：搜索结果汇总 + 最大竞品数
   - 核心指令：从搜索结果中识别3~8个核心竞品
   - 关键约束：去重、评估相关性（HIGH/MEDIUM/LOW）、排除自身
   - 输出格式：CompetitorList JSON

**系统提示词核心要素**：
```
角色：竞品发现专家
原则：关键词多样化 / 结果去重 / 相关性评估 / 排除自身
输出：严格JSON，使用 {{example:competitor_list}} 示例格式
```

### 4.2 数据采集Agent提示词推导

**推导思路**：数据采集需要逐竞品搜索+LLM结构化汇总。每个竞品覆盖功能/定价/市场/口碑/渠道五个维度，输出结构化数据（含引用溯源）。

**推导过程**：

1. **逐竞品搜索+汇总**（prompt_collect模板）
   - 对每个竞品：生成搜索查询 → 调用搜索 → LLM汇总提取结构化数据
   - 输出：CompetitorData JSON（含FeatureItem列表、PricingTier列表、Citation列表）

**系统提示词核心要素**：
```
角色：竞品数据采集专家
采集维度：产品功能 / 定价体系 / 市场份额 / 用户评价 / 渠道策略
原则：多源交叉验证 / 数据可溯源 / 区分事实与观点 / 缺失数据标注
输出：严格JSON，使用 {{example:competitor_data}} 示例格式
```

### 4.3 维度生成Agent提示词推导

**推导思路**：不同品类的竞品对比角度差异很大——SaaS产品看功能覆盖和集成能力，消费电子看硬件参数和设计，食品看配方和渠道。硬编码维度无法覆盖所有品类，因此需要一个前置Agent根据产品描述和竞品列表动态推断品类、生成专属分析维度。

**推导过程**：

1. **品类推断**（prompt_generate模板）：从产品描述和竞品名称中推断一级/二级品类
2. **产品子维度生成**：根据品类特征，生成4-6个最具区分度的产品功能对比维度
3. **定价子维度生成**：根据品类特征，生成4-6个定价策略对比维度
4. **维度质量约束**：维度名称简洁（2-6字），维度间不重叠，每个维度附带说明

**系统提示词核心要素**：
```
角色：产品品类分析和维度设计专家
原则：维度简洁 / 不重叠 / 选择最具区分度的对比角度
输出：严格JSON，使用 {{example:dimension_config}} 示例格式
```

### 4.4 产品分析Agent提示词推导

**推导思路**：产品分析的核心产出是"功能对比矩阵"——这是一个二维表格（竞品×功能），每个交叉点标注✅/❌/🔶。维度来源由DimensionAgent动态提供。

**推导过程**：

1. **功能维度来源**：使用DimensionAgent生成的产品子维度（通过`set_sub_dimensions()`注入）
2. **矩阵填充**：逐功能逐竞品标注支持程度（✅完整支持 / 🔶部分支持 / ❌不支持）
3. **优劣势标注**：识别我方优势和对方优势
4. **差异点提炼**：找出独特的、不可替代的差异

**系统提示词核心要素**：
```
角色：产品竞品分析专家
核心产出：功能对比矩阵（✅/🔶/❌），8-15个维度
分析维度：由DimensionAgent动态提供（{sub_dimensions}变量注入）
原则：客观对比 / 突出差异 / 矩阵可读
输出：严格JSON，使用 {{example:product_analysis}} 示例格式
```

### 4.5 定价分析Agent提示词推导

**推导思路**：定价分析需要"横向对比+纵向解读"——横向比价格数字，纵向解读定价策略背后的商业逻辑。维度来源由DimensionAgent动态提供。

**推导过程**：

1. **维度来源**：使用DimensionAgent生成的定价子维度（通过`set_sub_dimensions()`注入）
2. **价格提取**：从采集数据中提取各竞品的PricingTier列表
3. **策略分类**：识别定价模型（免费增值/纯订阅/按量付费/混合）
4. **性价比评估**：功能覆盖 vs 价格的性价比排序
5. **趋势判断**：市场整体定价趋势

**系统提示词核心要素**：
```
角色：定价策略分析专家
分析维度：由DimensionAgent动态提供（{sub_dimensions}变量注入）
原则：数字说话 / 策略解读 / 趋势判断
输出：严格JSON，使用 {{example:pricing_analysis}} 示例格式
```

### 4.6 市场分析Agent提示词推导

**推导思路**：市场分析需要"定量+定性"结合——定量看市场份额和增长数据，定性看用户口碑和用户画像。由于公开数据可能不完整，需要明确标注数据来源和置信度。

**推导过程**：

1. **份额估算**：从搜索结果中提取市场份额信息（MarketShareItem列表）
2. **增长趋势**：分析各竞品的增长态势
3. **口碑分析**：提取用户评价关键词和评分（UserReputation字典）
4. **用户画像**：分析目标用户群体特征（UserProfile字典，含年龄、职业、使用场景、痛点）
5. **渠道解读**：分析销售渠道和合作伙伴

**系统提示词核心要素**：
```
角色：市场研究分析专家
分析维度：市场份额 / 增长趋势 / 用户口碑 / 用户画像 / 渠道策略 / 竞争格局
原则：数据溯源 / 置信度标注 / 趋势重于快照
输出：严格JSON，使用 {{example:market_analysis}} 示例格式
```

### 4.7 策略建议Agent提示词推导

**推导思路**：策略建议是汇聚环节，需要"融会贯通"——不是简单拼接三份分析，而是从三维数据中提炼出统一的战略叙事。核心产出是差异化定位+行动方案+HTML/JSON报告。

**推导过程**：

1. **三维交叉**：产品优势+定价空间+市场机会 → 差异化定位
2. **优先级排序**：按影响力和可行性排列行动方案（P0-P3）
3. **风险评估**：基于竞品动态预判风险
4. **行动方案**：具体到时间线和预期效果（ActionItem列表）
5. **报告生成**：格式化为纯文本终端输出和完整HTML页面

**系统提示词核心要素**：
```
角色：竞争战略顾问
原则：三维融合 / 差异化优先 / 行动导向 / 风险预判
报告结构：定位→差异化→行动计划→风险评估
输出：严格JSON，使用 {{example:strategy_report}} 示例格式
```

### 4.8 质量检查Agent提示词推导

**推导思路**：质量检查是全流程保障机制，需要在每个关键阶段检测两类问题——数据完整性（字段缺失、维度不足）和幻觉风险（LLM编造无来源支撑的信息）。幻觉检测通过对比LLM输出与原始搜索文本来实现。

**推导过程**：

1. **完整性检查**（规则引擎，无需LLM）：
   - 字段非空检查
   - 维度数量合理性（feature_matrix应有6-15项）
   - 引用ID有效性

2. **幻觉检测**（LLM调用）：
   - 对比分析结果中的具体数据点与原始搜索文本
   - 标注无来源支撑的断言
   - 检查引用ID是否真实存在

3. **评分机制**：
   - critical问题：-20分/个
   - warning问题：-5分/个
   - 满分100分，底线0分
   - 70分以上通过

4. **反馈生成**（prompt_build_feedback模板）：
   - 将QualityCheckResult中的issues转化为给被打回Agent的改进提示
   - 包含具体问题描述、期望值、修复建议

**系统提示词核心要素**：
```
角色：质量检查专家
检查维度：完整性 / 幻觉检测 / 引用有效性
原则：客观评分 / 问题可操作 / 优先critical
输出：严格JSON，使用 {{example:quality_issue}} 相关示例格式
```

## 五、技术实现方案

### 技术栈
- **语言**：Python 3.12+
- **Agent框架**：基于原生Python + asyncio实现（零框架依赖）
- **LLM调用**：豆包（Volcengine）OpenAI兼容API
- **搜索**：豆包Responses API + web_search工具（联网搜索）
- **并行执行**：asyncio.gather（三维分析并行阶段 + QA并行质检阶段）
- **数据格式**：dataclass（Agent间类型安全传递）
- **报告输出**：HTML（独立页面，内联CSS）+ JSON

### 项目结构
```
SmartComp_Engine/
├── design.md                    # 本设计文档
├── main.py                      # 主入口（CLI，手动argv解析）
├── config.py                    # 配置（豆包LLM + 搜索参数 + 自定义.env加载器）
├── requirements.txt             # 依赖清单（仅 requests>=2.28.0）
├── core/
│   ├── __init__.py              # 导出 llm_call, parse_llm_json, get_llm_stats
│   ├── llm_client.py            # 豆包LLM调用封装（重试、JSON提取、统计）
│   ├── search_client.py         # 豆包联网搜索客户端（单次+批量，Responses API）
│   ├── prompt_loader.py         # 提示词模板加载器（.md格式，##节分割，内存缓存，{{example:xxx}}注入）
│   └── orchestrator.py          # 主控编排器（混合协作模式 + QA Gate循环）
├── agents/
│   ├── __init__.py              # 导出 BaseAgent
│   ├── base_agent.py            # Agent基类（ask_llm、ask_llm_json、Citation工具）
│   ├── discovery_agent.py       # 竞品发现Agent（Phase 1）
│   ├── collection_agent.py      # 数据采集Agent（Phase 2）
│   ├── dimension_agent.py       # 维度生成Agent（Phase 2.5）
│   ├── product_agent.py         # 产品分析Agent（Phase 3）
│   ├── pricing_agent.py         # 定价分析Agent（Phase 3）
│   ├── market_agent.py          # 市场分析Agent（Phase 3）
│   ├── strategy_agent.py        # 策略建议Agent（Phase 4，含HTML报告生成）
│   └── quality_agent.py         # 质量检查Agent（QA Gate 2/3/4）
├── models/
│   ├── __init__.py
│   └── domain.py                # 领域模型（20个dataclass + 2个enum）
├── prompts/                     # 提示词模板（.md格式，##节分割）
│   ├── discovery_agent.md       # system_prompt + prompt_keywords + prompt_filter
│   ├── collection_agent.md      # system_prompt + prompt_collect
│   ├── dimension_agent.md       # system_prompt + prompt_generate
│   ├── product_agent.md         # system_prompt + prompt_analyze
│   ├── pricing_agent.md         # system_prompt + prompt_analyze
│   ├── market_agent.md          # system_prompt + prompt_analyze
│   ├── strategy_agent.md        # system_prompt + prompt_strategy
│   ├── quality_agent.md         # system_prompt + prompt_check_collection/analysis/strategy + prompt_build_feedback
│   └── examples/                # 20个JSON示例文件（通过{{example:xxx}}注入prompt）
│       ├── action_item.json
│       ├── competitive_advantage.json
│       ├── competitor_data.json
│       ├── competitor_info.json
│       ├── competitor_list.json
│       ├── dimension_config.json
│       ├── feature_comparison.json
│       ├── feature_item.json
│       ├── market_analysis.json
│       ├── market_share_item.json
│       ├── pricing_analysis.json
│       ├── pricing_item.json
│       ├── pricing_tier.json
│       ├── product_analysis.json
│       ├── product_category.json
│       ├── strategy_report.json
│       ├── sub_dimension.json
│       ├── user_profile.json
│       └── user_reputation.json
├── scripts/
│   └── generate_prompt_examples.py  # 从dataclass自动生成prompts/examples/*.json
└── output/                      # 分析报告输出目录（HTML + JSON）
```

### 运行方式
```bash
# 默认：豆包LLM + 联网搜索
python3 main.py "飞书"

# 规则引擎模式（零LLM依赖，零成本运行）
python3 main.py --rule "飞书"

# 指定竞品数量（3-8）
python3 main.py --count 5 "飞书"

# 详细模式（输出中间结果）
python3 main.py --verbose "飞书"

# 帮助
python3 main.py help
```

### 环境配置

`.env`文件（已gitignore）：
```
LLM_PROVIDER=doubao
DOUBAO_API_KEY=your_api_key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=your_endpoint_id
SEARCH_RECENCY=month
SEARCH_DELAY_SECONDS=2.0
SEARCH_MAX_OUTPUT_TOKENS=2048
```

**config.py 内部常量**：

| 变量 | 来源 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | env | `"doubao"` |
| `DOUBAO_API_KEY` | env | `""` |
| `DOUBAO_BASE_URL` | env | `"https://ark.cn-beijing.volces.com/api/v3"` |
| `DOUBAO_MODEL` | env | 模型endpoint ID |
| `SEARCH_RECENCY` | env | `"month"` |
| `SEARCH_DELAY_SECONDS` | env | `2.0` |
| `SEARCH_MAX_OUTPUT_TOKENS` | env | `2048` |
| `ENABLE_LLM` | 代码 | `True`（`--rule` 模式切换为False） |
| `MIN_COMPETITORS` | 代码 | `3` |
| `MAX_COMPETITORS` | 代码 | `8` |
| `DEFAULT_COMPETITOR_COUNT` | 代码 | `5` |
| `LLM_TEMPERATURE` | 代码 | `0.3` |
| `LLM_MAX_TOKENS` | 代码 | `4096` |

## 六、Agent间数据传递规范

```
DiscoveryAgent ──(CompetitorList)──→ [串行]
                                          │
CollectionAgent ──(dict[str, CompetitorData])──→ [串行]
                                                      │
                                            QA Gate 2 (QualityAgent)
                                          不通过 → 打回CollectionAgent重做
                                                      │
                                                      ▼
DimensionAgent ──(DimensionConfig)──→ [串行]
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                     ProductAgent   PricingAgent   MarketAgent
                    (+子维度)      (+子维度)        [并行]
                         │            │            │
                         └────────────┼────────────┘
                                      │
                              QA Gate 3 (QualityAgent)
                          三路并行质检，不通过分别打回重做
                                      │
                                      ▼
                               StrategyAgent
                                      │
                              QA Gate 4 (QualityAgent)
                          不通过 → 打回StrategyAgent重做
                                      │
                                      ▼
                              StrategyReport
                          (HTML + JSON + 纯文本)
```

**关键约束**：
- Phase 1 → Phase 2：竞品列表直接传递
- Phase 2 → QA Gate 2：采集数据 + 原始搜索文本传递给QualityAgent
- QA Gate 2 → Phase 2.5：通过质检的竞品列表传递给DimensionAgent
- Phase 2.5 → Phase 3：DimensionAgent的子维度分别注入ProductAgent和PricingAgent的prompt（`set_sub_dimensions()`方法）
- Phase 3 并行三路：输入相同（竞品数据），输出独立（三份分析报告）
- Phase 3 → QA Gate 3：三份分析报告并行提交QualityAgent质检
- QA Gate 3 → Phase 4：通过质检的三份分析报告汇聚后传给StrategyAgent
- Phase 4 → QA Gate 4：策略报告提交QualityAgent质检
- 全链路：Citation对象从采集阶段产生，经分析阶段引用，最终汇总到StrategyReport.citation_index
- 全链路：QA检查结果汇总到StrategyReport.qa_timeline

## 七、LLM调用统计

| Agent | 调用次数 | 调用策略 | 降级方案 |
|-------|---------|---------|---------|
| DiscoveryAgent | 2次 | 关键词生成1次 + 结果筛选1次 | 直接使用产品描述搜索 |
| CollectionAgent | N次 | 逐竞品汇总N次 | 固定模板搜索 |
| DimensionAgent | 1次 | 品类推断+维度生成1次 | 通用维度模板 |
| ProductAgent | 1次 | 全量数据+子维度1次 | 关键词匹配对比 |
| PricingAgent | 1次 | 全量数据+子维度1次 | 价格数字提取排序 |
| MarketAgent | 1次 | 全量数据1次 | 关键词频率统计 |
| StrategyAgent | 1次 | 三维分析1次 | SWOT模板填充 |
| QualityAgent | 3~9次 | 每个QA Gate 1次（幻觉检测），重试时额外1次/次 | 规则引擎完整性检查（无需LLM） |
| **总计** | **10+N ~ 16+N次** | N=竞品数（默认5），QA重试0~6次 | — |

**说明**：
- QualityAgent的完整性检查基于规则引擎，不消耗LLM调用
- QualityAgent的幻觉检测需要LLM调用，每个QA Gate至少1次
- QA重试次数上限：每个Gate最多2次（MAX_RETRIES），超限则降级通过
- 最坏情况（所有Gate都重试满）：QualityAgent调用 3×(1+2) = 9次
- 最好情况（所有Gate一次通过）：QualityAgent调用 3次

## 八、领域模型一览

### 枚举类型
- `RelevanceLevel` — HIGH / MEDIUM / LOW（竞品相关性等级）
- `Priority` — P0 / P1 / P2 / P3（行动优先级）

### 数据模型分类

**引用溯源**：
- `Citation` — 单条引用来源（id, title, url, snippet, site_name, query, competitor, collected_at）
- `CitationIndex` — 全局引用索引（支持get/add/merge/all_citations操作）

**竞品发现**：
- `CompetitorInfo` — 竞品基本信息（name, brief, relevance）
- `CompetitorList` — 竞品发现结果（product_name, product_category, competitors, search_keywords_used）

**数据采集**：
- `FeatureItem` — 产品功能项（name, description, citations）
- `PricingTier` — 定价层级（tier_name, price, features, citations）
- `CompetitorData` — 单竞品采集数据（name, product_features, pricing_tiers, market_share, user_reviews, strengths, weaknesses, channels, search_sources, citations）

**维度生成**：
- `SubDimension` — 单个子维度（name, description）
- `ProductCategory` — 产品品类（level1, level2）
- `DimensionConfig` — 动态维度配置（product_category, product_sub_dimensions, pricing_sub_dimensions, reasoning）

**产品分析**：
- `FeatureComparison` — 功能对比项（feature, values: dict[str, str], citations）
- `CompetitiveAdvantage` — 竞争优势/劣势（competitor, our_advantage, their_advantage, citations）
- `ProductAnalysis` — 产品分析结果（feature_matrix, competitive_advantages, differentiation_points, summary, citations）

**定价分析**：
- `PricingItem` — 定价信息项（competitor, free_tier, paid_tier, pricing_model, citations）
- `PricingAnalysis` — 定价分析结果（pricing_comparison, pricing_strategy_analysis, value_ranking, summary, citations）

**市场分析**：
- `MarketShareItem` — 市场份额项（competitor, share_estimate, trend, citations）
- `UserReputation` — 用户口碑（score, keywords, citations）
- `UserProfile` — 用户画像（target_audience, age_range, occupation_distribution, use_cases, pain_points, citations）
- `MarketAnalysis` — 市场分析结果（market_share_data, growth_trends, user_reputation, user_profiles, channel_analysis, summary, citations）

**策略报告**：
- `ActionItem` — 行动方案项（priority, action, timeline, expected_impact, citations）
- `StrategyReport` — 最终策略报告（product_name, competitor_count, overall_positioning, differentiation_strategy, action_plan, risk_assessment, 三维摘要, raw_llm_logs, citation_index, qa_timeline）

**质量保障**：
- `QualityIssue` — 单个质量问题（severity, category, field, description, expected, actual, suggestion）
- `QualityCheckResult` — 单次质检结果（phase, target_agent, passed, score, issues, checked_at, attempt, degraded, feedback_to_agent）
- `QATimeline` — QA时间线（checks, max_retries, total_retries；支持add_check/all_passed操作）

## 九、设计要点与决策记录

### 9.1 为什么采用两段式采集而非一步到位？
- 第一步只发现竞品列表，确定分析范围，避免盲目搜索
- 第二步针对已确定的竞品逐个深度采集，搜索关键词更精准
- 分段后每步的LLM调用职责更单一，结果更可控

### 9.2 为什么引入维度生成Agent（DimensionAgent）？
- 不同品类的竞品对比角度差异很大（SaaS vs 消费电子 vs 食品饮料）
- 硬编码维度无法覆盖所有品类，导致分析模板化
- DimensionAgent根据产品描述动态推断品类，生成该品类最具区分度的子维度
- 产品分析和定价分析各获得4-6个专属子维度，提升分析的针对性和深度

### 9.3 为什么三维分析并行而非串行？
- 产品/定价/市场三个维度互不依赖，可并行执行，总耗时≈单路
- 并行结果独立输出JSON，避免维度间耦合
- 策略Agent一次性看到全貌，不受串行顺序影响

### 9.4 为什么每个Agent都有规则引擎Fallback？
- 即使没有LLM也能跑通完整流程（`--rule`模式）
- LLM故障时系统不宕机，自动降级
- 开发测试阶段可零成本运行

### 9.5 引用溯源系统设计
- 采集阶段：每条搜索结果生成Citation对象，ID格式为`{竞品名}:q{查询序号}:r{结果序号}`
- 分析阶段：ProductAgent/PricingAgent/MarketAgent在输出中标注引用ID列表（citations字段）
- 报告阶段：StrategyAgent汇总所有引用到CitationIndex，HTML报告附录中展示完整来源列表
- 全链路可追溯：最终报告中的每条结论都能追溯到原始搜索来源

### 9.6 竞品矩阵的符号设计
- ✅ 完整支持：功能完善，体验良好
- 🔶 部分支持：有此功能但不够成熟或体验一般
- ❌ 不支持：无此功能或仅规划中

### 9.7 为什么引入QualityAgent全流程质检？
- **幻觉风险**：LLM可能编造无来源支撑的数据（如虚构市场份额数字），需要对比原始搜索文本来检测
- **完整性保障**：分析结果可能维度缺失（如功能矩阵只有3项而应有8-10项），规则引擎可自动检查
- **打回重做机制**：发现问题后将具体反馈（含问题描述+修复建议）打回给对应Agent重做，而非简单丢弃
- **降级通过**：重试达到上限后标记degraded=True继续流程，保证系统不会因质检卡死
- **QA时间线嵌入报告**：所有质检结果记录在StrategyReport.qa_timeline中，用户可查看质量保障过程

### 9.8 提示词模板系统设计
- **Markdown格式**：每个Agent一个.md文件，通过`## section_name`分割为多个模板节
- **system_prompt必需**：每个.md文件必须包含`## system_prompt`节
- **变量注入**：模板中的`{variable}`由Agent代码填充
- **示例注入**：`{{example:xxx}}`模板变量自动加载`prompts/examples/xxx.json`文件内容
- **内存缓存**：prompt_loader对解析结果和示例文件进行缓存，避免重复IO
- **自动生成**：`scripts/generate_prompt_examples.py`可从dataclass定义自动生成示例JSON

### 9.9 数据传递为什么用dataclass而非dict？
- **类型安全**：IDE和mypy可在编译期捕获字段拼写错误
- **字段验证**：`__post_init__`可校验枚举值范围（如relevance必须是HIGH/MEDIUM/LOW）
- **自文档化**：字段类型和默认值一目了然
- **序列化兼容**：dataclass可直接转dict用于JSON输出
