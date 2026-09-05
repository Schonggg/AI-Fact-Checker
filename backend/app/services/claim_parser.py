"""
Claim Parser - Extract core claims from user input
队员 1 - AI 后端工程师
任务 2（补充）：从推文/URL/文本中提取核心主张（Claim）
"""
import re
from typing import Optional

from Crypto.Hash import keccak


CONTRACT_VERDICT_MAP = {
    "true": "TRUE",
    "false": "FALSE",
    "misleading": "DISPUTED",
}


def normalize_claim(text: str) -> str:
    """Normalize claim text before hashing so all clients hash identical input."""
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def extract_claim(text: str) -> str:
    """
    从用户输入中提取核心主张。
    清理多余的语气词、转发标记、hashtag 等。

    Examples:
        "特朗普宣布免除所有联邦学生贷款" → "特朗普宣布免除所有联邦学生贷款"
        "RT @user: 这是真的吗？" → "这是真的吗？"
        "突发！#BreakingNews 某事发生了" → "某事发生了"
    """
    # 移除 RT 标记
    text = re.sub(r'^RT\s+@\w+:\s*', '', text)

    # 移除 hashtag（保留文字）
    text = re.sub(r'#\w+', '', text)

    # 移除 @mention（保留文字用于判断）
    # 注意：不完全移除，因为有时 @xxx 是声明的一部分
    # text = re.sub(r'@\w+', '', text)

    # 移除 URL
    text = re.sub(r'https?://\S+', '', text)

    # 移除多余空白
    text = re.sub(r'\s+', ' ', text).strip()

    # 如果清理后太短，保留原文
    if len(text) < 5:
        return text.strip()

    return text


def extract_claim_simple(text: str) -> str:
    """
    简化版 claim 提取：直接返回清理后的文本。
    后续可以升级为 LLM 提取。
    """
    return extract_claim(text)


def is_url(text: str) -> bool:
    """判断输入是否为 URL"""
    return bool(re.match(r'https?://', text.strip()))


def is_tweet(text: str) -> bool:
    """判断输入是否为推文（包含 RT/@等特征）"""
    return bool(re.search(r'^(RT|@)', text.strip())) or len(text) < 150


def classify_input_type(text: str) -> str:
    """
    分类用户输入类型。
    Returns: "url" | "tweet" | "text"
    """
    if is_url(text):
        return "url"
    if is_tweet(text):
        return "tweet"
    return "text"


# ── Keccak256 claim_hash 工具（供 routes.py 使用） ────────────────────
def generate_claim_hash(claim_text: str) -> str:
    """
    生成 claim_hash（keccak256 bytes32 hex 格式）。
    与智能合约 TruthRegistry.sol 完全对齐。
    """
    digest = keccak.new(digest_bits=256)
    digest.update(normalize_claim(claim_text).encode("utf-8"))
    return "0x" + digest.hexdigest()


def contract_verdict(verdict: str) -> str | None:
    """Map an API verdict to TruthRegistry's accepted uppercase values."""
    return CONTRACT_VERDICT_MAP.get(str(verdict or "").strip().lower())


TRUTH_REGISTRY_ADDRESS = "0xb0DeedAe473dc32DD2B69bFdEc554e3b34119c58"