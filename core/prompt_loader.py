# -*- coding: utf-8 -*-
"""
core/prompt_loader.py - 提示词模板加载器

从 prompts/ 目录加载 .md 文件，并解析为结构化模板。
"""

from __future__ import annotations

import os
import re


_PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts",
)

_cache: dict[str, dict[str, str]] = {}

_GLOBAL_GUARDRAIL = """
### 事实约束
1. 不得编造任何价格、销量、性能参数、市场份额、转化率等具体数值。
2. 没有证据支撑的信息必须明确写“暂无数据”或“待验证”，不得自行补全。
3. 禁止使用“首个”“唯一”“第一”“全面领先”“全系标配”等排他性表达，除非输入里有明确来源支撑。
4. 具体结论必须优先复用输入里的原始证据，不要把推测写成事实。
""".strip()


def load(agent_name: str) -> dict[str, str]:
    """加载指定 Agent 的提示词模板。"""
    if agent_name in _cache:
        return _cache[agent_name]

    file_path = os.path.join(_PROMPTS_DIR, f"{agent_name}.md")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"提示词文件不存在: {file_path}")

    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()

    result = _parse_sections(content)
    if "system_prompt" not in result:
        raise ValueError(f"提示词文件 {file_path} 缺少 ## system_prompt 节")

    result["system_prompt"] = _inject_guardrail(result["system_prompt"])
    _cache[agent_name] = result
    return result


def _parse_sections(content: str) -> dict[str, str]:
    """解析 markdown 文件中的 ## section 节。"""
    sections: dict[str, str] = {}
    pattern = re.compile(r"^##\s+(\S+)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(content))

    for index, match in enumerate(matches):
        section_name = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections[section_name] = content[start:end].strip()

    return sections


def clear_cache() -> None:
    """清除提示词缓存。"""
    _cache.clear()


def _inject_guardrail(system_prompt: str) -> str:
    prompt = (system_prompt or "").strip()
    if _GLOBAL_GUARDRAIL in prompt:
        return prompt
    if not prompt:
        return _GLOBAL_GUARDRAIL
    return f"{prompt}\n\n{_GLOBAL_GUARDRAIL}"
