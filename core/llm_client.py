# -*- coding: utf-8 -*-
"""
core/llm_client.py — 豆包 LLM 调用封装
"""

import json
import re
import time

import config


_call_stats = {"total": 0, "success": 0, "fallback": 0, "errors": []}


def _normalize_provider(provider: str) -> str:
    aliases = {"doubao", "qianfan", "ollama"}
    provider = (provider or "").lower()
    return "doubao" if provider in aliases else provider


def _call_doubao(system_prompt: str, user_message: str,
                 temperature: float, max_tokens: int,
                 agent_id: str) -> str:
    """调用豆包 OpenAI 兼容接口。"""
    import requests

    if not config.DOUBAO_API_KEY:
        print(f"  [豆包] [{agent_id}] ⚠️ API密钥未配置，降级到规则引擎")
        return ""

    api_url = f"{config.DOUBAO_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.DOUBAO_API_KEY}",
    }
    payload = {
        "model": config.DOUBAO_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    for attempt in range(2):
        try:
            print(f"  [豆包] [{agent_id}] 🔄 调用豆包 (attempt {attempt + 1})...")
            resp = requests.post(api_url, headers=headers, json=payload, timeout=300)
            result = resp.json()

            if resp.status_code >= 400 or "error" in result:
                error = result.get("error", {})
                message = error.get("message") or result
                print(f"  [豆包] [{agent_id}] ❌ API错误: {message}")
                if attempt == 0:
                    time.sleep(1)
                    continue
                return ""

            message = result.get("choices", [{}])[0].get("message", {})
            content = message.get("content", "") or message.get("reasoning", "")

            if not content:
                print(f"  [豆包] [{agent_id}] ❌ 返回内容为空")
                return ""

            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", "?")
            completion_tokens = usage.get("completion_tokens", "?")
            print(
                f"  [豆包] [{agent_id}] ✅ 调用成功 "
                f"(tokens: {prompt_tokens}+{completion_tokens}, 输出长度: {len(content)}字)"
            )
            return content
        except requests.exceptions.Timeout:
            print(f"  [豆包] [{agent_id}] ⏱️ 请求超时 (attempt {attempt + 1})")
            if attempt == 0:
                continue
            return ""
        except requests.exceptions.ConnectionError as e:
            print(f"  [豆包] [{agent_id}] ❌ 连接失败: {e}")
            return ""

    return ""


def llm_call(system_prompt: str, user_message: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             agent_id: str = "") -> str:
    """统一 LLM 调用入口。"""
    _call_stats["total"] += 1
    call_label = f"[{agent_id}]" if agent_id else ""

    if not config.ENABLE_LLM:
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ⏭️ LLM未启用，使用规则引擎")
        return ""

    provider = _normalize_provider(config.LLM_PROVIDER)
    if provider != "doubao":
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ❌ 未知的LLM_PROVIDER: {config.LLM_PROVIDER}")
        return ""

    try:
        result = _call_doubao(system_prompt, user_message, temperature, max_tokens, agent_id)
        if result:
            _call_stats["success"] += 1
            return result

        _call_stats["fallback"] += 1
        return ""
    except ImportError:
        print(f"  [豆包] {call_label} ❌ requests未安装 (pip install requests)")
        _call_stats["fallback"] += 1
        return ""
    except Exception as e:
        print(f"  [豆包] {call_label} ❌ 异常: {e}")
        _call_stats["errors"].append(str(e))
        _call_stats["fallback"] += 1
        return ""


def check_llm_backend() -> dict:
    """检查当前 LLM 后端可用性。"""
    provider = _normalize_provider(config.LLM_PROVIDER)

    if provider != "doubao":
        return {
            "provider": provider,
            "available": False,
            "model": "",
            "detail": f"未知的LLM_PROVIDER: {config.LLM_PROVIDER}",
        }

    if not config.DOUBAO_API_KEY:
        return {
            "provider": "doubao",
            "available": False,
            "model": config.DOUBAO_MODEL,
            "detail": "豆包API密钥未配置",
        }

    return {
        "provider": "doubao",
        "available": True,
        "model": config.DOUBAO_MODEL,
        "detail": "豆包API密钥已配置",
    }


def parse_llm_json(text: str) -> dict:
    """解析 LLM 返回的 JSON。"""
    if not text:
        return {}

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    bracket_match = re.search(r"\[[\s\S]*\]", text)
    if bracket_match:
        try:
            return json.loads(bracket_match.group(0))
        except json.JSONDecodeError:
            pass

    print(f"  [LLM] ⚠️ JSON解析失败，原始文本前200字: {text[:200]}...")
    return {}


def get_llm_stats() -> dict:
    """获取 LLM 调用统计。"""
    return _call_stats.copy()


def reset_llm_stats():
    """重置 LLM 调用统计。"""
    global _call_stats
    _call_stats = {"total": 0, "success": 0, "fallback": 0, "errors": []}
