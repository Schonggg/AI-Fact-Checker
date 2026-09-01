"""
Consensus Agent - Multi-Model Debate Engine
队员 1 - AI 后端工程师
任务 3：多模型对抗与共识裁决逻辑
使用至少 2 个异构模型进行正反对抗 + 裁判打分
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from .gonka_client import GonkaClient, get_gonka_client
from .search_engine import SearchEngine, get_search_engine

logger = logging.getLogger(__name__)

# ── System Prompts ────────────────────────────────

PRO_AGENT_SYSTEM = """你是一名严谨的事实核查员（正方）。
你的任务是：给定一个新闻声明（Claim），在提供的【背景事实】基础上，
寻找支持该声明成立的证据和理由。
要求：
1. 只基于【背景事实】进行分析，不要编造信息
2. 逻辑清晰，列出支持的理由
3. 客观中立，不夸大也不隐瞒
4. 如果【背景事实】与声明不符，应如实说明

输出格式：
【正方论点】
（你的分析论证）"""

CON_AGENT_SYSTEM = """你是一名严谨的事实核查员（反方）。
你的任务是：给定一个新闻声明（Claim），在提供的【背景事实】基础上，
寻找反驳该声明的证据和逻辑漏洞。
要求：
1. 只基于【背景事实】进行分析，不要编造信息
2. 指出声明中的不准确之处、夸大说法或误导性表述
3. 逻辑清晰，列出反驳的理由
4. 客观中立，不为反驳而反驳

输出格式：
【反方论点】
（你的分析论证）"""

JUDGE_AGENT_SYSTEM = """你是一名公正的裁判，负责综合正反方意见，给出最终裁决。
你的任务是：
1. 仔细阅读正方和反方的论点
2. 基于【背景事实】和双方论点，评判声明的真实性
3. 给出 0-100 的真实性评分（0=完全虚假，100=完全真实）
4. 输出最终裁定（TRUE/FALSE/DISPUTED）
5. 简述裁决理由

输出格式（严格按此格式，不得改变标签）：
【真实性评分】: X/100
【最终裁定】: TRUE / FALSE / DISPUTED
【裁决理由】: （你的简要说明）"""


@dataclass
class GonkaRequest:
    """单次 Gonka 调用的结果"""
    model_name: str   # e.g. "pro", "con", "judge"
    content: str      # 模型的回复文本
    request_id: str  # 🌟 Gonka 官方 Request ID（用于链上存证）


@dataclass
class DebateResult:
    """辩论完整结果"""
    pro_result:  GonkaRequest
    con_result:  GonkaRequest
    judge_result: GonkaRequest
    sources: list  # 搜索结果


@dataclass
class VerdictOutput:
    """最终输出格式（供 routes.py 使用）"""
    claim: str
    claim_hash: str       # bytes32 hex (供合约使用)
    truth_score: int      # 0-100
    verdict: str          # "TRUE" | "FALSE" | "DISPUTED"
    confidence: float     # 0.0-1.0
    consensus_status: str # "CONSENSUS_REACHED" | "DISPUTED"
    reasoning_trace: dict # {pro_argument, con_argument, judge_verdict}
    sources: list[dict]  # [{"title": ..., "url": ...}, ...]
    gonka_request_ids: list[str]  # 🌟 每次调用的 Request ID 数组
    metadata_uri: str     # 完整报告链接（或空字符串）


class ConsensusAgent:
    """
    多模型共识引擎。
    并行调用正方+反方（asyncio.gather），再由裁判综合裁决。
    全程捕获每个 Gonka Request ID。
    """

    def __init__(
        self,
        gonka_client: Optional[GonkaClient] = None,
        search_engine: Optional[SearchEngine] = None,
    ):
        self.gonka = gonka_client or get_gonka_client()
        self.search = search_engine or get_search_engine()

    async def run(self, claim: str) -> VerdictOutput:
        """
        完整流程：
        1. 搜索实时新闻作为背景事实
        2. 并发调用正方 + 反方模型（asyncio.gather）
        3. 裁判模型综合裁决
        4. 组装标准化 VerdictOutput

        Args:
            claim: 用户提交的原始声明/新闻文本
        Returns:
            VerdictOutput: 标准化的核查结果
        """
        from web3 import Web3  # 生成 claim_hash

        # Step 1: 搜索实时背景事实
        search_results = await self.search.search(claim, max_results=5)
        context = self.search.build_context(search_results)

        # 构建发送给模型的完整 prompt
        user_prompt_base = f"""【待核查声明】
{claim}

