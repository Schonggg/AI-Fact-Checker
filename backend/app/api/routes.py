"""
FastAPI Routes - 5维雷达图 API 端点
队员 1 - AI 后端工程师
阶段5：API路由定义
"""
import logging
from fastapi import APIRouter, HTTPException
from ..schemas.verify_schema import VerifyRequest, VerifyResponse, MOCK_RESPONSE
from ..services.consensus_agent import get_consensus_agent

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "service": "AI Fact Checker",
        "version": "2.0.0",
        "base_url": "https://api.gonkarouter.io/v1",
    }


@router.get("/api/models")
async def list_models():
    """当前使用的3个Gonka模型（透明度展示）"""
    from ..services.gonka_client import PRO_MODEL, CON_MODEL, JUDGE_MODEL
    return {
        "models": {"pro": PRO_MODEL, "con": CON_MODEL, "judge": JUDGE_MODEL},
        "base_url": "https://api.gonkarouter.io/v1",
    }


@router.post("/api/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest):
    """
    🌟 核心 API：事实核查 + 5维雷达图数据

    返回字段：
    - metrics: {factual, sources, logic, bias, consensus}  → 前端雷达图
    - eas_metadata: {schema, network, timestamp, ipfs_cid, claim_hash} → 合约存证
    - gonka_request_ids: [pro_req_id, con_req_id, judge_req_id] → 链上存证
    - claim_hash: Keccak256(claim_text) → 合约参数
    """
    try:
        claim_text = request.claim.strip()
        logger.info(f"[/api/verify] claim: {claim_text[:60]}...")

        agent = get_consensus_agent()
        result = await agent.run(claim_text)

        return VerifyResponse(
            claim=result.claim,
            claim_hash=result.claim_hash,
            truth_score=result.truth_score,
            verdict=result.verdict,
            confidence=result.confidence,
            metrics=result.metrics,
            eas_metadata=result.eas_metadata,
            reasoning_trace=result.reasoning_trace,
            sources=result.sources,
            gonka_request_ids=result.gonka_request_ids,
        )

    except Exception as e:
        logger.exception(f"[/api/verify] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/mock/verify", response_model=VerifyResponse)
async def mock_verify():
    """
    Mock 端点 - 无需 API key，为前端离线开发和录制路演视频使用。
    返回预设的标准响应（5维 + 合约存证格式）。
    """
    return MOCK_RESPONSE