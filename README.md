# SmartComp Engine

一个基于多 Agent 协作的竞品分析项目。

项目当前使用：
- 豆包 LLM 做分析
- 豆包联网搜索做外部信息检索

## 1. 拉取项目

```bash
git clone https://github.com/Yejiajun277/SmartComp_Engine.git
cd SmartComp_Engine
```

## 2. 用 Conda 创建虚拟环境

先创建环境：

```bash
conda create -n smartcomp python=3.12 -y
```

再激活环境：

```bash
conda activate smartcomp
```

## 3. 安装依赖

```bash
pip install -r requirements.txt
```

## 4. 创建 `.env`

项目不会提交 `.env`，需要你在项目根目录手动创建一个 `.env` 文件。

示例：

```env
LLM_PROVIDER=doubao
DOUBAO_API_KEY=你的豆包API Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=你的接入点ID

SEARCH_RECENCY=month
SEARCH_DELAY_SECONDS=2.0
```

说明：
- `DOUBAO_API_KEY` 必填
- `DOUBAO_MODEL` 必填
- `SEARCH_RECENCY` 可选，默认 `month`
- `.env` 已被 `.gitignore` 忽略，不会上传

## 5. 启动项目

### 普通分析模式

Windows 下建议使用：

```powershell
python main.py "deepseek"
```

macOS / Linux：

```bash
python3 main.py "deepseek"
```

### 规则模式

不走 LLM，只走规则逻辑：

```bash
python main.py --rule "deepseek"
```

### 指定竞品数量

```bash
python main.py --count 5 "deepseek"
```

### 查看帮助

```bash
python main.py help
```

## 6. 输出结果

运行完成后，报告会输出到 `output/` 目录：
- HTML 报告
- JSON 报告

相关输出逻辑见 [main.py:59](/D:/学习作业/Agent_Learning/AI全栈挑战赛_agent竞品分析/agent竞品分析参考/competitor-analysis-mas-v2/main.py:59)。

## 7. 常见问题

### Windows 提示找不到 `python3`

这是 Windows 命令别名问题，直接改用：

```powershell
python main.py "deepseek"
```

### 没有配置 `.env`

如果没有配置 `.env`，LLM 和联网搜索都无法正常工作。
