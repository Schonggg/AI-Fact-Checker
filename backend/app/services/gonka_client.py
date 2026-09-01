"""
Gonka Router Async Client
队员 1 - AI 后端工程师
任务 1：官方 Gonka Router 客户端封装
已对齐 Gonka 官方提供的模型列表
"""
import os
import asyncio
from typing import AsyncGenerator, Optional
from openai import AsyncOpenAI

GONKA_BASE_URL = os.getenv("GONKA_BASE_URL", "https://api.gonkarouter.io/v1")
GONKA_API_KEY = os.getenv("GONKA_API_KEY", "")

# Gonka Router 官方模型（你提供的3个）
MODELS = {
    "pro":   "deepseek-ai/DeepSeek-V4-Flash-0731",  # 正方 Agent
    "con":   "MiniMaxAI/MiniMax-M2.7",              # 反方 Agent
    "judge": "moonshotai/Kimi-K2.6",                # 裁判 Agent
}


class GonkaClient:
    """Gonka Router OpenAI-compatible async client."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GONKA_API_KEY
        if not self.api_key:
            raise ValueError("GONKA_API_KEY is not set. Add to .env")
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=GONKA_BASE_URL,
            timeout=120.0,
        )

    async def chat(self, model: str, messages: list, temperature: float = 0.2) -> tuple[str, str]:
        """Call Gonka Router, return (content, request_id)."""
        response = await self.client.chat.completions.create(
            model=model, messages=messages, temperature=temperature
        )
        content = response.choices[0].message.content or ""
        request_id = response.id  # 🌟 Gonka Request ID for on-chain proof
        return content, request_id

    async def close(self):
        await self.client.aclose()

    # ── Role-based shortcuts ────────────────────────

    async def call_pro_agent(self, system_prompt: str, user_prompt: str):
        return await self.chat(MODELS["pro"], [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], temperature=0.2)

    async def call_con_agent(self, system_prompt: str, user_prompt: str):
        return await self.chat(MODELS["con"], [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], temperature=0.2)

    async def call_judge_agent(self, system_prompt: str, user_prompt: str):
        return await self.chat(MODELS["judge"], [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], temperature=0.1)


_client: Optional[GonkaClient] = None


def get_gonka_client() -> GonkaClient:
    global _client
    if _client is None:
        _client = GonkaClient()
    return _client


async def close_gonka_client():
    global _client
    if _client:
        await _client.close()
        _client = None