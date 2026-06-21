# SmartComp Engine

基于多 Agent 协作的竞品分析系统。输入一个产品名称，自动发现竞品、多维度分析（功能 / 定价 / 市场），生成 HTML + JSON 策略报告。

- LLM 调用走豆包（Volcengine）API，联网搜索走豆包 Responses API
- 每个 Agent 都有规则引擎兜底，无 API Key 时可零成本运行
- 双执行路径：LangGraph StateGraph（默认）和 Legacy 顺序流

## 快速开始

### 1. 拉取项目

```bash
git clone https://github.com/Yejiajun277/SmartComp_Engine.git
cd SmartComp_Engine
```

### 2. 创建虚拟环境

```bash
conda create -n smartcomp python=3.12 -y
conda activate smartcomp
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置 `.env`

在项目根目录创建 `.env` 文件（已被 `.gitignore` 忽略）：

```env
DOUBAO_API_KEY=你的豆包API Key
DOUBAO_MODEL=你的接入点ID
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

SEARCH_RECENCY=month
SEARCH_DELAY_SECONDS=2.0
```

- `DOUBAO_API_KEY` 和 `DOUBAO_MODEL` 为必填
- 不配置时可使用 `--rule` 模式运行（纯规则引擎，不调用 LLM）

## CLI 模式

```bash
python3 main.py "deepseek"              # LLM 模式（需要 .env）
python3 main.py --rule "deepseek"       # 规则引擎模式（无需 API Key）
python3 main.py --count 5 "deepseek"    # 指定竞品数量（3-8）
python3 main.py --debug "deepseek"      # 跳过 QA 检查
python3 main.py --verbose "deepseek"    # 详细输出
```

报告输出到 `output/` 目录：`{product}_analysis_report.html` 和 `.json`。

## Web UI 模式

提供可视化任务管理、实时进度推送、LLM 日志查看。

```bash
# 终端 1：启动 FastAPI 后端（端口 8000）
python3 -m uvicorn server.main:app --reload --port 8000

# 终端 2：启动前端开发服务器（端口 5173，代理 /api 和 /ws 到 8000）
cd frontend && npm run dev
```

生产环境下 FastAPI 直接从 `frontend/dist/` 提供前端静态文件。

## Docker Compose 部署

项目提供单容器生产部署：容器内先构建 React 前端，再由 FastAPI 在 `:8000` 同时提供 API、WebSocket 和静态前端页面。

### 1. 准备 `.env`

在项目根目录创建 `.env`，Compose 会在运行时注入该文件。`.env` 不会被复制进镜像，也不应提交到 Git。

```env
DOUBAO_API_KEY=你的豆包 API Key
DOUBAO_MODEL=你的接入点 ID
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

SEARCH_RECENCY=month
SEARCH_DELAY_SECONDS=2.0
```

如果没有配置 `DOUBAO_API_KEY`，Web 任务会自动切换到规则引擎模式；配置后默认使用 LLM 模式。

### 2. 构建并启动

```bash
docker compose build
docker compose up -d
```

启动后访问：

```text
http://localhost:8000
```

健康检查：

```bash
curl http://localhost:8000/api/health
```

预期返回：

```json
{"status":"ok"}
```

### 3. 数据持久化

Compose 会挂载本地 `./output` 到容器内 `/app/output`，用于保存任务状态、HTML/JSON 报告和运行归档。重启容器不会丢失这些产物。

### 4. 镜像源说明

`docker-compose.yml` 默认使用可覆盖的基础镜像参数：

```yaml
NODE_IMAGE: docker.m.daocloud.io/library/node:22-alpine
PYTHON_IMAGE: docker.m.daocloud.io/library/python:3.12-slim
```

如需切换回 Docker Hub 或公司内部镜像源，可在命令行覆盖：

```bash
docker compose build \
  --build-arg NODE_IMAGE=node:22-alpine \
  --build-arg PYTHON_IMAGE=python:3.12-slim
```

### 前端技术栈

React 19 + Vite 8 + Ant Design 6，通过 REST API 和 WebSocket 实时通信。

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks` | 创建分析任务 |
| GET | `/api/tasks` | 获取所有任务 |
| GET | `/api/tasks/{id}` | 获取单个任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| GET | `/api/tasks/{id}/report` | 获取 JSON 报告 |
| GET | `/api/tasks/{id}/report.html` | 获取 HTML 报告 |
| GET | `/api/tasks/{id}/llm-logs` | 获取 LLM 调用日志 |
| GET | `/api/tasks/{id}/artifacts/{phase}` | 获取阶段产物 |
| WS | `/ws/tasks/{task_id}` | 实时事件推送 |

## 系统架构

```
React Frontend (:5173)  ←→  FastAPI Server (:8000)  ←→  Orchestrator + Agents
   Dashboard, TaskDetail,      REST /api/tasks,            LangGraph StateGraph
   ReportView                  WS /ws/tasks/:id            (or Legacy path)
```

### 分析流水线

```
Phase 1   DiscoveryAgent    → 竞品列表                (2 次 LLM 调用)
Phase 2   CollectionAgent   → 竞品详细数据             (1+N 次调用，每竞品 7 组搜索)
Phase 2.5 DimensionAgent    → 动态分析维度配置         (1 次调用)
Phase 3   ProductAgent      → 功能对比分析             (并行，3 次调用)
          PricingAgent      → 定价策略分析
          MarketAgent       → 市场份额分析
Phase 4   StrategyAgent     → 策略报告 + HTML 生成     (1 次调用)
QA        QualityAgent      每阶段运行，完整性检查 + 幻觉检测
```

