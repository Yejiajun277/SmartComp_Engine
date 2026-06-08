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
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "doubao")

DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_BASE_URL = os.environ.get(
    "DOUBAO_BASE_URL",
    "https://ark.cn-beijing.volces.com/api/v3",
)
DOUBAO_MODEL = os.environ.get(
    "DOUBAO_MODEL",
    "ep-20260514111325-xjmj7",
)

SEARCH_RECENCY = os.environ.get("SEARCH_RECENCY", "month")
SEARCH_DELAY_SECONDS = float(os.environ.get("SEARCH_DELAY_SECONDS", "2.0"))
SEARCH_MAX_OUTPUT_TOKENS = int(os.environ.get("SEARCH_MAX_OUTPUT_TOKENS", "2048"))


# ========================
# 系统模式配置
# ========================
ENABLE_LLM = True
SKIP_QA = False  # --debug 模式下跳过所有质检


# ========================
# 竞品分析参数
# ========================
MIN_COMPETITORS = 3
MAX_COMPETITORS = 8
DEFAULT_COMPETITOR_COUNT = 5


# ========================
# LLM 调用参数
# ========================
LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS = 4096
