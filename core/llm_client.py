# -*- coding: utf-8 -*-
"""
core/llm_client.py — MiMo LLM 调用封装
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
    "reasoning_tokens": 0,
    "cached_tokens": None,
    "uncached_tokens": None,
    "content_chars": 0,
    "total_tokens": 0,
    "model": "",
    "finish_reason": "",
    "duration_ms": 0.0,
    "timestamp": "",
    "usage_known": False,
    "usage_reported": False,
    "request_bytes": 0,
    "usage_reservation_tokens": 0,
}


def _mimo_payload(system_prompt, user_message, temperature, max_tokens, json_mode, thinking=None):
    """Keep the public max_tokens argument; send only MiMo's documented field."""
    payload = {
        "model": config.MIMO_MODEL,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_message}],
        "max_completion_tokens": max_tokens,
        "stream": False,
    }
    if thinking is not None:
        if thinking not in ("enabled", "disabled"):
            raise ValueError("thinking must be enabled or disabled")
        payload["thinking"] = {"type": thinking}
    if thinking != "enabled":
        payload["temperature"] = temperature
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _request_usage_reservation(payload):
    request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return {"request_bytes": request_bytes,
            "usage_reservation_tokens": request_bytes + payload["max_completion_tokens"] + 4096}


def _mimo_response(result, duration_ms, thinking=None, *, request_payload=None):
    """Reasoning is never a final answer; retain counts without storing its text."""
    choice = (result.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    content = content if isinstance(content, str) else ""
    raw_usage = result.get("usage")
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, dict) else {}
    raw_prompt, raw_completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    prompt_known = type(raw_prompt) is int and raw_prompt >= 0
    completion_known = type(raw_completion) is int and raw_completion >= 0
    prompt_tokens = raw_prompt if prompt_known else 0
    completion_tokens = raw_completion if completion_known else 0
    prompt_details = usage.get("prompt_tokens_details")
    cached_tokens = prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
    # Missing/invalid metadata is unknown, never evidence of a complete miss.
    if ("prompt_tokens" not in usage or type(prompt_tokens) is not int or prompt_tokens < 0
            or type(cached_tokens) is not int or not 0 <= cached_tokens <= prompt_tokens):
        cached_tokens = None
    uncached_tokens = prompt_tokens - cached_tokens if cached_tokens is not None else None
    return {
        "content": content, "content_chars": len(content),
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "reasoning_tokens": details.get("reasoning_tokens", 0) or 0,
        "cached_tokens": cached_tokens, "uncached_tokens": uncached_tokens,
        "total_tokens": usage.get("total_tokens", prompt_tokens + completion_tokens),
        "model": result.get("model", config.MIMO_MODEL),
        "finish_reason": choice.get("finish_reason", "unknown"),
        "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds"),
        "thinking": thinking,
        "usage_known": prompt_known and completion_known,
        "usage_reported": bool(usage),
        **(_request_usage_reservation(request_payload) if request_payload is not None else {}),
    }


def _normalize_provider(provider: str) -> str:
    aliases = {"mimo", "doubao", "qianfan", "ollama"}
    provider = (provider or "").lower()
    return "mimo" if provider in aliases else provider


