"""
FastAPI Routes - Core API Endpoints
队员 1 - AI 后端工程师
任务 5：FastAPI 核心路由
"""
import logging
from fastapi import APIRouter, HTTPException
from contextlib import asynccontextmanager

from ..schemas.verify_schema import VerifyRequest, VerifyResponse, MOCK_VERIFY_RESPONSE
from ..services.consensus_agent import ConsensusAgent

logger = logging.getLogger(__name__)
router = APIRouter()

# ── 单例 ─────────────────────────────────────────
_consensus_agent: ConsensusAgent | None = None


def get_consensus_agent() -> ConsensusAgent:
    global _consensus_agent
    if _consensus_agent is None:
        _consensus_agent = ConsensusAgent()
    return _consensus_agent


# ── Routes ───────────────────────────────────────

@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "AI Fact Checker Backend",
        "version": "1.0.0",
        "gonka_router": "https://gonkarouter.io/v1",
    }


@router.post("/api/verify", response_model=VerifyResponse)
async def verify_claim(request: VerifyRequest) -> VerifyResponse:
    """
    🌟 核心 API 端点：事实核查

    数据流：
    1. 收到 text
    2. 搜索相关事实（SearchEngine）
    3. 并发调用 Pro Agent + Con Agent（asyncio.gather）
    4. 裁判 Agent 给出最终裁定
    5. 返回标准 VerifyResponse（前端可直接转发给合约）

    预期延迟：10-15 秒（并发优化后）
    """
    try:
        logger.info(f"Received verify request: {request.text[:80]}...")

        # 运行多模型共识引擎
        agent = get_consensus_agent()
        result = await agent.run(request.text)

        return VerifyResponse(
            claim=result.claim,
            claim_hash=result.claim_hash,
            truth_score=result.truth_score,
            verdict=result.verdict,
            confidence=result.confidence,
            consensus_status=result.consensus_status,
            reasoning_trace={
                "pro_argument": result.reasoning_trace["pro_argument"],
                "con_argument": result.reasoning_trace["con_argument"],
                "judge_verdict": result.reasoning_trace["judge_verdict"],
            },
            sources=[{"title": s.get("title", ""), "url": s.get("url", "")} for s in result.sources],
            gonka_request_ids=result.gonka_request_ids,
            metadata_uri=result.metadata_uri or "",
        )

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Backend config error: {str(e)}. "
                   "Make sure GONKA_API_KEY is set in .env"
        )
    except Exception as e:
        logger.exception(f"Verification failed: {e}")
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")


@router.get("/api/mock/verify", response_model=VerifyResponse)
async def mock_verify() -> VerifyResponse:
    """Mock endpoint - 无需 Gonka API Key 即可测试前端."""
    return MOCK_VERIFY_RESPONSE


@router.get("/api/models")
async def list_models() -> dict:
    """列出当前使用的 Gonka 模型（透明度展示）."""
    return {
        "models": {
            "pro":   "meta-llama/llama-3.3-70b-instruct",
            "con":   "deepseek/deepseek-chat",
            "judge": "deepseek/deepseek-r1",
        },
        "base_url": "https://gonkarouter.io/v1",
        "note": "Pro + Con agents run in parallel (asyncio.gather)"
    }