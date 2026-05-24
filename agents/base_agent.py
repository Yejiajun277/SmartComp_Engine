# -*- coding: utf-8 -*-
"""
agents/base_agent.py — Agent基类

所有竞品分析智能体继承此基类，获得LLM调用、日志记录等基础能力。
"""

from abc import ABC, abstractmethod
from core.llm_client import llm_call, parse_llm_json
import config


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

    def _log(self, message: str):
        """记录Agent日志"""
        entry = f"[{self.agent_id}] {message}"
        self.log.append(entry)
        print(entry)

    def ask_llm(self, user_message: str,
                temperature: float = None,
                max_tokens: int = None) -> str:
        """调用LLM做决策"""
        temp = temperature if temperature is not None else config.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS

        result = llm_call(self.system_prompt, user_message,
                          temperature=temp, max_tokens=tokens,
                          agent_id=self.agent_id)

        self.llm_logs.append({
            "agent_id": self.agent_id,
            "system_prompt_len": len(self.system_prompt),
            "user_message_len": len(user_message),
            "result_len": len(result) if result else 0,
            "success": bool(result),
        })

        return result

    def ask_llm_json(self, user_message: str,
                     temperature: float = None,
                     max_tokens: int = None) -> dict:
        """调用LLM并解析JSON返回"""
        text = self.ask_llm(user_message, temperature, max_tokens)
        if text:
            parsed = parse_llm_json(text)
            if parsed:
                return parsed
            else:
                self._log(f"   ⚠️ LLM返回了文本但JSON解析失败，降级到规则引擎")
        return {}

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
