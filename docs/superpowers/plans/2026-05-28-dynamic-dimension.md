# 动态维度生成机制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 DimensionAgent，根据产品品类动态生成产品分析和定价分析的子维度，替换现有硬编码子维度。

**Architecture:** 在 DiscoveryAgent 之后插入 DimensionAgent，推断品类并生成子维度配置。产品和定价 Agent 接收动态子维度注入，市场 Agent 保持不变。

**Tech Stack:** Python 3.x, asyncio, dataclasses, LLM (豆包/方舟兼容接口)

---

## File Structure

```
models/domain.py              — 新增 DimensionConfig 数据类
agents/dimension_agent.py     — 新建，品类推断 + 子维度生成
prompts/dimension_agent.md    — 新建，DimensionAgent 提示词模板
core/orchestrator.py          — 修改，插入 DimensionAgent 到管线
agents/product_agent.py       — 修改，接收动态子维度
agents/pricing_agent.py       — 修改，接收动态子维度
prompts/product_agent.md      — 修改，system_prompt 增加 {sub_dimensions} 占位符
prompts/pricing_agent.md      — 修改，同上
```

---

### Task 1: 新增 DimensionConfig 数据类

**Files:**
- Modify: `models/domain.py`

- [ ] **Step 1: 在 domain.py 末尾添加 DimensionConfig**

在 `StrategyReport` 类之后添加：

```python
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
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from models.domain import DimensionConfig, SubDimension, ProductCategory; print('OK')"`
Expected: `OK`

---

### Task 2: 创建 DimensionAgent 提示词

**Files:**
- Create: `prompts/dimension_agent.md`

- [ ] **Step 1: 创建提示词文件**

```markdown
## system_prompt

你是一个产品品类分析和维度设计专家。你的职责是：
1. 根据产品描述和竞品列表，推断产品品类
2. 为产品分析和定价分析各生成 4-6 个最合适的子维度

### 核心原则
1. 子维度名称简洁（2-6个字），便于矩阵展示
2. 每个子维度必须附带一句话说明
3. 避免维度之间高度重叠
4. 选择该品类最具区分度的对比角度

### 输出要求
严格JSON格式，不要任何多余文字。

## prompt_generate

请根据以下产品信息，推断产品品类并生成分析维度。

### 产品描述
{product_description}

### 竞品列表
{competitors_text}

### 分析要求
1. 推断产品品类（一级品类 + 二级品类）
2. 为产品分析生成 4-6 个子维度（从功能、体验、技术、设计等角度）
3. 为定价分析生成 4-6 个子维度（从定价模式、价格结构、促销策略等角度）
4. 解释品类推断和维度选择的理由

### 输出格式
```json
{{
    "product_category": {{
        "level1": "一级品类",
        "level2": "二级品类"
    }},
    "product_sub_dimensions": [
        {{"name": "维度名", "description": "维度说明"}}
    ],
    "pricing_sub_dimensions": [
        {{"name": "维度名", "description": "维度说明"}}
    ],
    "reasoning": "品类推断和维度选择理由"
}}
```
```

---

### Task 3: 创建 DimensionAgent

**Files:**
- Create: `agents/dimension_agent.py`

- [ ] **Step 1: 实现 DimensionAgent**

