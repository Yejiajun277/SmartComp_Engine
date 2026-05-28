# 动态维度生成机制设计

## 背景

当前系统的分析维度约 90% 是硬编码的：宏观 3 个维度（产品/定价/市场）在架构层面固定，每个维度下的子维度硬编码在提示词模板中。只有产品分析中功能对比矩阵的具体功能名由 LLM 动态生成。

**问题：**
- 子维度太死板 — 不同品类的产品需要不同的分析角度
- 维度不适配行业 — 通用框架无法覆盖手机、SaaS、内容平台等差异巨大的品类
- 市场维度例外 — 市场分析的 5 个子维度（市场份额/增长趋势/用户口碑/渠道策略/竞争格局）基本通用，不需要动态化

## 设计方案

### 核心思路

新增 DimensionAgent，独立负责品类推断和子维度生成。保留三大 Agent 宏观框架，只对产品分析和定价分析的子维度做动态化。

### 管线变化

```
现在：  Discovery → Collection → [产品/定价/市场 并行] → Strategy
改后：  Discovery → DimensionAgent → Collection → [产品/定价/市场 并行] → Strategy
```

### DimensionAgent

**输入：**
- `CompetitorList`（来自 DiscoveryAgent）
- 用户产品描述

**输出：`DimensionConfig`**
- `product_category`：推断的产品品类（两级分类）
- `product_sub_dims`：产品分析子维度列表（4-6 个，含名称和说明）
- `pricing_sub_dims`：定价分析子维度列表（4-6 个，含名称和说明）
- `reasoning`：品类推断与维度选择理由

**不包含**市场子维度 — MarketAgent 继续使用现有的 5 个固定子维度。

**LLM 调用：** 1 次（品类推断 + 维度生成合并在一次调用中）

### 品类推断机制

**推断方式：** LLM 从产品描述 + 竞品列表中推断。

**两级分类：**
- 一级品类（粗）：消费电子 / 内容服务 / SaaS软件 / 智能硬件 / 电商平台 / ...
- 二级品类（细）：智能手机 / 视频会员 / 协作办公 / 学习机 / ...

**推断依据：**
- 用户的产品描述（主要信号）
- 竞品名称和简介（辅助信号）

### 子维度生成

品类确定后，LLM 为产品和定价各生成 4-6 个子维度。

**生成指令：**
- 根据品类，从功能、体验、技术、设计等角度挑选产品分析的核心对比维度
- 从定价模式、价格结构、促销策略等角度挑选定价分析的核心对比维度
- 子维度名称简洁（2-6个字），便于矩阵展示
- 每个子维度附带一句话说明

### 一致性策略

每次分析独立生成维度，不做缓存。

- DimensionAgent 每次都调用 LLM，根据当前竞品组合生成最合适的维度
- 不需要缓存目录、key 设计、失效策略
- 用户如需固定维度，可在产品描述中明确指定分析角度

### 示例输出

**手机：**
```json
{
    "product_category": {"level1": "消费电子", "level2": "智能手机"},
    "product_sub_dimensions": [
        {"name": "硬件性能", "description": "处理器、内存、存储等核心硬件参数"},
        {"name": "影像系统", "description": "摄像头规格、拍照/视频画质、计算摄影能力"},
        {"name": "屏幕素质", "description": "分辨率、刷新率、亮度、护眼技术"},
        {"name": "续航充电", "description": "电池容量、快充速度、无线充电"},
        {"name": "系统体验", "description": "OS流畅度、AI能力、生态互联"},
        {"name": "工业设计", "description": "材质、重量、手感、配色工艺"}
    ],
    "pricing_sub_dimensions": [
        {"name": "版本定价", "description": "不同存储/配置版本的价格梯度"},
        {"name": "首发策略", "description": "首发价格、预约优惠、限量礼盒"},
        {"name": "以旧换新", "description": "旧机折价力度、合作平台"},
        {"name": "分期方案", "description": "免息分期期数、合作金融机构"},
        {"name": "降价节奏", "description": "上市后价格走势、促销节点频率"}
    ]
}
```

**抖音：**
```json
{
    "product_category": {"level1": "内容服务", "level2": "短视频平台"},
    "product_sub_dimensions": [
        {"name": "内容生态", "description": "创作者规模、内容品类覆盖、独家内容"},
        {"name": "推荐算法", "description": "个性化推荐精准度、信息茧房控制"},
        {"name": "创作工具", "description": "拍摄/剪辑/特效/模板等创作能力"},
        {"name": "社交互动", "description": "评论、私信、直播、群聊等社交功能"},
        {"name": "商业化体验", "description": "广告密度、电商整合、本地生活"},
        {"name": "多端适配", "description": "手机/Pad/TV/车载等多端体验一致性"}
    ],
    "pricing_sub_dimensions": [
        {"name": "免费模式", "description": "免费用户的功能范围和广告体验"},
        {"name": "会员体系", "description": "会员等级、权益内容、价格"},
        {"name": "虚拟货币", "description": "抖币定价、充值梯度、打赏分成"},
        {"name": "电商佣金", "description": "小店抽佣比例、达人带货分成"},
        {"name": "广告定价", "description": "信息流/开屏/搜索广告的投放成本"}
    ]
}
```

## 改动范围

| 文件 | 改动 |
|------|------|
| `models/domain.py` | 新增 `DimensionConfig` 数据类 |
| `agents/dimension_agent.py` | 新建，DimensionAgent 实现 |
| `prompts/dimension_agent.md` | 新建，品类推断 + 维度生成的 prompt |
| `core/orchestrator.py` | 管线中插入 DimensionAgent，将维度配置传递给后续 Agent |
| `prompts/product_agent.md` | `### 分析维度` 部分改为接收动态注入 |
| `prompts/pricing_agent.md` | 同上 |
| `agents/product_agent.py` | 初始化时接收维度配置 |
| `agents/pricing_agent.py` | 同上 |

**不改动：**
- `MarketAgent` / `market_agent.md` — 保持现有 5 个固定子维度
- `StrategyAgent` — 接收分析结果，不关心子维度来源
- `CollectionAgent` — 采集维度（5 个固定字段）与分析维度独立
