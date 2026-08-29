# -*- coding: utf-8 -*-
"""
config.py - 智能竞品分析多Agent系统全局配置
"""

import os
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# ========================
# LLM / 联网搜索配置
# ========================
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "mimo")

MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MIMO_BASE_URL = os.environ.get(
    "MIMO_BASE_URL",
    "https://token-plan-cn.xiaomimimo.com/v1",
)
MIMO_MODEL = os.environ.get(
    "MIMO_MODEL",
    "mimo-v2.5-pro",
)
MIMO_USE_SYSTEM_PROXY = os.environ.get(
    "MIMO_USE_SYSTEM_PROXY",
    "false",
).lower() in {"1", "true", "yes", "on"}

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

SEARCH_RECENCY = os.environ.get("SEARCH_RECENCY", "month")
SEARCH_DELAY_SECONDS = float(os.environ.get("SEARCH_DELAY_SECONDS", "2.0"))
SEARCH_MAX_OUTPUT_TOKENS = int(os.environ.get("SEARCH_MAX_OUTPUT_TOKENS", "2048"))


# ========================
# 系统模式配置
# ========================
ENABLE_LLM = True
SKIP_QA = False  # --debug 模式下跳过所有质检
USE_LANGGRAPH_WORKFLOW = os.environ.get("USE_LANGGRAPH_WORKFLOW", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LANGGRAPH_NODE_RETRIES = int(os.environ.get("LANGGRAPH_NODE_RETRIES", "2"))


# ========================
# 竞品分析参数
# ========================
MIN_COMPETITORS = 1
MAX_COMPETITORS = 8
DEFAULT_COMPETITOR_COUNT = 5


# ========================
# LLM 调用参数
# ========================
LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS = 4096

# 是否在 llm_logs.json 中归档完整 Prompt（用于调试和审计，会增大日志体积）
ARCHIVE_PROMPTS = os.getenv("ARCHIVE_PROMPTS", "true").lower() in ("true", "1", "yes")
