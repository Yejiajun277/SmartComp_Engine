# -*- coding: utf-8 -*-
"""
core/search_client.py - Tavily 联网搜索客户端
"""

import time
import asyncio

import config


class SearchClient:
    """基于 Tavily Search API 的联网搜索客户端。"""

    def __init__(
        self,
        api_key: str = config.TAVILY_API_KEY,
        recency: str = config.SEARCH_RECENCY,
    ):
        self.api_key = api_key
        self.recency = recency
        self.search_logs: list[dict] = []

    def search(self, query: str, recency: str | None = None) -> dict:
        """
        执行一次联网搜索，并兼容旧的返回结构。
        """
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY 未配置，无法执行联网搜索")

        from tavily import TavilyClient
        from datetime import datetime

        client = TavilyClient(api_key=self.api_key)

        # 将 recency 映射为 Tavily 的 days 参数
        days = self._recency_to_days(recency or self.recency)

        t0 = time.time()
        try:
            response = client.search(
                query=query,
                max_results=5,
                search_depth="advanced",
                days=days,
            )
            duration_ms = (time.time() - t0) * 1000
            result = self._normalize_response(response)
            refs = result.get("references", [])
            result_text = SearchClient.extract_text(result)
            self.search_logs.append({
                "type": "search",
                "agent_id": "",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "query": query,
                "duration_ms": round(duration_ms, 1),
                "success": True,
                "result_count": len(refs),
                "result_text_len": len(result_text),
                "error": "",
            })
            return result
        except Exception as e:
            duration_ms = (time.time() - t0) * 1000
            self.search_logs.append({
                "type": "search",
                "agent_id": "",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "query": query,
                "duration_ms": round(duration_ms, 1),
                "success": False,
                "result_count": 0,
                "result_text_len": 0,
                "error": str(e)[:200],
            })
            raise

    def batch_search(
        self,
        queries: list[str],
        delay: float = config.SEARCH_DELAY_SECONDS,
    ) -> list[dict]:
        """
        批量联网搜索，逐条调用并附带间隔，避免限流。
        每个结果项同时保留结构化 references 供引用溯源使用。
        """
        if not config.ENABLE_LLM:
            return [
                {
                    "query": q,
                    "result": None,
                    "references": [],
                    "error": "规则引擎模式跳过联网搜索",
                }
                for q in queries
            ]

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

    async def async_search(self, query: str, recency: str | None = None) -> dict:
        """
        异步执行一次联网搜索（在线程池中运行同步 Tavily 客户端）。
        """
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY 未配置，无法执行联网搜索")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.search(query, recency))

    async def async_batch_search(
        self,
        queries: list[str],
        delay: float = config.SEARCH_DELAY_SECONDS,
    ) -> list[dict]:
        """
        异步批量联网搜索，逐条调用并附带非阻塞间隔，避免限流。
        """
        if not config.ENABLE_LLM:
            return [
                {
                    "query": q,
                    "result": None,
                    "references": [],
                    "error": "规则引擎模式跳过联网搜索",
                }
                for q in queries
            ]

        results = []
        total = len(queries)
        for i, q in enumerate(queries):
            print(f"  [SearchClient] 异步搜索 {i + 1}/{total}: {q[:50]}...")
            try:
                result = await self.async_search(q)
                results.append({
                    "query": q,
                    "result": result,
                    "references": result.get("references", []) if result else [],
                })
            except Exception as e:
                print(f"  [SearchClient] 搜索失败: {q[:50]}... | 错误: {e}")
                results.append({"query": q, "result": None, "references": [], "error": str(e)})
            if i < total - 1:
                await asyncio.sleep(delay)
        return results

    @staticmethod
    def _recency_to_days(recency: str) -> int | None:
        """将 recency 字符串转换为 Tavily search 的 days 参数。"""
        mapping = {
            "day": 1,
            "week": 7,
            "month": 30,
            "year": 365,
        }
        return mapping.get((recency or "").lower())

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
    def _normalize_response(response: dict) -> dict:
        """将 Tavily 响应转换为兼容的统一格式。"""
        # Tavily 返回 {"results": [...], "answer": "...", ...}
        answer = response.get("answer", "")
        results = response.get("results", [])

        references = []
        for r in results:
            references.append({
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "summary": r.get("content", "")[:200] if r.get("content") else "",
                "url": r.get("url", ""),
                "site_name": "",
            })

        return {
            "choices": [
                {
                    "message": {
                        "content": answer,
                    }
                }
            ],
            "references": references,
            "raw_response": response,
        }