def _response_format_is_unsupported(status_code: int, result: dict) -> bool:
    """Detect compatibility errors from endpoints without JSON mode support."""
    if status_code not in {400, 422}:
        return False
    try:
        detail = json.dumps(result, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        detail = str(result).lower()
    return "response_format" in detail and any(
        marker in detail
        for marker in ("unsupported", "not support", "unknown", "unrecognized", "invalid")
    )


def _call_mimo(system_prompt: str, user_message: str,
               temperature: float, max_tokens: int,
               agent_id: str, json_mode: bool = False, thinking: str | None = None) -> dict:
    """调用 MiMo OpenAI 兼容接口，返回结构化结果。"""
    import requests
    global _last_call_error, _last_finish_reason, _last_usage

    if not config.MIMO_API_KEY:
        _last_call_error = "api_key_missing"
        print(f"  [mimo] [{agent_id}] ⚠️ API密钥未配置，降级到规则引擎")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    api_url = f"{config.MIMO_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.MIMO_API_KEY}",
    }
    prompt_len = len(system_prompt) + len(user_message)
    payload = _mimo_payload(system_prompt, user_message, temperature, max_tokens, json_mode, thinking)

    def post_completion():
        with requests.Session() as session:
            session.trust_env = config.MIMO_USE_SYSTEM_PROXY
            return session.post(api_url, headers=headers, json=payload, timeout=300)

    reservation_total = 0
    for attempt in range(2):
        request_meta = _request_usage_reservation(payload)
        reservation_total += request_meta["usage_reservation_tokens"]
        request_meta["usage_reservation_tokens"] = reservation_total
        t0 = time.time()
        try:
            print(f"  [mimo] [{agent_id}] 🔄 调用 mimo (attempt {attempt + 1}, prompt长度: {prompt_len}字)...")
            resp = post_completion()
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
                print(f"  [mimo] [{agent_id}] ❌ API错误 (status={resp.status_code}, type={error_type}, code={error_code}): {str(message)[:500]}")
                if (
                    attempt == 0
                    and "response_format" in payload
                    and _response_format_is_unsupported(resp.status_code, result)
                ):
                    payload.pop("response_format", None)
                    print(f"  [mimo] [{agent_id}] ↩️ 当前接口不支持JSON模式，改用文本JSON兼容重试")
                    continue
                if attempt == 0:
                    time.sleep(1)
                    continue
                return {**_EMPTY_RESULT, **request_meta, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

            response = _mimo_response(result, duration_ms, thinking, request_payload=payload)
            response.update(request_meta)
            # A later response cannot settle usage of an earlier failed HTTP
            # attempt. Preserve the reported numbers, but reserve the full call.
            response["usage_known"] = response["usage_known"] and attempt == 0
            content, finish_reason = response["content"], response["finish_reason"]
            _last_finish_reason = finish_reason
            _last_usage = {key: response[key] for key in
                           ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
                            "cached_tokens", "uncached_tokens", "content_chars", "usage_known",
                            "usage_reported", "request_bytes", "usage_reservation_tokens")}

            if finish_reason == "content_filter":
                _last_call_error = "provider_content_filter"
                print(f"  [mimo] [{agent_id}] ❌ 提供方拒绝请求 (finish_reason=content_filter)")
                return response

            if not content:
                _last_call_error = f"empty_response(finish_reason={finish_reason})"
                print(f"  [mimo] [{agent_id}] ❌ 返回内容为空 (finish_reason={finish_reason})")
                return response

            prompt_tokens, completion_tokens = response["prompt_tokens"], response["completion_tokens"]
            total_tokens = response["total_tokens"]
            _last_call_error = ""
            truncation_warn = " ⚠️ 输出被截断(max_tokens耗尽)" if finish_reason == "length" else ""
            print(
                f"  [mimo] [{agent_id}] ✅ 调用成功 "
                f"(tokens: {prompt_tokens}+{completion_tokens}={total_tokens}, 输出长度: {len(content)}字, "
                f"finish={finish_reason}){truncation_warn}"
            )
            return response
        except requests.exceptions.Timeout:
            duration_ms = (time.time() - t0) * 1000
            _last_call_error = f"timeout(300s, attempt {attempt + 1})"
            _last_finish_reason = ""
            _last_usage = {}
            print(f"  [mimo] [{agent_id}] ⏱️ 请求超时 (attempt {attempt + 1})")
            if attempt == 0:
                continue
            return {**_EMPTY_RESULT, **request_meta, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}
        except requests.exceptions.ConnectionError as e:
            duration_ms = (time.time() - t0) * 1000
            _last_call_error = f"connection_error({str(e)[:200]})"
            _last_finish_reason = ""
            _last_usage = {}
            print(f"  [mimo] [{agent_id}] ❌ 连接失败 (attempt {attempt + 1}): {e}")
            if attempt == 0:
                time.sleep(2)
                continue
            return {**_EMPTY_RESULT, **request_meta, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

    return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


async def _async_call_mimo(system_prompt: str, user_message: str,
                           temperature: float, max_tokens: int,
                           agent_id: str, json_mode: bool = False, thinking: str | None = None) -> dict:
    """异步调用 MiMo OpenAI 兼容接口，返回结构化结果。"""
    import httpx
    import ssl
    global _last_call_error, _last_finish_reason, _last_usage

    # 修复 conda 环境中 SSL_CERT_FILE 指向不存在文件的问题
    import os
    _ssl_cert = os.environ.get("SSL_CERT_FILE", "")
    if _ssl_cert and not os.path.isfile(_ssl_cert):
        os.environ.pop("SSL_CERT_FILE", None)

    if not config.MIMO_API_KEY:
        _last_call_error = "api_key_missing"
        print(f"  [mimo] [{agent_id}] ⚠️ API密钥未配置，降级到规则引擎")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    api_url = f"{config.MIMO_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.MIMO_API_KEY}",
    }
    prompt_len = len(system_prompt) + len(user_message)
    payload = _mimo_payload(system_prompt, user_message, temperature, max_tokens, json_mode, thinking)

    async with httpx.AsyncClient(
        timeout=300,
        trust_env=config.MIMO_USE_SYSTEM_PROXY,
    ) as client:
        reservation_total = 0
        for attempt in range(2):
            request_meta = _request_usage_reservation(payload)
            reservation_total += request_meta["usage_reservation_tokens"]
            request_meta["usage_reservation_tokens"] = reservation_total
            t0 = time.time()
            try:
                print(f"  [mimo] [{agent_id}] 🔄 异步调用 mimo (attempt {attempt + 1}, prompt长度: {prompt_len}字)...")
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
                    print(f"  [mimo] [{agent_id}] ❌ API错误 (status={resp.status_code}, type={error_type}, code={error_code}): {str(message)[:500]}")
                    if (
                        attempt == 0
                        and "response_format" in payload
                        and _response_format_is_unsupported(resp.status_code, result)
                    ):
                        payload.pop("response_format", None)
                        print(f"  [mimo] [{agent_id}] ↩️ 当前接口不支持JSON模式，改用文本JSON兼容重试")
                        continue
                    if attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    return {**_EMPTY_RESULT, **request_meta, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

                response = _mimo_response(result, duration_ms, thinking, request_payload=payload)
                response.update(request_meta)
                response["usage_known"] = response["usage_known"] and attempt == 0
                content, finish_reason = response["content"], response["finish_reason"]
                _last_finish_reason = finish_reason
                _last_usage = {key: response[key] for key in
                               ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
                                "cached_tokens", "uncached_tokens", "content_chars", "usage_known",
                                "usage_reported", "request_bytes", "usage_reservation_tokens")}

                if finish_reason == "content_filter":
                    _last_call_error = "provider_content_filter"
                    print(f"  [mimo] [{agent_id}] ❌ 提供方拒绝请求 (finish_reason=content_filter)")
                    return response

                if not content:
                    _last_call_error = f"empty_response(finish_reason={finish_reason})"
                    print(f"  [mimo] [{agent_id}] ❌ 返回内容为空 (finish_reason={finish_reason})")
                    return response

                prompt_tokens, completion_tokens = response["prompt_tokens"], response["completion_tokens"]
                total_tokens = response["total_tokens"]
                _last_call_error = ""
                truncation_warn = " ⚠️ 输出被截断(max_tokens耗尽)" if finish_reason == "length" else ""
                print(
                    f"  [mimo] [{agent_id}] ✅ 异步调用成功 "
                    f"(tokens: {prompt_tokens}+{completion_tokens}={total_tokens}, 输出长度: {len(content)}字, "
                    f"finish={finish_reason}){truncation_warn}"
                )
                return response
            except httpx.TimeoutException:
                duration_ms = (time.time() - t0) * 1000
                _last_call_error = f"timeout(300s, attempt {attempt + 1})"
                _last_finish_reason = ""
                _last_usage = {}
                print(f"  [mimo] [{agent_id}] ⏱️ 请求超时 (attempt {attempt + 1})")
                if attempt == 0:
                    continue
                return {**_EMPTY_RESULT, **request_meta, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}
            except httpx.ConnectError as e:
                duration_ms = (time.time() - t0) * 1000
                _last_call_error = f"connection_error({str(e)[:200]})"
                _last_finish_reason = ""
                _last_usage = {}
                print(f"  [mimo] [{agent_id}] ❌ 连接失败 (attempt {attempt + 1}): {e}")
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                return {**_EMPTY_RESULT, **request_meta, "duration_ms": duration_ms, "timestamp": datetime.now().isoformat(timespec="seconds")}

    return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


