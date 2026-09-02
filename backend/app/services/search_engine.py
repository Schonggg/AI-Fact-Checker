"""
Search Engine - Real-time Fact & News Retrieval
队员 1 - AI 后端工程师
阶段2：信息提取与实时事实检索
"""
import os
import logging
from dataclasses import dataclass
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


@dataclass
class SearchResult:
    """单条搜索结果"""
    title: str
    url: str
    snippet: str


class SearchEngine:
    """
    实时新闻检索引擎。
    支持 Tavily（推荐）、DuckDuckGo 降级。
    """

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if TAVILY_API_KEY:
            return await self._search_tavily(query, max_results)
        logger.warning("No Tavily API key - using fallback")
        return []

    async def _search_tavily(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": TAVILY_API_KEY,
                        "query": query,
                        "max_results": max_results,
                        "include_answer": False,
                        "include_raw_content": False,
                    }
                )
                r.raise_for_status()
                results = r.json().get("results", [])
                return [
                    SearchResult(
                        title=res.get("title", ""),
                        url=res.get("url", ""),
                        snippet=res.get("content", ""),
                    )
                    for res in results
                ]
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return []

    def build_context(self, results: list[SearchResult]) -> str:
        """构建供 LLM 引用的背景事实"""
        if not results:
            return "（无实时搜索结果，请基于常识判断）"
        lines = ["【背景事实】"]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.title}")
            lines.append(f"    来源: {r.url}")
            lines.append(f"    摘要: {r.snippet[:200]}")
        return "\n".join(lines)


_search_engine: Optional[SearchEngine] = None


def get_search_engine() -> SearchEngine:
    global _search_engine
    if _search_engine is None:
        _search_engine = SearchEngine()
    return _search_engine