```python
# -*- coding: utf-8 -*-
"""
agents/dimension_agent.py — 维度生成Agent

职责：推断产品品类，为产品分析和定价分析生成动态子维度
LLM调用：1次
外部工具：无
提示词来源：prompts/dimension_agent.md
"""

from agents.base_agent import BaseAgent
from models.domain import (
    CompetitorList, CompetitorInfo,
    DimensionConfig, ProductCategory, SubDimension,
)
from core.prompt_loader import load as load_prompts
import config


class DimensionAgent(BaseAgent):
    """维度生成Agent — 品类推断 + 子维度生成"""

    def __init__(self):
        prompts = load_prompts("dimension_agent")
        super().__init__(
            agent_id="DimensionAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_generate = prompts["prompt_generate"]

    async def run(self, product_description: str,
                  competitor_list: CompetitorList) -> DimensionConfig:
        """
        推断品类并生成产品/定价分析的子维度

        Args:
            product_description: 用户产品描述
            competitor_list: 竞品发现结果

        Returns:
            DimensionConfig: 动态维度配置
        """
        self._log("📐 开始维度生成...")

        competitors_text = self._build_competitors_text(competitor_list)

        if config.ENABLE_LLM:
            prompt = self._prompt_generate.format(
                product_description=product_description,
                competitors_text=competitors_text,
            )
            result = self.ask_llm_json(prompt, max_tokens=2048)
            if result:
                dim_config = self._parse_config(result)
                self._log(
                    f"✅ 维度生成完成: 品类={dim_config.product_category.level1}/{dim_config.product_category.level2}, "
                    f"产品子维度={len(dim_config.product_sub_dimensions)}个, "
                    f"定价子维度={len(dim_config.pricing_sub_dimensions)}个"
                )
                return dim_config
            else:
                self._log("⚠️ LLM维度生成失败，降级到默认维度")

        return self._rule_generate(competitor_list)

    def _build_competitors_text(self, competitor_list: CompetitorList) -> str:
        """构建竞品列表文本"""
        lines = []
        for c in competitor_list.competitors:
            lines.append(f"- {c.name}: {c.brief}")
        return "\n".join(lines)

    def _parse_config(self, result: dict) -> DimensionConfig:
        """解析LLM返回的维度配置"""
        cat = result.get("product_category", {})
        product_dims = [
            SubDimension(name=d.get("name", ""), description=d.get("description", ""))
            for d in result.get("product_sub_dimensions", [])
        ]
        pricing_dims = [
            SubDimension(name=d.get("name", ""), description=d.get("description", ""))
            for d in result.get("pricing_sub_dimensions", [])
        ]
        return DimensionConfig(
            product_category=ProductCategory(
                level1=cat.get("level1", ""),
                level2=cat.get("level2", ""),
            ),
            product_sub_dimensions=product_dims,
            pricing_sub_dimensions=pricing_dims,
            reasoning=result.get("reasoning", ""),
        )

    def _rule_generate(self, competitor_list: CompetitorList) -> DimensionConfig:
        """规则引擎降级：返回通用维度"""
        self._log("   使用通用默认维度")
        return DimensionConfig(
            product_category=ProductCategory(level1="通用", level2="通用产品"),
            product_sub_dimensions=[
                SubDimension(name="核心功能", description="主要功能的完整度和质量"),
                SubDimension(name="用户体验", description="交互设计、易用性、流畅度"),
                SubDimension(name="技术创新", description="技术方案的先进性和差异化"),
                SubDimension(name="产品成熟度", description="功能稳定性和完善程度"),
            ],
            pricing_sub_dimensions=[
                SubDimension(name="定价模式", description="免费增值/订阅/一次性买断等"),
                SubDimension(name="价格梯度", description="不同版本/套餐的价格差异"),
                SubDimension(name="性价比", description="功能覆盖与价格的综合评估"),
                SubDimension(name="促销策略", description="优惠活动、折扣、试用期"),
            ],
            reasoning="规则引擎降级，使用通用维度",
        )
```

---

### Task 4: 修改产品分析 prompt 支持动态子维度

**Files:**
- Modify: `prompts/product_agent.md`

- [ ] **Step 1: 修改 system_prompt 中的分析维度部分**

将现有的 `### 分析维度` 部分替换为动态注入格式。

将 `prompts/product_agent.md` 的 `## system_prompt` 节中的：

```
### 分析维度
1. 功能覆盖度：各竞品在核心功能上的支持程度
2. 体验深度：功能是否成熟、是否好用
3. 创新点：独有的、竞品没有的功能
4. 成熟度：功能的稳定性和完善程度
```

替换为：

```
### 分析维度
{sub_dimensions}
```

---

### Task 5: 修改定价分析 prompt 支持动态子维度

**Files:**
- Modify: `prompts/pricing_agent.md`

- [ ] **Step 1: 修改 system_prompt 中的分析维度部分**

