# -*- coding: utf-8 -*-
"""
core/search_client.py - 豆包联网搜索客户端
"""

import time

import requests

import config


class SearchClient:
    """基于豆包 Responses API 的联网搜索客户端。"""

    def __init__(
        self,
        api_key: str = config.DOUBAO_API_KEY,
        base_url: str = config.DOUBAO_BASE_URL,
        model: str = config.DOUBAO_MODEL,
        recency: str = config.SEARCH_RECENCY,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.recency = recency

    def search(self, query: str, recency: str | None = None) -> dict:
        """
        执行一次联网搜索，并兼容旧的返回结构。
        """
        if not self.api_key:
            raise RuntimeError("DOUBAO_API_KEY 未配置，无法执行联网搜索")

        api_url = f"{self.base_url}/responses"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "tools": [{"type": "web_search"}],
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._build_search_prompt(query, recency or self.recency),
                        }
                    ],
                }
            ],
            "max_output_tokens": config.SEARCH_MAX_OUTPUT_TOKENS,
        }

        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        return self._normalize_response(resp.json())

    def batch_search(
        self,
        queries: list[str],
        delay: float = config.SEARCH_DELAY_SECONDS,
    ) -> list[dict]:
        """
        批量联网搜索，逐条调用并附带间隔，避免限流。
        每个结果项同时保留结构化 references 供引用溯源使用。
        """
        results = []
        total = len(queries)
        for i, q in enumerate(queries):
            print(f"  [SearchClient] 搜索 {i + 1}/{total}: {q[:50]}...")
            try:
                result = self.search(q)
                results.append({
                    "query": q,
                    "result": result,
                    "references": result.get("references", []) if result else [],
                })
            except Exception as e:
                print(f"  [SearchClient] 搜索失败: {q[:50]}... | 错误: {e}")
                results.append({"query": q, "result": None, "references": [], "error": str(e)})
            if i < total - 1:
                time.sleep(delay)
        return results

    @staticmethod
    def extract_text(search_result: dict) -> str:
        """从兼容结构中提取纯文本内容。"""
        if not search_result:
            return ""

        texts = []

        choices = search_result.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            content = message.get("content", "")
            if isinstance(content, str) and content:
                texts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text", "")
                        if text:
                            texts.append(text)
                    elif isinstance(item, str):
                        texts.append(item)

        for sr in search_result.get("references", []):
            title = sr.get("title", "")
            snippet = sr.get("content", "") or sr.get("summary", "") or sr.get("snippet", "")
            url = sr.get("url", "")
            parts = [part for part in (title, snippet, url) if part]
            if parts:
                texts.append(" | ".join(parts))

        return "\n".join(texts)

    @staticmethod
    def _build_search_prompt(query: str, recency: str) -> str:
        recency_hint = {
            "day": "优先最近1天内的信息",
            "week": "优先最近1周内的信息",
            "month": "优先最近1个月内的信息",
            "year": "优先最近1年内的信息",
        }.get((recency or "").lower(), "")

        if recency_hint:
            return f"{query}\n\n要求：请使用联网搜索，并{recency_hint}，给出简洁结果并保留可引用的信息来源。"
        return f"{query}\n\n要求：请使用联网搜索，给出简洁结果并保留可引用的信息来源。"

    @staticmethod
    def _normalize_response(response: dict) -> dict:
        answer_text = SearchClient._extract_output_text(response)
        references = SearchClient._extract_references(response)
        return {
            "choices": [
                {
                    "message": {
                        "content": answer_text,
                    }
                }
            ],
            "references": references,
            "raw_response": response,
        }

    @staticmethod
    def _extract_output_text(response: dict) -> str:
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        texts = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue

            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    texts.append(text)

        return "\n".join(texts).strip()

    @staticmethod
    def _extract_references(response: dict) -> list[dict]:
        refs = []
        seen = set()

        for item in response.get("output", []):
            for content in item.get("content", []):
                for annotation in content.get("annotations", []):
                    title = annotation.get("title", "")
                    url = annotation.get("url", "")
                    if not title and not url:
                        continue

                    key = (title, url)
                    if key in seen:
                        continue
                    seen.add(key)

                    refs.append(
                        {
                            "title": title,
                            "content": annotation.get("text", "") or annotation.get("summary", ""),
                            "summary": annotation.get("summary", ""),
                            "url": url,
                            "site_name": annotation.get("site_name", ""),
                        }
                    )

        return refs
