"""
Consensus Agent - 多模型对抗与5维共识引擎
队员 1 - AI 后端工程师
阶段3：多模型对抗 + 终审裁判 + 5维雷达图指标
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional
from .gonka_client import (
    call_pro_con_parallel, call_judge_agent,
    GonkaError, PRO_MODEL, CON_MODEL, JUDGE_MODEL,
)
from .search_engine import get_search_engine, SearchResult

logger = logging.getLogger(__name__)

# ── System Prompts ────────────────────────────────

PROMPT_PRO = """你是一名严谨的事实核查员（正方）。
你的任务：给定一个声明（Claim）和【背景事实】，寻找支持该声明成立的证据和理由。

要求：
1. 只基于【背景事实】进行分析，不要编造
2. 逻辑清晰，列出支持的理由
3. 客观中立，不夸大

输出格式：
【正方论点】
（你的分析论证，引用具体事实）"""

PROMPT_CON = """你是一名严谨的事实核查员（反方）。
你的任务：给定一个声明（Claim）和【背景事实】，寻找反驳该声明的证据和逻辑漏洞。

要求：
1. 只基于【背景事实】进行分析，不要编造
2. 指出不准确之处、夸大说法或误导性表述
3. 客观中立，不为反驳而反驳

输出格式：
【反方论点】
（你的分析论证，引用具体事实）"""

PROMPT_JUDGE = """你是一名公正的事实核查裁判。综合正反方意见，给出最终裁决和5维量化评分。

输出格式（必须严格按此JSON格式，不得有任何多余文字）：
{
  "verdict": "TRUE"或"FALSE"或"DISPUTED",
  "truth_score": 0-100,
  "confidence": 0-100,
  "metrics": {
    "factual": 0-100,
    "sources": 0-100,
    "logic": 0-100,
    "bias": 0-100,
    "consensus": 0-100
  },
  "reasoning": "裁决理由（50字以内）"
}"""


@dataclass
class RadarMetrics:
    """5维雷达图指标"""
    factual: int      # 事实准确度
    sources: int     # 信源权威度
    logic: int        # 逻辑自洽性
    bias: int         # 偏见/煽动指数（越低越好）
    consensus: int    # 模型间共识度


@dataclass
class VerdictOutput:
    """最终输出 - 对应 verify_schema"""
    claim: str
    claim_hash: str
    truth_score: int
    verdict: str
    confidence: float
    metrics: RadarMetrics
    reasoning_trace: dict
    sources: list[dict]
    gonka_request_ids: list[str]
    eas_metadata: dict


class ConsensusAgent:
    """
    多模型共识引擎。

    流程：
    1. 实时搜索背景事实
    2. asyncio.gather 并行正反方辩论
    3. 裁判综合裁决 → 5维量化指标
    4. 组装 Keccak256 claim_hash
    5. 返回完整标准化输出
    """

    def __init__(self):
        self.search = get_search_engine()

    async def run(self, claim: str) -> VerdictOutput:
        logger.info(f"[ConsensusAgent] 开始核查: {claim[:60]}...")

        # Step 1: 搜索背景事实
        search_results = await self.search.search(claim, max_results=5)
        context = self.search.build_context(search_results)
        user_prompt = f"""【待核查声明】
{claim}

{context}

请根据以上【背景事实】进行分析。"""

        # Step 2: 并发正反方辩论（asyncio.gather，任一失败不崩溃）
        logger.info(f"[ConsensusAgent] 正反方并行辩论: PRO={PRO_MODEL}, CON={CON_MODEL}")
        pro_result, con_result = await call_pro_con_parallel(
            PROMPT_PRO, user_prompt,
            PROMPT_CON, user_prompt,
        )
        pro_content, pro_req_id = pro_result
        con_content, con_req_id = con_result

        if isinstance(pro_req_id, str) and not pro_req_id:
            logger.warning(f"[ConsensusAgent] Pro agent 返回异常 ID: {pro_req_id}")
        if isinstance(con_req_id, str) and not con_req_id:
            logger.warning(f"[ConsensusAgent] Con agent 返回异常 ID: {con_req_id}")

        # Step 3: 裁判终审（高可用 DeepSeek）
        judge_prompt = f"""【待裁判声明】
{claim}

【正方论点】
{pro_content}

【反方论点】
{con_content}