将 `prompts/pricing_agent.md` 的 `## system_prompt` 节中的：

```
### 分析维度
1. **定价模型**：免费增值/纯订阅/按量付费/混合/一次性买断
2. **价格梯度**：免费版→入门版→专业版→企业版的功能和价格递进
3. **促销模式**：试用期、折扣策略、捆绑销售、年付优惠
4. **性价比**：功能覆盖 vs 价格的性价比评估
5. **定价趋势**：市场整体定价趋势（涨价/降价/免费化）
```

替换为：

```
### 分析维度
{sub_dimensions}
```

---

### Task 6: 修改 ProductAgent 接收动态子维度

**Files:**
- Modify: `agents/product_agent.py`

- [ ] **Step 1: 修改 __init__ 和 run 方法签名**

在 `__init__` 中将 system_prompt 模板保存为模板字符串，在 `run` 时注入子维度。

将 `product_agent.py` 中的：

```python
class ProductAgent(BaseAgent):
    """产品分析Agent — 功能对比矩阵"""

    def __init__(self):
        prompts = load_prompts("product_agent")
        super().__init__(
            agent_id="ProductAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData]) -> ProductAnalysis:
```

替换为：

```python
class ProductAgent(BaseAgent):
    """产品分析Agent — 功能对比矩阵"""

    def __init__(self):
        prompts = load_prompts("product_agent")
        self._system_prompt_template = prompts["system_prompt"]
        self._prompt_analyze = prompts["prompt_analyze"]
        super().__init__(
            agent_id="ProductAgent",
            system_prompt=self._system_prompt_template,
        )

    def set_sub_dimensions(self, sub_dimensions_text: str):
        """注入动态子维度（由 DimensionAgent 生成）"""
        self.system_prompt = self._system_prompt_template.format(
            sub_dimensions=sub_dimensions_text
        )

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData],
                  sub_dimensions: str = "") -> ProductAnalysis:
```

- [ ] **Step 2: 在 run 方法开头注入子维度**

在 `run` 方法的 `self._log("🔧 开始产品分析...")` 之后，添加：

```python
        if sub_dimensions:
            self.set_sub_dimensions(sub_dimensions)
```

---

### Task 7: 修改 PricingAgent 接收动态子维度

**Files:**
- Modify: `agents/pricing_agent.py`

- [ ] **Step 1: 修改 __init__ 和 run 方法签名**

与 ProductAgent 同样的模式。将 `pricing_agent.py` 中的：

```python
class PricingAgent(BaseAgent):
    """定价分析Agent — 价格策略对比"""

    def __init__(self):
        prompts = load_prompts("pricing_agent")
        super().__init__(
            agent_id="PricingAgent",
            system_prompt=prompts["system_prompt"],
        )
        self._prompt_analyze = prompts["prompt_analyze"]

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData]) -> PricingAnalysis:
```

替换为：

```python
class PricingAgent(BaseAgent):
    """定价分析Agent — 价格策略对比"""

    def __init__(self):
        prompts = load_prompts("pricing_agent")
        self._system_prompt_template = prompts["system_prompt"]
        self._prompt_analyze = prompts["prompt_analyze"]
        super().__init__(
            agent_id="PricingAgent",
            system_prompt=self._system_prompt_template,
        )

    def set_sub_dimensions(self, sub_dimensions_text: str):
        """注入动态子维度（由 DimensionAgent 生成）"""
        self.system_prompt = self._system_prompt_template.format(
            sub_dimensions=sub_dimensions_text
        )

    async def run(self, product_name: str,
                  competitors_data: dict[str, CompetitorData],
                  sub_dimensions: str = "") -> PricingAnalysis:
```

- [ ] **Step 2: 在 run 方法开头注入子维度**

在 `run` 方法的 `self._log("💰 开始定价分析...")` 之后，添加：

```python
        if sub_dimensions:
            self.set_sub_dimensions(sub_dimensions)
```

---

### Task 8: 修改 Orchestrator 插入 DimensionAgent

**Files:**
- Modify: `core/orchestrator.py`

- [ ] **Step 1: 添加 DimensionAgent 导入和实例化**

