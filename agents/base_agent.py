# -*- coding: utf-8 -*-
"""
agents/base_agent.py — Agent基类

所有竞品分析智能体继承此基类，获得LLM调用、日志记录等基础能力。
"""

from abc import ABC, abstractmethod
from core.llm_client import llm_call, async_llm_call, parse_llm_json, get_last_call_error
import config
import json
import re

_LOG_TEXT_MAX = 2000  # 日志中 prompt/output 截断长度


class BaseAgent(ABC):
    """
    竞品分析智能体基类

    职责：
    1. 管理Agent标识和日志
    2. 封装LLM调用接口
    3. 定义统一执行接口
    """

    def __init__(self, agent_id: str, system_prompt: str = ""):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.log: list[str] = []
        self.llm_logs: list[dict] = []
        self.on_log_added = None  # callback(log_entry: dict) — 每次 llm_logs 追加后调用

    def _log(self, message: str):
        """记录Agent日志"""
        entry = f"[{self.agent_id}] {message}"
        self.log.append(entry)
        print(entry)

    def ask_llm(self, user_message: str,
                temperature: float = None,
                max_tokens: int = None,
                json_mode: bool = False, *, thinking: str | None = None) -> str:
        """调用LLM做决策"""
        temp = temperature if temperature is not None else config.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS

        result = llm_call(self.system_prompt, user_message,
                          temperature=temp, max_tokens=tokens,
                          agent_id=self.agent_id, json_mode=json_mode,
                          **({"thinking": thinking} if thinking is not None else {}))

        content = result.get("content", "") if isinstance(result, dict) else (result or "")
        usage = result.get("usage", {}) if isinstance(result, dict) else {}

        self.llm_logs.append({
            "agent_id": self.agent_id,
            "timestamp": result.get("timestamp", "") if isinstance(result, dict) else "",
            "system_prompt": (self.system_prompt or "")[:_LOG_TEXT_MAX],
            "user_message": (user_message or "")[:_LOG_TEXT_MAX],
            "result": content[:_LOG_TEXT_MAX] if content else "",
            "prompt_tokens": result.get("prompt_tokens", 0) if isinstance(result, dict) else 0,
            "completion_tokens": result.get("completion_tokens", 0) if isinstance(result, dict) else 0,
            "reasoning_tokens": result.get("reasoning_tokens", 0) if isinstance(result, dict) else 0,
            "cached_tokens": result.get("cached_tokens") if isinstance(result, dict) else None,
            "uncached_tokens": result.get("uncached_tokens") if isinstance(result, dict) else None,
            "usage_known": result.get("usage_known") if isinstance(result, dict) else False,
            "usage_reported": result.get("usage_reported") if isinstance(result, dict) else False,
            "request_bytes": result.get("request_bytes", 0) if isinstance(result, dict) else 0,
            "usage_reservation_tokens": result.get("usage_reservation_tokens", 0) if isinstance(result, dict) else 0,
            "content_chars": len(content) if isinstance(content, str) else 0,
            "total_tokens": result.get("total_tokens", 0) if isinstance(result, dict) else 0,
            "duration_ms": result.get("duration_ms", 0.0) if isinstance(result, dict) else 0.0,
            "model": result.get("model", "") if isinstance(result, dict) else "",
            "finish_reason": result.get("finish_reason", "") if isinstance(result, dict) else "",
            "temperature": None if thinking == "enabled" else temp,
            "requested_temperature": temp,
            "thinking": thinking,
            "max_completion_tokens": tokens,
            "max_tokens": tokens,
            "success": bool(content) and result.get("finish_reason") != "content_filter" if isinstance(result, dict) else bool(content),
            "parse_error": "",
            # Prompt 归档（可选，通过 config 控制）
            "system_prompt_archive": self.system_prompt if config.ARCHIVE_PROMPTS else "",
            "user_message_archive": user_message if config.ARCHIVE_PROMPTS else "",
            "max_tokens_requested": tokens,
        })

        if self.on_log_added:
            try:
                self.on_log_added(self.llm_logs[-1])
            except Exception:
                pass

        return "" if self.llm_logs[-1].get("finish_reason") == "content_filter" else content

    def ask_llm_json(self, user_message: str,
                     temperature: float = None,
                     max_tokens: int = None) -> dict:
        """调用LLM并解析JSON返回"""
        text = self.ask_llm(
            user_message,
            temperature,
            max_tokens,
            json_mode=True,
        )
        if text:
            parsed = parse_llm_json(text)
            if parsed:
                return parsed
            else:
                if self.llm_logs:
                    self.llm_logs[-1]["parse_error"] = get_last_call_error() or "json_parse_error"
                self._log(f"   ⚠️ LLM返回了文本但JSON解析失败，降级到规则引擎")
        return {}

    def ask_llm_json_with_reason(self, user_message: str,
                                 temperature: float = None,
                                 max_tokens: int = None, *, thinking: str | None = None) -> tuple[dict, str]:
        """调用LLM并解析JSON返回，附带失败原因"""
        text = self.ask_llm(
            user_message,
            temperature,
            max_tokens,
            json_mode=True,
            **({"thinking": thinking} if thinking is not None else {}),
        )
        if self.llm_logs and self.llm_logs[-1].get("finish_reason") == "content_filter":
            self.llm_logs[-1]["parse_error"] = "provider_content_filter"
            return {}, "provider_content_filter"
        if self.llm_logs and self.llm_logs[-1].get("finish_reason") == "length":
            reason = "truncated_output(finish_reason=length)"
            self.llm_logs[-1]["parse_error"] = reason
            self._log(f"   ⚠️ JSON响应未完整结束: {reason}")
            return {}, reason
        if text:
            parsed = parse_llm_json(text)
            if parsed:
                return parsed, "success"
            else:
                reason = get_last_call_error() or "json_parse_error"
                if self.llm_logs:
                    self.llm_logs[-1]["parse_error"] = reason
                self._log(f"   ⚠️ LLM返回了文本但JSON解析失败: {reason}")
                return {}, reason
        reason = get_last_call_error() or "empty_response"
        return {}, reason

    async def async_ask_llm(self, user_message: str,
                            temperature: float = None,
                            max_tokens: int = None,
                            json_mode: bool = False, *, thinking: str | None = None) -> str:
        """异步调用LLM做决策"""
        temp = temperature if temperature is not None else config.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS

        result = await async_llm_call(self.system_prompt, user_message,
                                      temperature=temp, max_tokens=tokens,
                                      agent_id=self.agent_id, json_mode=json_mode,
                                      **({"thinking": thinking} if thinking is not None else {}))

        content = result.get("content", "") if isinstance(result, dict) else (result or "")

        self.llm_logs.append({
            "agent_id": self.agent_id,
            "timestamp": result.get("timestamp", "") if isinstance(result, dict) else "",
            "system_prompt": (self.system_prompt or "")[:_LOG_TEXT_MAX],
            "user_message": (user_message or "")[:_LOG_TEXT_MAX],
            "result": content[:_LOG_TEXT_MAX] if content else "",
            "prompt_tokens": result.get("prompt_tokens", 0) if isinstance(result, dict) else 0,
            "completion_tokens": result.get("completion_tokens", 0) if isinstance(result, dict) else 0,
            "reasoning_tokens": result.get("reasoning_tokens", 0) if isinstance(result, dict) else 0,
            "cached_tokens": result.get("cached_tokens") if isinstance(result, dict) else None,
            "uncached_tokens": result.get("uncached_tokens") if isinstance(result, dict) else None,
            "usage_known": result.get("usage_known") if isinstance(result, dict) else False,
            "usage_reported": result.get("usage_reported") if isinstance(result, dict) else False,
            "request_bytes": result.get("request_bytes", 0) if isinstance(result, dict) else 0,
            "usage_reservation_tokens": result.get("usage_reservation_tokens", 0) if isinstance(result, dict) else 0,
            "content_chars": len(content) if isinstance(content, str) else 0,
            "total_tokens": result.get("total_tokens", 0) if isinstance(result, dict) else 0,
            "duration_ms": result.get("duration_ms", 0.0) if isinstance(result, dict) else 0.0,
            "model": result.get("model", "") if isinstance(result, dict) else "",
            "finish_reason": result.get("finish_reason", "") if isinstance(result, dict) else "",
            "temperature": None if thinking == "enabled" else temp,
            "requested_temperature": temp,
            "thinking": thinking,
            "max_completion_tokens": tokens,
            "max_tokens": tokens,
            "success": bool(content) and result.get("finish_reason") != "content_filter" if isinstance(result, dict) else bool(content),
            "parse_error": "",
        })

        if self.on_log_added:
            try:
                self.on_log_added(self.llm_logs[-1])
            except Exception:
                pass

        return "" if self.llm_logs[-1].get("finish_reason") == "content_filter" else content

    async def async_ask_llm_json(self, user_message: str,
                                 temperature: float = None,
                                 max_tokens: int = None) -> dict:
        """异步调用LLM并解析JSON返回"""
        text = await self.async_ask_llm(
            user_message,
            temperature,
            max_tokens,
            json_mode=True,
        )
        if text:
            parsed = parse_llm_json(text)
            if parsed:
                return parsed
            if self.llm_logs:
                self.llm_logs[-1]["parse_error"] = get_last_call_error() or "json_parse_error"
            self._log(f"   ⚠️ LLM返回了文本但JSON解析失败，降级到规则引擎")
        return {}

    async def async_ask_llm_json_with_reason(self, user_message: str,
                                             temperature: float = None,
                                             max_tokens: int = None, *, thinking: str | None = None) -> tuple[dict, str]:
        """异步调用LLM并解析JSON返回，附带失败原因"""
        text = await self.async_ask_llm(
            user_message,
            temperature,
            max_tokens,
            json_mode=True,
            **({"thinking": thinking} if thinking is not None else {}),
        )
        if self.llm_logs and self.llm_logs[-1].get("finish_reason") == "content_filter":
            self.llm_logs[-1]["parse_error"] = "provider_content_filter"
            return {}, "provider_content_filter"
        if self.llm_logs and self.llm_logs[-1].get("finish_reason") == "length":
            reason = "truncated_output(finish_reason=length)"
            self.llm_logs[-1]["parse_error"] = reason
            self._log(f"   ⚠️ JSON响应未完整结束: {reason}")
            return {}, reason
        if text:
            parsed = parse_llm_json(text)
            if parsed:
                return parsed, "success"
            reason = get_last_call_error() or "json_parse_error"
            if self.llm_logs:
                self.llm_logs[-1]["parse_error"] = reason
            self._log(f"   ⚠️ LLM返回了文本但JSON解析失败: {reason}")
            return {}, reason
        reason = get_last_call_error() or "empty_response"
        return {}, reason

    async def async_ask_llm_json_with_truncation_check(self, user_message: str,
                                                        temperature: float = None,
                                                        max_tokens: int = None) -> tuple[dict, bool]:
        """异步调用LLM并解析JSON，同时检测输出是否被截断。"""
        text = await self.async_ask_llm(
            user_message,
            temperature,
            max_tokens,
            json_mode=True,
        )
        truncated = bool(self.llm_logs and self.llm_logs[-1].get("finish_reason") == "length")

        if text:
            parsed = parse_llm_json(text)
            if parsed:
                if truncated:
                    self._log(f"   ⚠️ JSON解析成功但输出被截断(max_tokens耗尽)，部分内容可能缺失")
                return parsed, truncated
            else:
                if self.llm_logs:
                    self.llm_logs[-1]["parse_error"] = get_last_call_error() or "json_parse_error"
                if truncated:
                    self._log(f"   ⚠️ 输出被截断且JSON解析失败，需要分片重试")
                else:
                    self._log(f"   ⚠️ LLM返回了文本但JSON解析失败，降级到规则引擎")
                return {}, truncated
        return {}, truncated

    def ask_llm_json_with_truncation_check(self, user_message: str,
                                            temperature: float = None,
                                            max_tokens: int = None) -> tuple[dict, bool]:
        """
        调用LLM并解析JSON，同时检测输出是否被截断。

        Returns:
            (parsed_dict, was_truncated):
            - parsed_dict: 解析成功返回dict，失败返回{}
            - was_truncated: True 表示 finish_reason=='length'，输出被截断
        """
        text = self.ask_llm(
            user_message,
            temperature,
            max_tokens,
            json_mode=True,
        )
        truncated = bool(self.llm_logs and self.llm_logs[-1].get("finish_reason") == "length")

        if text:
            parsed = parse_llm_json(text)
            if parsed:
                if truncated:
                    self._log(f"   ⚠️ JSON解析成功但输出被截断(max_tokens耗尽)，部分内容可能缺失")
                return parsed, truncated
            else:
                if self.llm_logs:
                    self.llm_logs[-1]["parse_error"] = get_last_call_error() or "json_parse_error"
                if truncated:
                    self._log(f"   ⚠️ 输出被截断且JSON解析失败，需要分片重试")
                else:
                    self._log(f"   ⚠️ LLM返回了文本但JSON解析失败，降级到规则引擎")
                return {}, truncated
        return {}, truncated

    @staticmethod
    def build_citations_text(citations: list, with_snippet: bool = True, max_snippet: int = 200) -> str:
        """将引用列表格式化为 LLM 可读的来源编号文本"""
        if not citations:
            return ""
        lines = []
        for c in citations:
            line = f"  [{c.id}] {c.title}"
            if c.site_name:
                line += f" ({c.site_name})"
            if c.url:
                line += f" — {c.url}"
            if with_snippet and c.snippet:
                snippet = c.snippet[:max_snippet].replace("\n", " ").strip()
                if snippet:
                    line += f"\n    内容摘要: {snippet}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def extract_citation_ids(data: dict) -> list[str]:
        """从 LLM 输出的 dict 中提取所有引用 ID"""
        from core.report_citations import extract_inline_citation_ids

        explicit = data.get("citations", [])
        explicit = [explicit] if isinstance(explicit, str) else explicit
        ids = []
        for value in explicit if isinstance(explicit, (list, tuple)) else []:
            if not isinstance(value, str):
                continue
            value = value.strip()
            wrapped = extract_inline_citation_ids(value)
            if wrapped:
                ids.extend(wrapped)
            elif value:
                ids.append(value[1:-1].strip() if value.startswith("[") and value.endswith("]") else value)

        def collect(value):
            if isinstance(value, str):
                ids.extend(extract_inline_citation_ids(value))
            elif isinstance(value, dict):
                for nested in value.values():
                    collect(nested)
            elif isinstance(value, (list, tuple)):
                for nested in value:
                    collect(nested)

        collect(data)
        return list(dict.fromkeys(ids))

    @abstractmethod
    async def run(self, *args, **kwargs):
        """Agent主运行逻辑（子类实现）"""
        pass

    def get_status(self) -> dict:
        """获取Agent状态"""
        return {
            "agent_id": self.agent_id,
            "log_count": len(self.log),
            "llm_call_count": len(self.llm_logs),
            "llm_success_count": sum(1 for l in self.llm_logs if l["success"]),
        }
