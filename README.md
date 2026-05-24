# CompetAgent - AI驱动的竞品分析Agent协作系统

基于LangGraph构建的多Agent协作竞品分析系统，模拟数字调研小组自动完成从公开信息采集到结构化竞品报告的全链路产出。

## 项目架构
本系统包含4个专职角色Agent：
- **信息采集Agent**：负责全网公开信息抓取，支持搜索调研
- **分析师Agent**：负责结构化整理、竞品对比、SWOT分析
- **报告撰写Agent**：负责生成规范的结构化分析报告
- **质检Agent**：负责事实校验，识别问题并打回迭代，形成反馈闭环

## 环境要求
- Python 3.12+
- uv 包管理器

## 快速开始

### 1. 安装依赖
```bash
cd CompetAgent
uv sync
```

### 2. 配置环境变量
在项目根目录创建 `.env` 文件，配置你的API密钥：
```env
# OpenAI 兼容的 LLM 配置（如 Xiaomi MIMO API）
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1

# 搜索服务配置
TAVILY_API_KEY=your-tavily-api-key

# LangSmith 可观测性配置（可选）
LANGSMITH_API_KEY=your-langsmith-api-key
LANGSMITH_TRACING=true
```

### 3. 启动LangGraph开发服务
```bash
cd src
uv run langgraph dev
```

服务启动后会在本地运行，你可以通过 LangGraph Studio 界面访问，查看Agent执行流程、调试状态、跟踪每一步的执行日志。

## 输出说明
系统最终会生成结构化的竞品分析报告，包含：
- 竞品公司详细档案
- 多维度功能对比矩阵
- 定价模型对比分析
- 用户画像与市场份额分析
- SWOT战略洞察
- 所有结论附带溯源数据源URL

## 核心特性
- 基于LangGraph原生DAG编排，任务流转全程可视化可追溯
- Agent间采用结构化消息传递，非纯自然语言对话
- 真实反馈闭环：质检Agent可将问题打回前置环节重制
- 每条分析结论绑定数据来源，完整信息溯源
- 全链路可观测：记录每个Agent的Prompt、输入输出、Token消耗
