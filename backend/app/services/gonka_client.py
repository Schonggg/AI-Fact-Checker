"""
Gonka Router Async Client
队员 1 - AI 后端工程师
任务 1：官方 Gonka Router 客户端封装
"""

import os
import asyncio
from typing import AsyncGenerator, Optional
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

# ── Gonka Router 官方网关配置 ────────────────────────
GONKA_BASE_URL = "https://gonkarouter.io/v1"
GONKA_API_KEY = os.getenv("GONKA_API_KEY", "")

# ── 可用模型列表（可按需扩展） ────────────────────────
MODELS = {
    "pro":   "meta-llama/llama-3.3-70b-instruct",   # 正方 Agent
    "con":   "deepseek/deepseek-chat",              # 反方 Agent
    "judge": "deepseek/deepseek-r1",                # 裁判 Agent
    # 可按需添加更多模型进行交叉验证
}


class GonkaClient:
    """
    Async wrapper around Gonka Router (OpenAI-compatible API).
    Handles auth, rate limiting, and Request ID extraction.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GONKA_API_KEY
        if not self.api_key:
            raise ValueError(
                "GONKA_API_KEY is not set. "
                "Add it to your .env file: GONKA_API_KEY=your_key_here"
            )

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=GONKA_BASE_URL,
            timeout=60.0,  # 60s timeout
        )

    async def chat(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float = 0.2,
        **kwargs
    ) -> tuple[str, str]:
        """
        Send a chat request to Gonka Router.

        Returns:
            tuple[str, str]: (content, request_id)
            - content: The model's response text
            - request_id: Gonka Router's official request ID (used for on-chain proof)

        Raises:
            openai.APIError on failure
        """
        response: ChatCompletion = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs
        )

        content = response.choices[0].message.content or ""
        request_id: str = response.id  # 🌟 核心：提取 Gonka Request ID

        return content, request_id

    async def chat_stream(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float = 0.2,
        **kwargs
    ) -> AsyncGenerator[tuple[str, str], None]:
        """
        Stream responses from Gonka Router.
        Yields: (chunk_text, request_id) - request_id only on first chunk
        """
        first_chunk = True
        request_id = ""

        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
            **kwargs
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                if first_chunk:
                    request_id = chunk.id  # 🌟 第一条 chunk 才有 id
                    first_chunk = False
                yield delta, request_id

    # ── 快捷调用方法 ────────────────────────────────

    async def call_pro_agent(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, str]:
        """Call the Pro Agent (supporting evidence)."""
        return await self.chat(
            model=MODELS["pro"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

    async def call_con_agent(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, str]:
        """Call the Con Agent (critical evidence)."""
        return await self.chat(
            model=MODELS["con"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

    async def call_judge_agent(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, str]:
        """Call the Judge Agent (final verdict)."""
        return await self.chat(
            model=MODELS["judge"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # Lower temp for judge
        )

    async def close(self):
        """Close the async client."""
        await self.client.close()


# ── 全局单例（懒加载） ────────────────────────────────
_client: Optional[GonkaClient] = None


def get_gonka_client() -> GonkaClient:
    """Get or create the global Gonka client instance."""
    global _client
    if _client is None:
        _client = GonkaClient()
    return _client


async def close_gonka_client():
    """Close the global client (call on app shutdown)."""
    global _client
    if _client:
        await _client.close()
        _client = None