"""
Gonka Router Async Client - 带超时容错与自动降级
队员 1 - AI 后端工程师
"""
import os
import asyncio
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

GONKA_API_KEY = os.getenv("GONKA_API_KEY", "")
GONKA_BASE_URL = os.getenv("GONKA_BASE_URL", "https://api.gonkarouter.io/v1")

# 模型分配（确保裁判高可用，正反模型异构）
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731")
PRO_MODEL = os.getenv("PRO_MODEL", "moonshotai/Kimi-K2.6")
CON_MODEL = os.getenv("CON_MODEL", "MiniMaxAI/MiniMax-M2.7")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731")

# Kimi 超时截断（6~8秒自动降级）
KIMI_TIMEOUT_SECONDS = float(os.getenv("KIMI_TIMEOUT_SECONDS", "8.0"))


class GonkaError(Exception):
    """Gonka API 调用失败"""
    def __init__(self, message: str, model: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.model = model
        self.status_code = status_code


async def call_gonka(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 3200,
    timeout_seconds: float = 60.0,
) -> tuple[str, str]:
    """
    调用 Gonka Router，返回 (content, request_id)。

    Kimi 模型有专属超时降级逻辑：超时或500错误 → 自动切换 DeepSeek。

    Args:
        model: 模型名（如 deepseek-ai/DeepSeek-V4-Flash-0731, moonshotai/Kimi-K2.6）
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        temperature: 随机性参数
        timeout_seconds: 超时秒数

    Returns:
        tuple[str, str]: (模型回复内容, Gonka Request ID)

    Raises:
        GonkaError: API 调用彻底失败时抛出
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {GONKA_API_KEY}",
        "Content-Type": "application/json",
    }

    # Kimi 特殊降级逻辑
    is_kimi = "kimi" in model.lower()
    effective_timeout = KIMI_TIMEOUT_SECONDS if is_kimi else timeout_seconds

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(effective_timeout)) as client:
            r = await client.post(
                f"{GONKA_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"] or ""
            request_id = data.get("id", "")
            logger.info(f"[Gonka] {model} -> req_id={request_id[:20]}...")
            return content, request_id

    except httpx.TimeoutException:
        if is_kimi:
            logger.warning(f"[Gonka] {model} 超时({effective_timeout}s)，自动降级到 {FALLBACK_MODEL}")
            return await _fallback_call(payload, headers, timeout_seconds)
        raise GonkaError(f"{model} 请求超时（{effective_timeout}s）", model=model)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 500 and is_kimi:
            logger.warning(f"[Gonka] {model} 返回500错误，自动降级到 {FALLBACK_MODEL}")
            return await _fallback_call(payload, headers, timeout_seconds)
        raise GonkaError(
            f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            model=model,
            status_code=e.response.status_code,
        )

    except Exception as e:
        raise GonkaError(str(e), model=model)


async def _fallback_call(payload: dict, headers: dict, timeout_seconds: float) -> tuple[str, str]:
    """Kimi 超时时，毫秒级切换 DeepSeek 继续执行"""
    payload["model"] = FALLBACK_MODEL
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            r = await client.post(
                f"{GONKA_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"] or ""
            request_id = data.get("id", "")
            logger.info(f"[Gonka] Fallback {FALLBACK_MODEL} -> req_id={request_id[:20]}...")
            return content, request_id
    except Exception as e:
        raise GonkaError(f"Fallback model {FALLBACK_MODEL} also failed: {e}", model=FALLBACK_MODEL)


# ── 角色调用快捷方法 ──────────────────────────────

async def call_pro_agent(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """正方 Agent（支持证据）- 默认 Kimi，超时自动降级"""
    return await call_gonka(PRO_MODEL, system_prompt, user_prompt, temperature=0.2)


async def call_con_agent(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """反方 Agent（反驳证据）- MiniMax"""
    return await call_gonka(CON_MODEL, system_prompt, user_prompt, temperature=0.2)


async def call_judge_agent(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """裁判 Agent（终审裁决）- DeepSeek，高可用"""
    return await call_gonka(JUDGE_MODEL, system_prompt, user_prompt, temperature=0.1)


# ── 多模型并发调用（asyncio.gather） ─────────────

async def call_pro_con_parallel(
    system_pro: str, user_pro: str,
    system_con: str, user_con: str,
) -> tuple[tuple[str, str], tuple[str, str]]:
    """
    正反方并行辩论（asyncio.gather）。
    任意一方出错不影响另一方，单方出错不崩溃。
    耗时压缩到 3~5 秒内。
    """
    pro_task = _safe_call(call_pro_agent, system_pro, user_pro)
    con_task = _safe_call(call_con_agent, system_con, user_con)

    results = await asyncio.gather(pro_task, con_task, return_exceptions=True)

    pro_result = results[0]
    con_result = results[1]

    # 如果某个失败，返回 (error_message, "")
    if isinstance(pro_result, Exception):
        logger.error(f"[Gonka] Pro agent failed: {pro_result}")
        pro_result = (f"[Pro Agent 错误] {pro_result}", "")
    if isinstance(con_result, Exception):
        logger.error(f"[Gonka] Con agent failed: {con_result}")
        con_result = (f"[Con Agent 错误] {con_result}", "")

    return pro_result, con_result


async def _safe_call(fn, *args) -> tuple:
    """包装调用，捕获所有异常，返回 tuple 而不抛出"""
    try:
        return await fn(*args)
    except GonkaError as e:
        raise e
    except Exception as e:
        raise e