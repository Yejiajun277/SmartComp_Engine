# -*- coding: utf-8 -*-
"""
agents/base_agent.py - Agent 基类
"""

from abc import ABC, abstractmethod
from datetime import datetime

import config
from core.llm_client import llm_call, parse_llm_json


class BaseAgent(ABC):
    def __init__(self, agent_id: str, system_prompt: str = ""):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.log: list[str] = []
        self.llm_logs: list[dict] = []

    def _log(self, message: str):
        entry = f"[{self.agent_id}] {message}"
        self.log.append(entry)
        try:
            print(entry)
        except UnicodeEncodeError:
            safe_entry = entry.encode("utf-8", errors="replace").decode(
                "utf-8", errors="replace"
            )
            print(safe_entry)

    def ask_llm(
        self,
        user_message: str,
        temperature: float = None,
        max_tokens: int = None,
    ) -> str:
        temp = temperature if temperature is not None else config.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS

        result = llm_call(
            self.system_prompt,
            user_message,
            temperature=temp,
            max_tokens=tokens,
            agent_id=self.agent_id,
        )

        self.llm_logs.append(
            {
                "agent_id": self.agent_id,
                "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                "system_prompt_preview": self.system_prompt[:300],
                "user_message_preview": user_message[:600],
                "result_preview": result[:600] if result else "",
                "system_prompt_len": len(self.system_prompt),
                "user_message_len": len(user_message),
                "result_len": len(result) if result else 0,
                "prompt_tokens_estimate": max(1, (len(self.system_prompt) + len(user_message)) // 4),
                "completion_tokens_estimate": max(0, len(result) // 4) if result else 0,
                "temperature": temp,
                "max_tokens": tokens,
                "success": bool(result),
            }
        )
        return result

    def ask_llm_json(
        self,
        user_message: str,
        temperature: float = None,
        max_tokens: int = None,
    ) -> dict:
        text = self.ask_llm(user_message, temperature, max_tokens)
        if text:
            parsed = parse_llm_json(text)
            if parsed:
                return parsed
            self._log("LLM 返回文本但 JSON 解析失败，降级到规则引擎")
        return {}

    @abstractmethod
    async def run(self, *args, **kwargs):
        pass

    def get_status(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "log_count": len(self.log),
            "llm_call_count": len(self.llm_logs),
            "llm_success_count": sum(1 for item in self.llm_logs if item["success"]),
        }
