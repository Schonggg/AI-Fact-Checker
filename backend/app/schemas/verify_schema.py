"""
Pydantic Schemas - 5维雷达图新版验证格式
队员 1 - AI 后端工程师
阶段4：数据对齐与Schema规范
"""
from pydantic import BaseModel, Field
from typing import Optional


class VerifyRequest(BaseModel):
    """POST /api/verify 请求体"""
    claim: str = Field(..., min_length=5, max_length=12000)
    settings: Optional[dict] = Field(default=None)


class RadarMetrics(BaseModel):
    """前端5维雷达图数据"""
    factual: int = Field(ge=0, le=100, description="事实准确度")
    sources: int = Field(ge=0, le=100, description="信源权威度")
    logic: int = Field(ge=0, le=100, description="逻辑自洽性")
    bias: int = Field(ge=0, le=100, description="偏见/煽动指数（越低越中立）")
    consensus: int = Field(ge=0, le=100, description="模型间共识度")


class EASMetadata(BaseModel):
    """合约存证所需元数据"""
    eas_schema: str = Field(default="#gonka-fact-v1", description="EAS Schema ID")
    network: str = Field(default="Arbitrum Sepolia")
    timestamp: str
    ipfs_cid: str
    claim_hash: str


class ReasoningTrace(BaseModel):
    pro_argument: str = Field(description="正方Agent论点")
    con_argument: str = Field(description="反方Agent论点")
    judge_verdict: str = Field(description="裁判Agent最终裁决")


class SourceItem(BaseModel):
    title: str
    url: str


class VerifyResponse(BaseModel):
    """
    POST /api/verify 标准响应（匹配前端5维雷达图 + 合约存证）
    """
    claim: str = Field(description="原始声明")
    claim_hash: str = Field(description="Keccak256(claim) - 0x开头的64位十六进制")
    truth_score: int = Field(ge=0, le=100, description="综合真实度 0-100")
    verdict: str = Field(description="TRUE / FALSE / DISPUTED")
    confidence: float = Field(ge=0.0, le=1.0, description="判定置信度 0.0-1.0")
    metrics: RadarMetrics = Field(description="前端5维雷达图数据")
    eas_metadata: EASMetadata = Field(description="合约存证元数据")
    reasoning_trace: ReasoningTrace
    sources: list[SourceItem] = Field(default_factory=list)
    gonka_request_ids: list[str] = Field(
        description="🌟 每次Gonka调用的Request ID（pro/con/judge各一个）"
    )


# ── Mock 数据（供前端离线开发 / 录制路演） ──────────────────────

MOCK_RESPONSE = VerifyResponse(
    claim="特朗普宣布免除所有联邦学生贷款",
    claim_hash="0x7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
    truth_score=12,
    verdict="FALSE",
    confidence=0.95,
    metrics=RadarMetrics(
        factual=15,
        sources=35,
        logic=42,
        bias=88,
        consensus=75,
    ),
    eas_metadata=EASMetadata(
        schema="#gonka-fact-v1",
        network="Arbitrum Sepolia",
        timestamp="2026-09-02T04:00:00Z",
        ipfs_cid="QmYk7E9fZ2eAbcDeF1234567890abcdef1234567890",
        claim_hash="0x7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
    ),
    reasoning_trace=ReasoningTrace(
        pro_argument="社交媒体上有相关视频和推文传播，部分账号声称看到了相关公告。",
        con_argument="白宫官方与教育部未发布任何行政令，主流媒体无报道，2024年 student loan relief 已被最高法院否决。",
        judge_verdict="【裁决理由】: 缺乏官方文件支持，主流事实核查机构均证伪，判定为假新闻。",
    ),
    sources=[SourceItem(title="White House Official", url="https://www.whitehouse.gov/")],
    gonka_request_ids=["req_pro_demo_001", "req_con_demo_002", "req_judge_demo_003"],
)