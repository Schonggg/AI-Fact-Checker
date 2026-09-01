"""
AI Fact Checker - FastAPI Backend
队员 1 - Jin Yi
Version 2.0 - Fixed and tested
"""
import os
import asyncio
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
from web3 import Web3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================
GONKA_API_KEY = os.getenv("GONKA_API_KEY", "sk-QFLHfPqrnbx378PLQk5745l5XO61sGh3Fl2Gv7jaHNfCEOh7")
GONKA_BASE_URL = "https://api.gonkarouter.io/v1"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "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")

# Models - Only use models provided by Gonka Router
PRO_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
CON_MODEL = "MiniMaxAI/MiniMax-M2.7"
JUDGE_MODEL = "moonshotai/Kimi-K2.6"

# ============================================================
# REQUEST/RESPONSE SCHEMAS
# ============================================================
class VerifyRequest(BaseModel):
    text: str = Field(..., min_length=5, max_length=5000)

class ReasoningTrace(BaseModel):
    pro_argument: str
    con_argument: str
    judge_verdict: str

class SourceItem(BaseModel):
    title: str
    url: str

class VerifyResponse(BaseModel):
    claim: str
    claim_hash: str
    truth_score: int = Field(ge=0, le=100)
    verdict: str  # TRUE / FALSE / DISPUTED
    confidence: float
    consensus_status: str
    reasoning_trace: ReasoningTrace
    sources: list[SourceItem]
    gonka_request_ids: list[str]
    metadata_uri: str = ""

# ============================================================
# GONKA CLIENT
# ============================================================
async def call_gonka(model: str, system_prompt: str, user_prompt: str, temp: float = 0.2) -> tuple[str, str]:
    """Call Gonka Router, return (content, request_id)"""
    headers = {
        "Authorization": f"Bearer {GONKA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temp,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        r = await client.post(f"{GONKA_BASE_URL}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        request_id = data["id"]
        return content, request_id

# ============================================================
# SEARCH
# ============================================================
async def search_facts(query: str, max_results: int = 3) -> list[SourceItem]:
    """Search real-time facts using Tavily"""
    if not TAVILY_API_KEY:
        return [SourceItem(title="(search unavailable)", url="")]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                }
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            return [
                SourceItem(title=res.get("title", ""), url=res.get("url", ""))
                for res in results
            ]
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return []

# ============================================================
# PROMPTS
# ============================================================
PROMPT_PRO = """You are a strict fact-checker (PRO side).
Your task: given a claim and background facts, find evidence that SUPPORTS the claim.
Rules:
1. Only use the provided background facts - do not invent information
2. Be logical and cite specific evidence
3. Objective and neutral

Output format:
【正方论点】
(your analysis)"""

PROMPT_CON = """You are a strict fact-checker (CON side).
Your task: given a claim and background facts, find evidence that REFUTES the claim.
Rules:
1. Only use the provided background facts - do not invent information
2. Point out inaccuracies, exaggerations, or misleading statements
3. Be logical and objective

Output format:
【反方论点】
(your analysis)"""

PROMPT_JUDGE = """You are an impartial judge. Analyze the PRO and CON arguments.
Output format (MUST follow exactly):
【真实性评分】: X/100
【最终裁定】: TRUE / FALSE / DISPUTED
【裁决理由】: (brief reason)"""

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(title="AI Fact Checker API", version="2.0.0", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "AI Fact Checker", "version": "2.0.0"}

@app.get("/api/models")
async def list_models():
    return {
        "models": {"pro": PRO_MODEL, "con": CON_MODEL, "judge": JUDGE_MODEL},
        "base_url": GONKA_BASE_URL,
    }

@app.post("/api/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest):
    try:
        claim_text = request.text.strip()
        logger.info(f"Verifying: {claim_text[:60]}...")

        # Search for background facts
        sources = await search_facts(claim_text)

        # Build context from search results
        context_lines = ["【背景事实】"]
        for s in sources:
            context_lines.append(f"- {s.title}: {s.url}")
        context = "\n".join(context_lines) if sources else "（无实时搜索结果，请基于常识判断）"

        user_prompt = f"""【待核查声明】
{claim_text}

{context}

请根据以上【背景事实】进行分析。"""

        # Call Pro and Con agents in parallel
        pro_task = call_gonka(PRO_MODEL, PROMPT_PRO, user_prompt)
        con_task = call_gonka(CON_MODEL, PROMPT_CON, user_prompt)
        pro_content, pro_id = await pro_task
        con_content, con_id = await con_task

        # Call Judge agent
        judge_prompt = f"""【待裁判声明】
{claim_text}

【正方论点】
{pro_content}

【反方论点】
{con_content}

请综合以上正反方意见，给出最终裁决。"""

        judge_content, judge_id = await call_gonka(JUDGE_MODEL, PROMPT_JUDGE, judge_prompt, temp=0.1)

        # Parse judge output
        import re
        score_match = re.search(r"(\d+)\s*/\s*100", judge_content)
        truth_score = int(score_match.group(1)) if score_match else 50

        verdict_match = re.search(r"(TRUE|FALSE|DISPUTED)", judge_content)
        verdict = verdict_match.group(1) if verdict_match else (
            "TRUE" if truth_score >= 70 else ("FALSE" if truth_score <= 30 else "DISPUTED")
        )

        consensus = "CONSENSUS_REACHED" if verdict != "DISPUTED" else "DISPUTED"

        # Distance from 50 determines confidence
        dist = abs(truth_score - 50) / 50.0
        confidence = round(0.5 + dist * 0.5, 2)

        claim_hash = Web3.keccak(text=claim_text).hex()

        return VerifyResponse(
            claim=claim_text,
            claim_hash=claim_hash,
            truth_score=truth_score,
            verdict=verdict,
            confidence=confidence,
            consensus_status=consensus,
            reasoning_trace=ReasoningTrace(
                pro_argument=pro_content,
                con_argument=con_content,
                judge_verdict=judge_content,
            ),
            sources=sources,
            gonka_request_ids=[pro_id, con_id, judge_id],
            metadata_uri="",
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"Gonka API error: {e.response.text}")
        raise HTTPException(status_code=502, detail=f"Gonka API error: {e.response.text}")
    except Exception as e:
        logger.exception(f"Verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Mock endpoint for testing without API keys
MOCK_RESPONSE = VerifyResponse(
    claim="特朗普宣布免除所有联邦学生贷款",
    claim_hash="0x7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
    truth_score=12,
    verdict="FALSE",
    confidence=0.95,
    consensus_status="CONSENSUS_REACHED",
    reasoning_trace=ReasoningTrace(
        pro_argument="社交媒体上有相关视频和推文传播，部分账号声称看到了相关公告。",
        con_argument="白宫官方与教育部未发布任何行政令，主流媒体无报道，2024年 student loan relief 已被最高法院否决。",
        judge_verdict="【真实性评分】: 12/100\n【最终裁定】: FALSE\n【裁决理由】: 缺乏官方文件支持，且被主流事实核查机构证伪，判定为假新闻。"
    ),
    sources=[SourceItem(title="White House Official Statements", url="https://www.whitehouse.gov/")],
    gonka_request_ids=["req_pro_demo_001", "req_con_demo_002", "req_judge_demo_003"],
    metadata_uri="",
)

@app.get("/api/mock/verify", response_model=VerifyResponse)
async def mock_verify():
    return MOCK_RESPONSE

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)