LLM 调用总数：6 + N（N = 竞品数量）。

### Agent 列表

| Agent | 职责 |
|-------|------|
| `DiscoveryAgent` | 生成搜索关键词，发现并筛选竞品 |
| `CollectionAgent` | 逐竞品深度采集数据，构建结构化引用 |
| `DimensionAgent` | 推断产品类别，生成动态分析子维度 |
| `ProductAgent` | 构建功能对比矩阵 |
| `PricingAgent` | 对比定价策略 |
| `MarketAgent` | 分析市场份额、用户口碑、用户画像 |
| `StrategyAgent` | 综合分析生成策略报告，生成 HTML 报告 |
| `QualityAgent` | 完整性检查（规则引擎）+ 幻觉检测（LLM），管理重试与降级 |

### LangGraph 工作流

默认使用 LangGraph StateGraph 编排（`workflow/` 目录），包含 30+ 节点：

- 条件路由：QA 通过 / 重试 / 降级
- 扇出/扇入：Phase 3 三个分析 Agent 并行执行
- 重试机制：每个节点支持可配置重试次数（默认 2 次）
- 实时事件：每个节点通过 EventBus 推送进度到前端

切换到 Legacy 顺序流：设置环境变量 `USE_LANGGRAPH_WORKFLOW=0`。

### QA 质检体系

- **完整性检查**：规则引擎验证必填字段、格式、引用
- **幻觉检测**：LLM 验证数据是否可溯源到原始搜索结果
- **评分机制**：完整性 60% + 幻觉检测 40%
- **自动重试**：质检不通过时自动重试，超过上限后降级运行

## 项目结构

```
SmartComp_Engine/
├── main.py                 # CLI 入口
├── config.py               # 全局配置（自定义 .env 加载）
├── agents/                 # 8 个 Agent 实现
│   ├── base_agent.py       # 抽象基类（ask_llm, ask_llm_json, 异步变体）
│   ├── discovery_agent.py
│   ├── collection_agent.py
│   ├── dimension_agent.py
│   ├── product_agent.py
│   ├── pricing_agent.py
│   ├── market_agent.py
│   ├── strategy_agent.py
│   └── quality_agent.py
├── core/                   # 基础设施
│   ├── llm_client.py       # 豆包 LLM 客户端（同步 + 异步）
│   ├── search_client.py    # 豆包联网搜索客户端（同步 + 异步）
│   ├── orchestrator.py     # 流水线编排器（双路径）
│   ├── prompt_loader.py    # Markdown 模板加载器
│   └── artifact_store.py   # 运行产物归档
├── models/
│   └── domain.py           # 全部领域数据模型（dataclass）
├── workflow/               # LangGraph 工作流
│   ├── state.py            # AnalysisState（~50 个字段）
│   ├── nodes.py            # ~25 个节点方法
│   └── graph.py            # StateGraph 构建与路由
├── prompts/                # Markdown 提示词模板 + JSON 示例
├── server/                 # FastAPI Web 服务
│   ├── main.py             # FastAPI 应用
│   ├── models.py           # Pydantic 模型
│   ├── routers/            # REST + WebSocket 路由
│   └── services/           # 任务管理 + 事件总线
├── frontend/               # React 前端
│   └── src/
│       ├── pages/          # Dashboard, TaskDetail, ReportView
│       ├── components/     # PipelineGraph, LlmLogs, QATimeline 等
│       └── hooks/          # useTask, useWebSocket
├── tests/                  # pytest 测试
└── output/                 # 报告输出 + 运行归档
```

## 运行测试

```bash
python3 -m pytest tests/ -v                              # 全部测试
python3 -m pytest tests/test_orchestrator_baseline.py -v  # 编排器基线测试
python3 -m pytest tests/test_workflow_nodes.py -v         # LangGraph 节点测试
python3 -m pytest tests/test_workflow_graph.py -v         # LangGraph 图测试
python3 -m pytest tests/test_orchestrator_facade.py -v    # 编排器接口测试
```

测试使用 `unittest.IsolatedAsyncioTestCase`，通过 fake agent 模拟，无需 LLM / 网络。

## 环境变量参考

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DOUBAO_API_KEY` | 是 | - | 豆包 API Key |
| `DOUBAO_MODEL` | 是 | - | 豆包接入点 ID |
| `DOUBAO_BASE_URL` | 否 | `https://ark.cn-beijing.volces.com/api/v3` | API 地址 |
| `SEARCH_RECENCY` | 否 | `month` | 搜索时效性过滤 |
| `SEARCH_DELAY_SECONDS` | 否 | `2.0` | 搜索请求间隔 |
| `USE_LANGGRAPH_WORKFLOW` | 否 | `1` | 是否使用 LangGraph（`0` 为 Legacy） |
| `LANGGRAPH_NODE_RETRIES` | 否 | `2` | 节点重试次数 |
| `LLM_TEMPERATURE` | 否 | `0.1` | LLM 温度参数 |
| `LLM_MAX_TOKENS` | 否 | `4096` | LLM 最大输出 token |
| `SKIP_QA` | 否 | `0` | 跳过 QA 检查 |

## 常见问题

### Windows 提示找不到 `python3`

直接使用 `python main.py "deepseek"`。

### 没有配置 `.env`

使用规则模式运行：`python3 main.py --rule "deepseek"`，不调用 LLM 和联网搜索。
