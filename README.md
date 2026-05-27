# AI 竞品分析 Agent 协作系统

基于 `LangGraph` 的多 Agent 竞品分析系统，当前链路为：

`竞品发现 -> 研究规划 -> 证据采集 -> 并行分析 -> 质检闭环 -> 报告输出 -> Trace 落盘`

## 安装

### Conda 开发环境

推荐使用仓库内的 `environment.yml` 创建开发环境：

```powershell
conda env create -f environment.yml
conda activate smartcomp-engine-dev
```

后续依赖变更后同步环境：

```powershell
conda env update -f environment.yml --prune
```

验证环境：

```powershell
python -c "import agent; print('ok')"
```

### venv 环境

如果使用本地 venv，请先自行创建 `.venv`，再安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果你用自己的 Python：

```powershell
python -m pip install -r requirements.txt
```

## 环境变量

在项目根目录创建 `.env`：

```env
LLM_PROVIDER=doubao
DOUBAO_API_KEY=你的 API Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=你的模型接入点 ID

SEARCH_RECENCY=month
SEARCH_DELAY_SECONDS=2.0
SEARCH_MAX_OUTPUT_TOKENS=2048
```

## 运行命令

### 1. CLI 运行

开启 LLM：

```powershell
.\.venv\Scripts\python.exe .\main.py "分析飞书，关注定位、定价、功能树和用户画像"
```

关闭 LLM，走规则模式：

```powershell
.\.venv\Scripts\python.exe .\main.py --rule "分析飞书"
```

指定竞品数量：

```powershell
.\.venv\Scripts\python.exe .\main.py --count 5 "分析飞书"
```

查看帮助：

```powershell
.\.venv\Scripts\python.exe .\main.py help
```

### 2. 启动本地 API + 前端 Demo

```powershell
.\.venv\Scripts\python.exe .\api_server.py
```

启动后打开：

```text
http://127.0.0.1:8000
```

### 3. LangGraph 本地调试

```powershell
langgraph dev
```

可用 graph：

- `competitive_analysis_workflow`
- `competitive_analysis_assistant`

## 输出位置

每次运行都会写入：

```text
runs/<run_id>/trace/*.json
runs/<run_id>/artifacts/*.json
runs/<run_id>/report/*_analysis_report.json
runs/<run_id>/report/*_analysis_report.html
```

## 测试命令

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

## 说明

- 前端 Demo 只做演示，不是完整产品前端。
- Trace 会记录节点输入摘要、输出摘要、决策、延迟和 token 估算。
- 质检 Agent 会根据缺少 citation、缺少功能树、缺少定价模型、缺少用户画像等问题触发打回。