在文件顶部导入部分添加：

```python
from agents.dimension_agent import DimensionAgent
```

在 `__init__` 中添加：

```python
        self.dimension_agent = DimensionAgent()
```

- [ ] **Step 2: 在 Phase 2 之后插入维度生成步骤**

在 `Phase 2` 结束（`print(f"\n  ⏱️ 采集耗时: ...")` 之后）和 `Phase 3` 开始之前，插入：

```python
        # ── Phase 2.5: 维度生成 ──
        phase2_5_start = time.time()
        dim_config = await self.dimension_agent.run(
            product_description, competitor_list
        )
        self.timings["dimension"] = time.time() - phase2_5_start

        # 构建子维度文本注入 prompt
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
```

- [ ] **Step 3: 修改 Phase 3 并行分析调用**

将现有的：

```python
        product_analysis, pricing_analysis, market_analysis = await asyncio.gather(
            self.product_agent.run(product_name, competitors_data),
            self.pricing_agent.run(product_name, competitors_data),
            self.market_agent.run(product_name, competitors_data),
        )
```

替换为：

```python
        product_analysis, pricing_analysis, market_analysis = await asyncio.gather(
            self.product_agent.run(product_name, competitors_data,
                                   sub_dimensions=product_sub_dims_text),
            self.pricing_agent.run(product_name, competitors_data,
                                   sub_dimensions=pricing_sub_dims_text),
            self.market_agent.run(product_name, competitors_data),
        )
```

- [ ] **Step 4: 添加 _format_sub_dimensions 辅助方法**

在类中添加：

```python
    @staticmethod
    def _format_sub_dimensions(dims: list) -> str:
        """将子维度列表格式化为 prompt 注入文本"""
        lines = []
        for i, d in enumerate(dims, 1):
            lines.append(f"{i}. **{d.name}**：{d.description}")
        return "\n".join(lines)
```

- [ ] **Step 5: 添加 dimension_agent 的 LLM 日志**

在 `report.raw_llm_logs` 赋值处添加 `self.dimension_agent.llm_logs`：

```python
        report.raw_llm_logs = (
            self.discovery_agent.llm_logs +
            self.dimension_agent.llm_logs +
            self.collection_agent.llm_logs +
            self.product_agent.llm_logs +
            self.pricing_agent.llm_logs +
            self.market_agent.llm_logs +
            self.strategy_agent.llm_logs
        )
```

---

### Task 9: 验证 prompt_loader 缓存兼容性

**Files:**
- Verify: `core/prompt_loader.py`

- [ ] **Step 1: 确认 prompt_loader 缓存不会导致问题**

`prompt_loader.py` 有 `_cache` 字典缓存已加载的 prompt。由于 ProductAgent 和 PricingAgent 的 `system_prompt_template` 保留了 `{sub_dimensions}` 占位符，每次 `set_sub_dimensions` 都会用 `.format()` 重新生成 `system_prompt`，不会受缓存影响。无需修改 prompt_loader。

验证：阅读 `agents/product_agent.py` 和 `agents/pricing_agent.py` 确认 `_system_prompt_template` 和 `system_prompt` 是两个独立变量。

---

### Task 10: 运行测试

- [ ] **Step 1: 运行 `python main.py "iphone 16"` 验证完整流程**

```bash
conda activate agent_env && python main.py "iphone 16"
```

Expected: 完整流程执行，包含维度生成阶段输出，无报错。

- [ ] **Step 2: 检查输出报告中维度是否动态化**

查看终端输出中的 `📐 品类:` 行，确认品类推断合理（应为消费电子/智能手机）。
查看功能对比矩阵，确认维度不再是固定的"即时通讯/视频会议/..."。

- [ ] **Step 3: 提交所有改动**

```bash
git add models/domain.py agents/dimension_agent.py prompts/dimension_agent.md \
        core/orchestrator.py agents/product_agent.py agents/pricing_agent.py \
        prompts/product_agent.md prompts/pricing_agent.md
git commit -m "feat(dimension): add DimensionAgent for dynamic sub-dimension generation"
```
