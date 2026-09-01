"""
Search Engine - Real-time Fact & News Retrieval
队员 1 - AI 后端工程师
任务 2：实时事实与新闻检索器
"""
import os
import logging
from typing import Optional
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

# ── Search API 配置 ────────────────────────────────
# 推荐使用 Tavily (https://tavily.com) - 免费额度充足
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
# 备选：Serper (https://serper.dev)
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")


@dataclass
class SearchResult:
    """单条搜索结果"""
    title: str
    url: str
    snippet: str
    source: str


class SearchEngine:
    """
    实时新闻检索引擎。
    优先使用 Tavily API（推荐），支持 DuckDuckGo 备选。
    大模型无法知道最新新闻，此模块提供实时事实检索作为输入。
    """

    def __init__(self, tavily_key: Optional[str] = None):
        self.tavily_key = tavily_key or TAVILY_API_KEY
        self.serper_key = SERPER_API_KEY

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """
        搜索新闻事实。优先用 Tavily，失败则降级到 Serper / DuckDuckGo。
        Args:
            query: 搜索关键词（通常是 claim 的简化表述）
            max_results: 返回结果数量（默认 5 条）
        Returns:
            list[SearchResult]: 搜索结果列表
        """
        if self.tavily_key:
            return await self._search_tavily(query, max_results)
        elif self.serper_key:
            return await self._search_serper(query, max_results)
        else:
            logger.warning("No search API key found. Using DuckDuckGo fallback.")
            return await self._search_duckduckgo(query, max_results)

    async def _search_tavily(self, query: str, max_results: int) -> list[SearchResult]:
        """Tavily API search (recommended)"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                }
            )
            response.raise_for_status()
            data = response.json()

            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    source=r.get("source", "tavily"),
                )
                for r in data.get("results", [])
            ]

    async def _search_serper(self, query: str, max_results: int) -> list[SearchResult]:
        """Serper API search (alternative)"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.serper_key},
                json={"q": query, "num": max_results}
            )
            response.raise_for_status()
            data = response.json()

            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    snippet=r.get("snippet", ""),
                    source="serper",
                )
                for r in data.get("organic", [])
            ]

    async def _search_duckduckgo(self, query: str, max_results: int) -> list[SearchResult]:
        """
        DuckDuckGo HTML search (last resort, no API key needed).
        Note: Not ideal for production - use Tavily/Serper for reliability.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # DDG HTML endpoint (unofficial)
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query}
                )
                response.raise_for_status()

                # Simple HTML parsing would go here
                # For demo purposes, return empty results with warning
                logger.warning(
                    "DuckDuckGo fallback used - results may be limited. "
                    "Consider using Tavily (free tier) for better results."
                )
                return []
        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")
            return []

    def build_context(self, results: list[SearchResult]) -> str:
        """
        将搜索结果构建为 LLM 可读的 context 字符串。
        这个 context 将作为 Gonka 模型的事实输入。
        """
        if not results:
            return "（未找到相关实时新闻，请基于常识判断）"

        lines = ["【相关事实检索结果】"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n[{i}] {r.title}")
            lines.append(f"来源: {r.url}")
            lines.append(f"摘要: {r.snippet}")
        return "\n".join(lines)


# ── 全局单例 ──────────────────────────────────────
_search_engine: Optional[SearchEngine] = None


def get_search_engine() -> SearchEngine:
    global _search_engine
    if _search_engine is None:
        _search_engine = SearchEngine()
    return _search_engine