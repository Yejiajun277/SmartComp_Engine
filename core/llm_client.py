# -*- coding: utf-8 -*-
"""
core/llm_client.py — 豆包 LLM 调用封装
"""

import json
import re
import time
import asyncio
from datetime import datetime

import config


_call_stats = {"total": 0, "success": 0, "fallback": 0, "errors": []}
_last_call_error = ""  # 最近一次调用的失败原因
_last_finish_reason = ""  # 最近一次调用的 finish_reason（用于截断检测）
_last_usage = {}  # 最近一次调用的 token 用量

_EMPTY_RESULT = {
    "content": "",
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "model": "",
    "finish_reason": "",
    "duration_ms": 0.0,
    "timestamp": "",
}


def _normalize_provider(provider: str) -> str:
    aliases = {"doubao", "qianfan", "ollama"}
    provider = (provider or "").lower()
    return "doubao" if provider in aliases else provider


def _call_doubao(system_prompt: str, user_message: str,
                 temperature: float, max_tokens: int,
                 agent_id: str) -> dict:
    """调用豆包 OpenAI 兼容接口，返回结构化结果。"""
    import requests
    global _last_call_error, _last_finish_reason, _last_usage

    if not config.DOUBAO_API_KEY:
        _last_call_error = "api_key_missing"
        print(f"  [豆包] [{agent_id}] ⚠️ API密钥未配置，降级到规则引擎")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

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
        t0 = time.time()
        try:
            print(f"  [豆包] [{agent_id}] 🔄 调用豆包 (attempt {attempt + 1}, prompt长度: {prompt_len}字)...")
            resp = requests.post(api_url, headers=headers, json=payload, timeout=300)
            duration_ms = (time.time() - t0) * 1000
            result = resp.json()

            if resp.status_code >= 400 or "error" in result:
                error = result.get("error", {})
                message = error.get("message") or result
                error_type = error.get("type", "unknown")
                error_code = error.get("code", resp.status_code)
                _last_call_error = f"api_error({resp.status_code}, {error_type}, {error_code})"
                _last_finish_reason = ""
                _last_usage = {}
                print(f"  [豆包] [{agent_id}] ❌ API错误 (status={resp.status_code}, type={error_type}, code={error_code}): {str(message)[:500]}")
                if attempt == 0:
                    time.sleep(1)
                    continue
                return {**_EMPTY_RESULT, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

            message = result.get("choices", [{}])[0].get("message", {})
            content = message.get("content", "") or message.get("reasoning", "")
            finish_reason = result.get("choices", [{}])[0].get("finish_reason", "unknown")

            if not content:
                _last_call_error = f"empty_response(finish_reason={finish_reason})"
                _last_finish_reason = finish_reason
                _last_usage = {}
                print(f"  [豆包] [{agent_id}] ❌ 返回内容为空 (finish_reason={finish_reason})")
                return {**_EMPTY_RESULT, "finish_reason": finish_reason, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
            _last_call_error = ""
            _last_finish_reason = finish_reason
            _last_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
            truncation_warn = " ⚠️ 输出被截断(max_tokens耗尽)" if finish_reason == "length" else ""
            print(
                f"  [豆包] [{agent_id}] ✅ 调用成功 "
                f"(tokens: {prompt_tokens}+{completion_tokens}={total_tokens}, 输出长度: {len(content)}字, "
                f"finish={finish_reason}){truncation_warn}"
            )
            return {
                "content": content,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "model": result.get("model", config.DOUBAO_MODEL),
                "finish_reason": result.get("choices", [{}])[0].get("finish_reason", ""),
                "duration_ms": duration_ms,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        except requests.exceptions.Timeout:
            duration_ms = (time.time() - t0) * 1000
            _last_call_error = f"timeout(300s, attempt {attempt + 1})"
            _last_finish_reason = ""
            _last_usage = {}
            print(f"  [豆包] [{agent_id}] ⏱️ 请求超时 (attempt {attempt + 1})")
            if attempt == 0:
                continue
            return {**_EMPTY_RESULT, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}
        except requests.exceptions.ConnectionError as e:
            duration_ms = (time.time() - t0) * 1000
            _last_call_error = f"connection_error({str(e)[:200]})"
            _last_finish_reason = ""
            _last_usage = {}
            print(f"  [豆包] [{agent_id}] ❌ 连接失败 (attempt {attempt + 1}): {e}")
            if attempt == 0:
                time.sleep(2)
                continue
            return {**_EMPTY_RESULT, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

    return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


async def _async_call_doubao(system_prompt: str, user_message: str,
                             temperature: float, max_tokens: int,
                             agent_id: str) -> dict:
    """异步调用豆包 OpenAI 兼容接口，返回结构化结果。"""
    import httpx
    global _last_call_error, _last_finish_reason, _last_usage

    if not config.DOUBAO_API_KEY:
        _last_call_error = "api_key_missing"
        print(f"  [豆包] [{agent_id}] ⚠️ API密钥未配置，降级到规则引擎")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

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

    async with httpx.AsyncClient(timeout=300) as client:
        for attempt in range(2):
            t0 = time.time()
            try:
                print(f"  [豆包] [{agent_id}] 🔄 异步调用豆包 (attempt {attempt + 1}, prompt长度: {prompt_len}字)...")
                resp = await client.post(api_url, headers=headers, json=payload)
                duration_ms = (time.time() - t0) * 1000
                result = resp.json()

                if resp.status_code >= 400 or "error" in result:
                    error = result.get("error", {})
                    message = error.get("message") or result
                    error_type = error.get("type", "unknown")
                    error_code = error.get("code", resp.status_code)
                    _last_call_error = f"api_error({resp.status_code}, {error_type}, {error_code})"
                    _last_finish_reason = ""
                    _last_usage = {}
                    print(f"  [豆包] [{agent_id}] ❌ API错误 (status={resp.status_code}, type={error_type}, code={error_code}): {str(message)[:500]}")
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    return {**_EMPTY_RESULT, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

                message = result.get("choices", [{}])[0].get("message", {})
                content = message.get("content", "") or message.get("reasoning", "")
                finish_reason = result.get("choices", [{}])[0].get("finish_reason", "unknown")

                if not content:
                    _last_call_error = f"empty_response(finish_reason={finish_reason})"
                    _last_finish_reason = finish_reason
                    _last_usage = {}
                    print(f"  [豆包] [{agent_id}] ❌ 返回内容为空 (finish_reason={finish_reason})")
                    return {**_EMPTY_RESULT, "finish_reason": finish_reason, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

                usage = result.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
                _last_call_error = ""
                _last_finish_reason = finish_reason
                _last_usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
                truncation_warn = " ⚠️ 输出被截断(max_tokens耗尽)" if finish_reason == "length" else ""
                print(
                    f"  [豆包] [{agent_id}] ✅ 异步调用成功 "
                    f"(tokens: {prompt_tokens}+{completion_tokens}={total_tokens}, 输出长度: {len(content)}字, "
                    f"finish={finish_reason}){truncation_warn}"
                )
                return {
                    "content": content,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "model": result.get("model", config.DOUBAO_MODEL),
                    "finish_reason": finish_reason,
                    "duration_ms": duration_ms,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
            except httpx.TimeoutException:
                duration_ms = (time.time() - t0) * 1000
                _last_call_error = f"timeout(300s, attempt {attempt + 1})"
                _last_finish_reason = ""
                _last_usage = {}
                print(f"  [豆包] [{agent_id}] ⏱️ 请求超时 (attempt {attempt + 1})")
                if attempt == 0:
                    continue
                return {**_EMPTY_RESULT, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}
            except httpx.ConnectError as e:
                duration_ms = (time.time() - t0) * 1000
                _last_call_error = f"connection_error({str(e)[:200]})"
                _last_finish_reason = ""
                _last_usage = {}
                print(f"  [豆包] [{agent_id}] ❌ 连接失败 (attempt {attempt + 1}): {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                return {**_EMPTY_RESULT, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

    return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


def llm_call(system_prompt: str, user_message: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             agent_id: str = "") -> dict:
    """统一 LLM 调用入口。返回 dict，包含 content 和元数据。"""
    global _last_call_error
    _call_stats["total"] += 1
    call_label = f"[{agent_id}]" if agent_id else ""

    if not config.ENABLE_LLM:
        _last_call_error = "llm_disabled"
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ⏭️ LLM未启用，使用规则引擎")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    provider = _normalize_provider(config.LLM_PROVIDER)
    if provider != "doubao":
        _last_call_error = f"unknown_provider({config.LLM_PROVIDER})"
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ❌ 未知的LLM_PROVIDER: {config.LLM_PROVIDER}")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    try:
        result = _call_doubao(system_prompt, user_message, temperature, max_tokens, agent_id)
        if result["content"]:
            _call_stats["success"] += 1
            return result

        _call_stats["fallback"] += 1
        return result
    except ImportError:
        _last_call_error = "requests_not_installed"
        print(f"  [豆包] {call_label} ❌ requests未安装 (pip install requests)")
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}
    except Exception as e:
        _last_call_error = f"exception({type(e).__name__}: {str(e)[:200]})"
        print(f"  [豆包] {call_label} ❌ 异常: {e}")
        _call_stats["errors"].append(str(e))
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


async def async_llm_call(system_prompt: str, user_message: str,
                         temperature: float = 0.3, max_tokens: int = 4096,
                         agent_id: str = "") -> dict:
    """统一异步 LLM 调用入口。返回 dict，包含 content 和元数据。"""
    global _last_call_error
    _call_stats["total"] += 1
    call_label = f"[{agent_id}]" if agent_id else ""

    if not config.ENABLE_LLM:
        _last_call_error = "llm_disabled"
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ⏭️ LLM未启用，使用规则引擎")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    provider = _normalize_provider(config.LLM_PROVIDER)
    if provider != "doubao":
        _last_call_error = f"unknown_provider({config.LLM_PROVIDER})"
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ❌ 未知的LLM_PROVIDER: {config.LLM_PROVIDER}")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    try:
        result = await _async_call_doubao(system_prompt, user_message, temperature, max_tokens, agent_id)
        if result["content"]:
            _call_stats["success"] += 1
            return result

        _call_stats["fallback"] += 1
        return result
    except ImportError:
        _last_call_error = "httpx_not_installed"
        print(f"  [豆包] {call_label} ❌ httpx未安装 (pip install httpx)")
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}
    except Exception as e:
        _last_call_error = f"exception({type(e).__name__}: {str(e)[:200]})"
        print(f"  [豆包] {call_label} ❌ 异常: {e}")
        _call_stats["errors"].append(str(e))
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


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


def _format_json_error(source_name: str, error: json.JSONDecodeError, text_len: int) -> str:
    return (
        f"json_parse_error(source={source_name}, line={error.lineno}, "
        f"col={error.colno}, pos={error.pos}, msg={error.msg}, 文本长度={text_len})"
    )


def _try_parse_json(candidate: str, source_name: str, original_len: int) -> tuple[object, str]:
    try:
        return json.loads(candidate.strip()), ""
    except json.JSONDecodeError as e:
        return None, _format_json_error(source_name, e, original_len)


def parse_llm_json(text: str) -> dict:
    """解析 LLM 返回的 JSON。"""
    global _last_call_error
    if not text:
        return {}

    parse_errors = []
    parsed, error = _try_parse_json(text, "raw_text", len(text))
    if not error:
        return parsed
    parse_errors.append(error)

    code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
    for i, block in enumerate(code_blocks, 1):
        parsed, error = _try_parse_json(block, f"code_block_{i}", len(text))
        if not error:
            return parsed
        parse_errors.append(error)

    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        parsed, error = _try_parse_json(brace_match.group(0), "first_object", len(text))
        if not error:
            return parsed
        parse_errors.append(error)

    bracket_match = re.search(r"\[[\s\S]*\]", text)
    if bracket_match:
        parsed, error = _try_parse_json(bracket_match.group(0), "first_array", len(text))
        if not error:
            return parsed
        parse_errors.append(error)

    # Extra data 修复：LLM 有时在数组 JSON 后追加多余内容，找到最后一个 ] 截断后重试
    last_bracket = text.rfind("]")
    if last_bracket > 0:
        truncated = text[:last_bracket + 1]
        first_bracket = truncated.find("[")
        if first_bracket >= 0:
            candidate = truncated[first_bracket:]
            parsed, error = _try_parse_json(candidate, "last_array_fix", len(text))
            if not error:
                return parsed
            parse_errors.append(error)

    _last_call_error = parse_errors[-1] if parse_errors else f"json_parse_error(文本长度={len(text)})"
    print(f"  [LLM] ⚠️ JSON解析失败: {_last_call_error}")
    print(f"  [LLM] ⚠️ 原始文本前200字: {text[:200]}...")
    return {}


def get_last_call_error() -> str:
    """获取最近一次 LLM 调用的失败原因"""
    return _last_call_error


def get_last_finish_reason() -> str:
    """获取最近一次 LLM 调用的 finish_reason。'length' 表示输出被截断。"""
    return _last_finish_reason


def is_last_call_truncated() -> bool:
    """最近一次 LLM 调用是否因 max_tokens 耗尽而被截断。"""
    return _last_finish_reason == "length"


def get_last_usage() -> dict:
    """获取最近一次 LLM 调用的 token 用量。"""
    return dict(_last_usage)


def get_llm_stats() -> dict:
    """获取 LLM 调用统计。"""
    return _call_stats.copy()


def reset_llm_stats():
    """重置 LLM 调用统计。"""
    global _call_stats
    _call_stats = {"total": 0, "success": 0, "fallback": 0, "errors": []}
