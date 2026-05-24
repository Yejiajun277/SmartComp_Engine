# -*- coding: utf-8 -*-
"""
core/prompt_loader.py — 提示词模板加载器

从 prompts/ 目录加载 .md 文件，解析为结构化模板。

文件格式约定：
  每个 .md 文件用 ## section_name 作为节标题，
  节之间的内容即为该节的模板文本。

  必须包含 system_prompt 节（系统提示词），
  其余节为用户提示词模板，名称自定义。
"""

import os
import re


# prompts 目录路径
_PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts"
)

# 缓存
_cache: dict[str, dict[str, str]] = {}


def load(agent_name: str) -> dict[str, str]:
    """加载指定Agent的提示词模板"""
    if agent_name in _cache:
        return _cache[agent_name]

    file_path = os.path.join(_PROMPTS_DIR, f"{agent_name}.md")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"提示词文件不存在: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    result = _parse_sections(content)

    if "system_prompt" not in result:
        raise ValueError(f"提示词文件 {file_path} 缺少 ## system_prompt 节")

    _cache[agent_name] = result
    return result


def _parse_sections(content: str) -> dict[str, str]:
    """解析 markdown 文件中的 ## section 节"""
    sections: dict[str, str] = {}
    pattern = re.compile(r'^##\s+(\S+)\s*$', re.MULTILINE)
    matches = list(pattern.finditer(content))

    for i, match in enumerate(matches):
        section_name = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_text = content[start:end].strip()
        sections[section_name] = section_text

    return sections


def clear_cache():
    """清除缓存"""
    _cache.clear()