{context}

请根据以上【背景事实】进行分析。"""

        # Step 2: 并发调用正方 + 反方（10-15s 延迟优化关键）
        logger.info(f"Starting debate for claim: {claim[:50]}...")

        pro_task = self.gonka.call_pro_agent(PRO_AGENT_SYSTEM, user_prompt_base)
        con_task = self.gonka.call_con_agent(CON_AGENT_SYSTEM, user_prompt_base)

        pro_raw, con_raw = await asyncio.gather(pro_task, con_task)

        pro_content, pro_req_id = pro_raw
        con_content, con_req_id = con_raw

        logger.info(f"Pro/Con agents done. Request IDs: {pro_req_id}, {con_req_id}")

        # Step 3: 裁判综合裁决（需要把正反方结果作为输入）
        judge_prompt = f"""【待裁判声明】
{claim}

【正方论点】
{pro_content}

【反方论点】
{con_content}

{context}

请综合以上正反方意见，给出最终裁决。"""

        judge_content, judge_req_id = await self.gonka.call_judge_agent(
            JUDGE_AGENT_SYSTEM, judge_prompt
        )
        logger.info(f"Judge agent done. Request ID: {judge_req_id}")

        # Step 4: 解析裁判输出
        truth_score, verdict, judge_reasoning = self._parse_judge_output(judge_content)

        # Step 5: 组装 claim_hash（keccak256，bytes32 hex 格式）
        claim_hash = Web3.keccak(text=claim).hex()

        # Step 6: 组装 consensus_status
        consensus_status = "CONSENSUS_REACHED" if verdict != "DISPUTED" else "DISPUTED"

        # Step 7: 构建 sources 列表
        sources = [
            {"title": r.title, "url": r.url}
            for r in search_results
        ]

        return VerdictOutput(
            claim=claim,
            claim_hash=claim_hash,
            truth_score=truth_score,
            verdict=verdict,
            confidence=self._score_to_confidence(truth_score, verdict),
            consensus_status=consensus_status,
            reasoning_trace={
                "pro_argument": pro_content,
                "con_argument": con_content,
                "judge_verdict": judge_content,
            },
            sources=sources,
            gonka_request_ids=[pro_req_id, con_req_id, judge_req_id],
            # metadata_uri 后续可接 IPFS 或后端存储
            metadata_uri="",
        )

    def _parse_judge_output(self, judge_content: str) -> tuple[int, str, str]:
        """
        解析裁判输出，提取分数、裁定、理由。
        尝试正则匹配 fallback 到保守估计。
        """
        import re

        # 提取评分：尝试匹配 "【真实性评分】: X/100" 或 "X/100" 或 "score: X"
        score_match = re.search(
            r'(?:真实性评分|score|评分)[:\s]*(\d+)\s*/\s*100',
            judge_content,
            re.IGNORECASE
        )
        if score_match:
            truth_score = int(score_match.group(1))
        else:
            # Fallback: 如果解析失败，默认给 50（DISPUTED 边缘）
            logger.warning("Could not parse truth_score from judge output. Defaulting to 50.")
            truth_score = 50

        # 提取裁定：TRUE / FALSE / DISPUTED
        verdict_match = re.search(
            r'【最终裁定】[:\s]*(TRUE|FALSE|DISPUTED)',
            judge_content
        )
        if verdict_match:
            verdict = verdict_match.group(1)
        else:
            # Fallback: 基于分数判断
            if truth_score >= 70:
                verdict = "TRUE"
            elif truth_score <= 30:
                verdict = "FALSE"
            else:
                verdict = "DISPUTED"
            logger.warning(f"Could not parse verdict from judge output. Defaulting to {verdict}.")

        # 裁决理由：取【裁决理由】后面的内容
        reasoning_match = re.search(r'【裁决理由】[:\s]*(.+?)(?:\n\n|\Z)', judge_content, re.DOTALL)
        reasoning = reasoning_match.group(1).strip() if reasoning_match else judge_content[:200]

        return truth_score, verdict, reasoning

    def _score_to_confidence(self, truth_score: int, verdict: str) -> float:
        """
        将 truth_score 转换为 confidence (0.0-1.0)。
        逻辑：分数越靠近 0 或 100，confidence 越高；中间地带则低。
        """
        if verdict == "DISPUTED":
            return 0.5  # 有争议，confidence 中等
        # 距离 50 分越远，confidence 越高
        distance_from_middle = abs(truth_score - 50) / 50.0
        return round(0.5 + (distance_from_middle * 0.5), 2)