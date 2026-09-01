"""
Pydantic Schemas - Request/Response Data Models
队员 1 - AI 后端工程师
任务 4：请求与返回的 Pydantic 数据结构定义
"""

from pydantic import BaseModel, Field
from typing import Optional


# ── Request Models ────────────────────────────────

class VerifyRequest(BaseModel):
    """
    POST /api/verify 的请求体。
    用户输入一条新闻/推文/URL，等待 AI 核查结果。
    """
    text: str = Field(
        ...,
        description="待核查的新闻、推文或文本内容",
        min_length=5,
        max_length=5000,
        examples=["特朗普宣布免除所有联邦学生贷款"]
    )
    # 可选：提供 claim_hash（如果前端已计算）
    claim_hash: Optional[str] = Field(
        default=None,
        description="可选：前端预计算的 claim_hash（keccak256 hex）"
    )


class HealthCheckRequest(BaseModel):
    """GET /health 的响应（无请求体，但定义以保持一致性）"""
    status: str = "ok"


# ── Response Models ────────────────────────────────

class ReasoningTrace(BaseModel):
    """
    推理过程追踪。
    展示多模型辩论过程，透明度 UI 核心部分。
    """
    pro_argument: str = Field(
        description="正方 Agent（Pro Agent）的论点与支持证据"
    )
    con_argument: str = Field(
        description="反方 Agent（Con Agent）的论点与反驳证据"
    )
    judge_verdict: str = Field(
        description="裁判 Agent（Judge Agent）的最终裁决与理由"
    )


class SourceItem(BaseModel):
    """单条参考来源"""
    title: str = Field(description="文章/网页标题")
    url: str = Field(description="来源 URL")


class VerifyResponse(BaseModel):
    """
    POST /api/verify 的标准响应体。
    🌟 必须与前端 / 智能合约完全对齐。
    """
    claim: str = Field(
        description="用户提交的原始声明"
    )
    claim_hash: str = Field(
        description="Keccak256(claim_text) 的 0x 开头 64 位十六进制字符串（供合约使用）",
        examples=["0x7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"]
    )
    truth_score: int = Field(
        description="真实性评分 0-100（0=假新闻，100=真新闻）",
        ge=0, le=100
    )
    verdict: str = Field(
        description="最终裁定：TRUE | FALSE | DISPUTED",
        pattern="^(TRUE|FALSE|DISPUTED)$"
    )
    confidence: float = Field(
        description="置信度 0.0-1.0",
        ge=0.0, le=1.0
    )
    consensus_status: str = Field(
        description="共识状态：CONSENSUS_REACHED | DISPUTED",
        pattern="^(CONSENSUS_REACHED|DISPUTED)$"
    )
    reasoning_trace: ReasoningTrace = Field(
        description="多模型辩论推理过程（透明度展示用）"
    )
    sources: list[SourceItem] = Field(
        description="实时检索到的参考来源列表",
        default_factory=list
    )
    gonka_request_ids: list[str] = Field(
        description="🌟 每次 Gonka 调用的 Request ID 数组（3个：pro/con/judge）",
        min_length=2  # 至少 2 个模型参与
    )
    metadata_uri: str = Field(
        description="完整核查报告的 IPFS/后端链接（可为空）",
        default=""
    )

    class Config:
        json_schema_extra = {
            "example": {
                "claim": "特朗普宣布免除所有联邦学生贷款",
                "claim_hash": "0x7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
                "truth_score": 12,
                "verdict": "FALSE",
                "confidence": 0.95,
                "consensus_status": "CONSENSUS_REACHED",
                "reasoning_trace": {
                    "pro_argument": "社交媒体上有相关视频和推文传播...",
                    "con_argument": "白宫官方与教育部未发布任何行政令，主流媒体无报道...",
                    "judge_verdict": "【真实性评分】: 12/100\n【最终裁定】: FALSE\n【裁决理由】: 缺乏官方文件支持，且被主流事实核查机构证伪，判定为假新闻。"
                },
                "sources": [
                    {"title": "White House Official Statements", "url": "https://www.whitehouse.gov/"}
                ],
                "gonka_request_ids": [
                    "req_pro_agent_89f72b1a",
                    "req_con_agent_12a34c5d",
                    "req_judge_agent_99e81d0f"
                ],
                "metadata_uri": ""
            }
        }


# ── Mock Data（供前端调试用） ───────────────────────

MOCK_VERIFY_RESPONSE = VerifyResponse(
    claim="特朗普宣布免除所有联邦学生贷款",
    claim_hash="0x7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
    truth_score=12,
    verdict="FALSE",
    confidence=0.95,
    consensus_status="CONSENSUS_REACHED",
    reasoning_trace=ReasoningTrace(
        pro_argument="社交媒体上有相关视频和推文传播，部分账号声称看到了相关公告。",
        con_argument="白宫官方与教育部未发布任何行政令，主流媒体（AP, Reuters, FactCheck.org）均无此报道。2024年 student loan relief 政策早在 2024年已被最高法院否决。",
        judge_verdict="【真实性评分】: 12/100\n【最终裁定】: FALSE\n【裁决理由】: 缺乏官方文件支持，且被主流事实核查机构证伪，判定为假新闻。"
    ),
    sources=[
        SourceItem(
            title="White House - No Student Loan Announcement",
            url="https://www.whitehouse.gov/briefing-room/"
        ),
        SourceItem(
            title="AP News - Fact Check",
            url="https://apnews.com/article/fact-check-archive"
        )
    ],
    gonka_request_ids=[
        "req_pro_agent_89f72b1a",
        "req_con_agent_12a34c5d",
        "req_judge_agent_99e81d0f"
    ],
    metadata_uri=""
)