def llm_call(system_prompt: str, user_message: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             agent_id: str = "", json_mode: bool = False, *, thinking: str | None = None) -> dict:
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
    if provider != "mimo":
        _last_call_error = f"unknown_provider({config.LLM_PROVIDER})"
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ❌ 未知的LLM_PROVIDER: {config.LLM_PROVIDER}")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    try:
        result = _call_mimo(
            system_prompt,
            user_message,
            temperature,
            max_tokens,
            agent_id,
            json_mode=json_mode, **({"thinking": thinking} if thinking is not None else {}),
        )
        if result["content"] and result.get("finish_reason") != "content_filter":
            _call_stats["success"] += 1
            return result

        _call_stats["fallback"] += 1
        return result
    except ImportError:
        _last_call_error = "requests_not_installed"
        print(f"  [mimo] {call_label} ❌ requests未安装 (pip install requests)")
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}
    except Exception as e:
        _last_call_error = f"exception({type(e).__name__}: {str(e)[:200]})"
        print(f"  [mimo] {call_label} ❌ 异常: {e}")
        _call_stats["errors"].append(str(e))
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


async def async_llm_call(system_prompt: str, user_message: str,
                         temperature: float = 0.3, max_tokens: int = 4096,
                         agent_id: str = "", json_mode: bool = False, *, thinking: str | None = None) -> dict:
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
    if provider != "mimo":
        _last_call_error = f"unknown_provider({config.LLM_PROVIDER})"
        _call_stats["fallback"] += 1
        print(f"  [LLM] {call_label} ❌ 未知的LLM_PROVIDER: {config.LLM_PROVIDER}")
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}

    try:
        result = await _async_call_mimo(
            system_prompt,
            user_message,
            temperature,
            max_tokens,
            agent_id,
            json_mode=json_mode, **({"thinking": thinking} if thinking is not None else {}),
        )
        if result["content"] and result.get("finish_reason") != "content_filter":
            _call_stats["success"] += 1
            return result

        _call_stats["fallback"] += 1
        return result
    except ImportError:
        _last_call_error = "httpx_not_installed"
        print(f"  [mimo] {call_label} ❌ httpx未安装 (pip install httpx)")
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}
    except Exception as e:
        _last_call_error = f"exception({type(e).__name__}: {str(e)[:200]})"
        print(f"  [mimo] {call_label} ❌ 异常: {e}")
        _call_stats["errors"].append(str(e))
        _call_stats["fallback"] += 1
        return {**_EMPTY_RESULT, "timestamp": datetime.now().isoformat(timespec="seconds")}


def check_llm_backend() -> dict:
    """检查当前 LLM 后端可用性。"""
    provider = _normalize_provider(config.LLM_PROVIDER)

    if provider != "mimo":
        return {
            "provider": provider,
            "available": False,
            "model": "",
            "detail": f"未知的LLM_PROVIDER: {config.LLM_PROVIDER}",
        }

    if not config.MIMO_API_KEY.strip():
        return {
            "provider": "mimo",
            "available": False,
            "model": config.MIMO_MODEL,
            "detail": "mimo API密钥未配置",
        }

    return {
        "provider": "mimo",
        "available": True,
        "model": config.MIMO_MODEL,
        "detail": "mimo API密钥已配置",
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
