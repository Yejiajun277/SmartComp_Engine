# SmartComp Engine

SmartComp Engine 是一个多 Agent 竞品分析系统。给定产品名称或产品描述后，系统会发现竞品、采集竞品信息、生成产品/定价/市场三维分析，并输出 HTML 与 JSON 策略报告。

当前实现保留原有 Agent、Prompt、Doubao LLM 调用、JSON 解析和规则引擎 fallback，并使用 LangGraph `StateGraph` 作为默认编排层。

## 架构

### Agent 层

- `DiscoveryAgent`：发现核心竞品。
- `CollectionAgent`：采集目标产品和竞品数据。
- `DimensionAgent`：生成产品分析和定价分析的动态维度。
- `ProductAgent`：生成产品功能矩阵和差异化点。
- `PricingAgent`：生成定价对比和定价策略分析。
- `MarketAgent`：生成市场份额、用户口碑、用户画像和渠道分析。
- `StrategyAgent`：汇总三维分析，生成最终策略报告和 HTML。
- `QualityAgent`：对采集、三维分析、策略报告做质检并生成反馈。

### LangGraph 编排层

默认编排路径位于 `workflow/`：

- `workflow/state.py`：统一 `AnalysisState`。
- `workflow/nodes.py`：将现有 Agent 调用包装为 graph node。
- `workflow/graph.py`：使用 `StateGraph`、固定边和条件边表达完整流程。

主流程：

```text
竞品发现
→ 目标产品采集
→ 竞品数据采集
→ 数据采集质检
→ 分析维度生成
→ 产品分析、定价分析、市场分析并发执行
→ 三类分析结果质检
→ 策略报告生成
→ 最终报告质检
→ 输出 HTML 和 JSON 报告
```

质检失败会通过条件边定向回到对应节点重跑。每个质检回路最多重跑 2 次；超过最大次数后进入结构化失败出口，保存 `failed_state.json`、`qa_timeline.json` 和 `llm_logs.json`。

旧编排实现仍保留在 `core/orchestrator.py::_analyze_legacy()`，可通过 feature flag 回滚。

## 安装

```bash
conda create -n smartcomp python=3.12 -y
conda activate smartcomp
pip install -r requirements.txt
```

依赖包括：

- `requests`
- `langgraph`

## 配置

项目使用 `config.py` 中的自定义 `.env` 加载逻辑，不依赖 `python-dotenv`。

在项目根目录创建 `.env`：

```env
LLM_PROVIDER=doubao
DOUBAO_API_KEY=你的豆包 API Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=你的接入点 ID

SEARCH_RECENCY=month
SEARCH_DELAY_SECONDS=2.0
SEARCH_MAX_OUTPUT_TOKENS=2048

USE_LANGGRAPH_WORKFLOW=1
LANGGRAPH_NODE_RETRIES=2
```

关键配置：

- `DOUBAO_API_KEY`：LLM 和联网搜索需要。
- `DOUBAO_MODEL`：Doubao endpoint/model ID。
- `USE_LANGGRAPH_WORKFLOW`：默认 `1`，使用 LangGraph 编排。
- `LANGGRAPH_NODE_RETRIES`：节点级临时异常重试次数，默认 `2`。

## 运行

### LangGraph 默认路径

```bash
python main.py "deepseek"
```

### 规则模式

不走 LLM，使用规则引擎 fallback：

```bash
python main.py --rule "deepseek"
```

### 指定竞品数量

```bash
python main.py --count 5 "deepseek"
```

### 回滚旧编排路径

Windows PowerShell：

```powershell
$env:USE_LANGGRAPH_WORKFLOW="0"
python main.py --rule "deepseek"
```

macOS / Linux：

```bash
USE_LANGGRAPH_WORKFLOW=0 python3 main.py --rule "deepseek"
```

## 输出

运行完成后会输出：

- `output/{product}_analysis_report.html`
- `output/{product}_analysis_report.json`
- `output/runs/{timestamp}_{product}/report.html`
- `output/runs/{timestamp}_{product}/report.json`
- `output/runs/{timestamp}_{product}/qa_timeline.json`
- `output/runs/{timestamp}_{product}/llm_logs.json`

如果 LangGraph 路径在质检最大重试后失败，还会输出：

- `output/runs/{timestamp}_{product}/failed_state.json`

## 测试

当前测试使用 `unittest`，fake agents 隔离网络和真实 LLM。

```bash
python -m unittest discover tests
```

本地 conda 示例：

```powershell
D:\Elmo\anaconda3\Scripts\conda.exe run -n agents-goods-analysis python -m unittest discover tests
```

覆盖范围：

- 旧编排基线和回滚路径。
- LangGraph node wrappers。
- `StateGraph` compile、正常路径、无竞品分支。
- 产品/定价/市场三维并发。
- collection/product/pricing/market/strategy 质检定向重试。
- 最大重试耗尽后的结构化失败出口。
- `Orchestrator.analyze()` feature flag 切换。

Windows 下如果 `conda run` 捕获 Unicode 输出时报 `UnicodeEncodeError`，可加 `--no-capture-output`：

```powershell
D:\Elmo\anaconda3\Scripts\conda.exe run -n agents-goods-analysis --no-capture-output python main.py --rule smoke_product
```

## 常见问题

### Windows 提示找不到 `python3`

Windows 下直接使用：

```powershell
python main.py "deepseek"
```

### 没有配置 `.env`

LLM 模式和联网搜索需要 Doubao API key。没有 `.env` 时，可以使用规则模式：

```bash
python main.py --rule "deepseek"
```

### 如何确认当前使用的是 LangGraph？

`USE_LANGGRAPH_WORKFLOW` 默认开启。也可以显式设置：

```bash
USE_LANGGRAPH_WORKFLOW=1 python3 main.py --rule "deepseek"
```

报告归档中的 `run_meta.json` 会记录本次运行配置和输出文件。