请综合以上正反方意见，给出最终裁决。"""

        logger.info(f"[ConsensusAgent] 裁判终审: JUDGE={JUDGE_MODEL}")
        try:
            judge_content, judge_req_id = await call_judge_agent(PROMPT_JUDGE, judge_prompt)
        except GonkaError as e:
            logger.error(f"[ConsensusAgent] Judge failed: {e}")
            judge_content = ""
            judge_req_id = ""

        # Step 4: 解析裁判输出 → 5维指标
        metrics, truth_score, verdict, confidence = self._parse_judge(judge_content)

        # Step 5: claim_hash（Keccak256）
        from web3 import Web3
        claim_hash = Web3.keccak(text=claim.strip()).hex()

        # Step 6: IPFS CID 模拟（后续接真实 IPFS）
        import uuid
        ipfs_cid = f"Qm{uuid.uuid4().hex[:44]}"
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Step 7: sources 列表
        sources = [
            {"title": r.title, "url": r.url}
            for r in search_results
            if r.url
        ]

        # Step 8: 过滤空 request_id
        gonka_ids = [rid for rid in [pro_req_id, con_req_id, judge_req_id] if rid]
        if not gonka_ids:
            gonka_ids = [f"fallback_{uuid.uuid4().hex[:8]}"]
            logger.warning(f"[ConsensusAgent] 无有效 Request ID，使用 fallback: {gonka_ids}")

        logger.info(f"[ConsensusAgent] 完成: verdict={verdict}, score={truth_score}, ids={gonka_ids}")

        return VerdictOutput(
            claim=claim,
            claim_hash=claim_hash,
            truth_score=truth_score,
            verdict=verdict,
            confidence=confidence,
            metrics=metrics,
            reasoning_trace={
                "pro_argument": pro_content[:2000],
                "con_argument": con_content[:2000],
                "judge_verdict": judge_content[:2000],
            },
            sources=sources,
            gonka_request_ids=gonka_ids,
            eas_metadata={
                "schema": "#gonka-fact-v1",
                "network": "Arbitrum Sepolia",
                "timestamp": timestamp,
                "ipfs_cid": ipfs_cid,
                "claim_hash": claim_hash,
            },
        )

    def _parse_judge(self, content: str) -> tuple[RadarMetrics, int, str, float]:
        """解析裁判 JSON 输出，提取5维指标"""
        import json as _json

        # 尝试提取 JSON
        try:
            # 找到 JSON 块
            match = re.search(r"\{[^{}]*\"metrics\"[^{}]*\}", content, re.DOTALL)
            if not match:
                # 尝试找所有 {...} 内容
                start = content.find("{")
                end = content.rfind("}")
                if start >= 0 and end > start:
                    parsed = _json.loads(content[start:end+1])
                else:
                    raise ValueError("No JSON found")
            else:
                parsed = _json.loads(match.group(0))
        except Exception:
            logger.warning(f"[ConsensusAgent] 裁判输出无法解析为JSON: {content[:200]}")
            return self._fallback_metrics(50)

        # 提取 metrics
        m = parsed.get("metrics", {})
        metrics = RadarMetrics(
            factual=_clamp(m.get("factual", 50)),
            sources=_clamp(m.get("sources", 50)),
            logic=_clamp(m.get("logic", 50)),
            bias=_clamp(m.get("bias", 50)),
            consensus=_clamp(m.get("consensus", 50)),
        )

        # truth_score
        truth_score = _clamp(parsed.get("truth_score", 50))

        # verdict
        v = str(parsed.get("verdict", "")).strip().upper()
        if v in ("TRUE", "REAL", "VERIFIED"):
            verdict = "TRUE"
        elif v in ("FALSE", "FAKE", "DEBUNKED"):
            verdict = "FALSE"
        else:
            verdict = "DISPUTED"

        # confidence
        confidence = round(_clamp(parsed.get("confidence", 50)) / 100.0, 2)

        return metrics, truth_score, verdict, confidence

    def _fallback_metrics(self, truth_score: int) -> tuple[RadarMetrics, int, str, float]:
        """解析失败时的保守降级"""
        if truth_score >= 70:
            verdict = "TRUE"
            metrics = RadarMetrics(75, 65, 80, 15, 70)
            confidence = 0.75
        elif truth_score <= 30:
            verdict = "FALSE"
            metrics = RadarMetrics(20, 60, 70, 85, 70)
            confidence = 0.80
        else:
            verdict = "DISPUTED"
            metrics = RadarMetrics(50, 50, 50, 50, 40)
            confidence = 0.50
        return metrics, truth_score, verdict, confidence


def _clamp(v: float, lo: int = 0, hi: int = 100) -> int:
    """限制在 [lo, hi] 范围内"""
    try:
        return max(lo, min(hi, int(round(v))))
    except (TypeError, ValueError):
        return 50


_consumer_agent: Optional[ConsensusAgent] = None


def get_consensus_agent() -> ConsensusAgent:
    global _consumer_agent
    if _consumer_agent is None:
        _consumer_agent = ConsensusAgent()
    return _consumer_agent