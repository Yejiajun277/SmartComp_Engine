# -*- coding: utf-8 -*-
"""
core/llm_client.py — 豆包 LLM 调用封装
"""

import json
import re
import time

import config


_call_stats = {"total": 0, "success": 0, "fallback": 0, "errors": []}
_last_call_error = ""  # 最近一次调用的失败原因


def _normalize_provider(provider: str) -> str:
    aliases = {"doubao", "qianfan", "ollama"}
    provider = (provider or "").lower()
    return "doubao" if provider in aliases else provider


def _call_doubao(system_prompt: str, user_message: str,
                 temperature: float, max_tokens: int,
                 agent_id: str) -> str:
    """调用豆包 OpenAI 兼容接口。"""
    import requests
    global _last_call_error

    if not config.DOUBAO_API_KEY:
        _last_call_error = "api_key_missing"
        print(f"  [豆包] [{agent_id}] ⚠️ API密钥未配置，降级到规则引擎")
        return ""

    api_url = f"{config.DOUBAO_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.DOUBAO_API_KEY}",
    }
    prompt_len = len(system_prompt) + len(user_message)
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
            print(f"  [豆包] [{agent_id}] 🔄 调用豆包 (attempt {attempt + 1}, prompt长度: {prompt_len}字)...")
            resp = requests.post(api_url, headers=headers, json=payload, timeout=300)
            result = resp.json()

            if resp.status_code >= 400 or "error" in result:
                error = result.get("error", {})
                message = error.get("message") or result
                error_type = error.get("type", "unknown")
                error_code = error.get("code", resp.status_code)
                _last_call_error = f"api_error({resp.status_code}, {error_type}, {error_code})"
                print(f"  [豆包] [{agent_id}] ❌ API错误 (status={resp.status_code}, type={error_type}, code={error_code}): {str(message)[:500]}")
                if attempt == 0:
                    time.sleep(1)
                    continue
                return ""

            message = result.get("choices", [{}])[0].get("message", {})
            content = message.get("content", "") or message.get("reasoning", "")

            if not content:
                finish_reason = result.get("choices", [{}])[0].get("finish_reason", "unknown")
                _last_call_error = f"empty_response(finish_reason={finish_reason})"
                print(f"  [豆包] [{agent_id}] ❌ 返回内容为空 (finish_reason={finish_reason})")
                return ""

            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", "?")
            completion_tokens = usage.get("completion_tokens", "?")
            _last_call_error = ""
            print(
                f"  [豆包] [{agent_id}] ✅ 调用成功 "
                f"(tokens: {prompt_tokens}+{completion_tokens}, 输出长度: {len(content)}字)"
            )
            return content
        except requests.exceptions.Timeout:
            _last_call_error = f"timeout(300s, attempt {attempt + 1})"
            print(f"  [豆包] [{agent_id}] ⏱️ 请求超时 (attempt {attempt + 1})")
            if attempt == 0:
                continue
            return ""
        except requests.exceptions.ConnectionError as e:
            _last_call_error = f"connection_error({str(e)[:200]})"
            print(f"  [豆包] [{agent_id}] ❌ 连接失败 (attempt {attempt + 1}): {e}")
            if attempt == 0:
                time.sleep(2)
                continue
            return ""

    return ""


def llm_call(system_prompt: str, user_message: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             agent_id: str = "") -> str:
    """统一 LLM 调用入口。"""
    global _last_call_error
    _call_stats["total"] += 1
    call_label = f"[{agent_id}]" if agent_id else ""

    if not config.ENABLE_LLM:
        _last_call_error = "llm_disabled"
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ⏭️ LLM未启用，使用规则引擎")
        return ""

    provider = _normalize_provider(config.LLM_PROVIDER)
    if provider != "doubao":
        _last_call_error = f"unknown_provider({config.LLM_PROVIDER})"
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
        _last_call_error = "requests_not_installed"
        print(f"  [豆包] {call_label} ❌ requests未安装 (pip install requests)")
        _call_stats["fallback"] += 1
        return ""
    except Exception as e:
        _last_call_error = f"exception({type(e).__name__}: {str(e)[:200]})"
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
    global _last_call_error
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

    _last_call_error = f"json_parse_error(文本长度={len(text)}, 前100字={text[:100]!r})"
    print(f"  [LLM] ⚠️ JSON解析失败，原始文本前200字: {text[:200]}...")
    return {}


def get_last_call_error() -> str:
    """获取最近一次 LLM 调用的失败原因"""
    return _last_call_error


def get_llm_stats() -> dict:
    """获取 LLM 调用统计。"""
    return _call_stats.copy()


def reset_llm_stats():
    """重置 LLM 调用统计。"""
    global _call_stats
    _call_stats = {"total": 0, "success": 0, "fallback": 0, "errors": []}
