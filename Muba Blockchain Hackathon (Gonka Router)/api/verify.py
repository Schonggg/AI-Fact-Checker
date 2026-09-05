import hashlib
import html
import io
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.core.web3_config import ATTESTATION_PROTOCOL, CHAIN_NAME, MIN_GONKA_PROOF_IDS, SCHEMA_ID
from app.services.claim_parser import contract_verdict, generate_claim_hash

# Configure logging to stderr (Vercel serverless captures stderr in function logs).
logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("gonka.factchecker")


def _load_local_env():
    """Load .env.local when this file is run outside Vercel."""
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env.local"))
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env()

MAX_INPUT_CHARS = 12000
MAX_ARTICLE_CHARS = 28000
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("GONKA_MODEL_TIMEOUT", "45"))
ARTICLE_TIMEOUT_SECONDS = int(os.environ.get("GONKA_ARTICLE_TIMEOUT", "15"))
# Kimi 专属超时（秒）：超过即自动降级到 DeepSeek，避免慢模型拖垮整单
KIMI_TIMEOUT_SECONDS = int(os.environ.get("GONKA_KIMI_MODEL_TIMEOUT", "30"))
# Vercel maxDuration 预算上限（秒），保证总耗时不被掐断
MAX_TOTAL_BUDGET_SECONDS = int(os.environ.get("GONKA_TOTAL_BUDGET_SECONDS", "50"))
# 降级兜底模型
FALLBACK_MODEL = os.environ.get("GONKA_FALLBACK_MODEL", "MiniMaxAI/MiniMax-M2.7")
PINATA_TIMEOUT_SECONDS = int(os.environ.get("PINATA_TIMEOUT", "8"))
def _normalize_gonka_base_url(value):
    """Return the OpenAI-compatible Gonka broker base URL ending in /v1."""
    url = str(value or "https://api.gonkarouter.io/v1").strip().rstrip("/")
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("GONKA_BASE_URL must be an absolute HTTPS URL, for example https://api.openbroker.gonka.gg/v1")
    if parsed.scheme != "https":
        raise ValueError("GONKA_BASE_URL must use HTTPS")
    for endpoint_suffix in ("/chat/completions", "/models"):
        if url.endswith(endpoint_suffix):
            url = url[: -len(endpoint_suffix)]
            break
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


try:
    GONKA_BASE_URL = _normalize_gonka_base_url(os.environ.get("GONKA_BASE_URL", "https://api.gonkarouter.io/v1"))
except ValueError as _base_url_err:
    # A malformed GONKA_BASE_URL must NOT crash the whole serverless function
    # (it would 500 every request, including /health). Fall back to the public default
    # and surface the misconfiguration via the health endpoint + logs.
    logging.getLogger("gonka.factchecker").error(
        "Invalid GONKA_BASE_URL (%s); falling back to https://api.gonkarouter.io/v1",
        _base_url_err,
    )
    GONKA_BASE_URL = "https://api.gonkarouter.io/v1"

MODEL_CONFIGS = [
    {
        "provider": "DeepSeek",
        "model": os.environ.get("GONKA_DEEPSEEK_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731"),
        "role": "Con - challenges the claim",
        "panel_role": "con",
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "fallback": None,
    },
    {
        "provider": "Kimi",
        "model": os.environ.get("GONKA_KIMI_MODEL", "moonshotai/Kimi-K2.6"),
        "role": "Pro - supports the claim",
        "panel_role": "pro",
        "timeout": KIMI_TIMEOUT_SECONDS,
        "fallback": FALLBACK_MODEL,
    },
    {
        "provider": "MiniMax",
        "model": os.environ.get("GONKA_MINIMAX_MODEL", "MiniMaxAI/MiniMax-M2.7"),
        "role": "Judge - resolves the Pro/Con debate",
        "panel_role": "judge",
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "fallback": None,
    },
]

SYSTEM_PROMPT = """You are one independent member of a three-model adversarial fact-checking panel.
Your task is to assess a claim using only the supplied text/article evidence. Return ONLY one valid compact JSON object, without markdown fences or prose.

JSON schema:
{"verdict":"true|false|misleading|unverified","truth_score":0-100,"confidence":0-100,"summary":"concise conclusion","reasoning_steps":[{"label":"short label","status":"ok|warning|error|info","detail":"what was checked and found"}],"metrics":{"factual_accuracy":0-100,"source_quality":0-100,"logical_consistency":0-100,"bias_neutrality":0-100,"temporal_consistency":0-100},"references":[{"title":"real supplied source title","url":"absolute https URL when known, otherwise empty string","publisher":"publisher/domain","source_type":"article|official|research|primary|other","published_at":"date or empty string","stance":"supports|contradicts|context|unclear","relevance":0-100,"credibility":0-100,"quote":"brief supporting passage or empty string"}],"risk_flags":["specific limitations"]}

Rules:
- Do not claim you browsed or searched the web. You only have the evidence supplied in the prompt.
- Never invent a citation, URL, title, date, statistic, or quote.
- A reachable article URL is evidence of what the article says, not automatic proof that its assertions are true.
- If evidence is insufficient or the claim depends on current external facts absent from supplied text, prefer "unverified" and lower confidence.
- Produce 4-8 useful reasoning_steps so the website can show the verification process.
- Include supplied article/reference only when present.
"""

PRO_SYSTEM_PROMPT = SYSTEM_PROMPT + """
Panel role: PRO.
Find the strongest evidence and reasoning supporting the claim. Even if evidence is incomplete, make the strongest supportable pro argument and identify its limitations. Do not make the final panel decision.
"""

CON_SYSTEM_PROMPT = SYSTEM_PROMPT + """
Panel role: CON.
Find the strongest evidence and reasoning that the claim is false, misleading, overstated, or unsupported. Make the strongest supportable counterargument and identify its limitations. Do not make the final panel decision.
"""

JUDGE_SYSTEM_PROMPT = SYSTEM_PROMPT + """
Panel role: JUDGE.
You will receive complete structured outputs from Pro and Con. Resolve their competing arguments using only those submissions and supplied evidence. Do not perform a separate independent assessment or invent absent evidence.
"""


def _json_response(handler, status_code, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", os.environ.get("GONKA_ALLOWED_ORIGIN", "*"))
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if status_code != 204:
        handler.wfile.write(body)


def _read_json_body(handler):
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    if length > 200_000:
        raise ValueError("Request body is too large")
    return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")


def _clamp_number(value, default=50):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, round(number)))


def _normalize_verdict(value):
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"true", "real", "verified", "likely_true", "supported"}:
        return "true"
    if text in {"false", "fake", "likely_false", "debunked"}:
        return "false"
    if text in {"misleading", "partly_false", "partially_true", "mixed"}:
        return "misleading"
    return "unverified"


def _extract_json(text):
    if not text:
        raise ValueError("Model returned an empty response")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _fallback_result(config, claim, article, reason, latency_ms):
    has_article = bool(article and article.get("text"))
    source_quality = 65 if has_article else 15
    summary = (
        "The model did not return strict JSON, so this agent is marked unverified. "
        "The fetched article is still shown as context for human review."
        if has_article else
        "The model did not return strict JSON and no external article text was available, so this agent is marked unverified."
    )
    return {
        "provider": config["provider"],
        "model": config["model"],
        "role": config["role"],
        "status": "error",
        "latencyMs": latency_ms,
        "verdict": "unverified",
        "truthScore": 50,
        "confidence": 20 if has_article else 10,
        "summary": summary,
        "error": reason[:500],
        "steps": [
            {"label": "Input captured", "status": "ok", "detail": f"Claim/input received: {claim[:220]}"},
            {"label": "Article extraction", "status": "ok" if has_article else "warning", "detail": f"Extracted {article.get('characters', 0)} readable characters from the URL." if has_article else "No readable public HTTPS article text was supplied."},
            {"label": "Structured analysis", "status": "warning", "detail": reason[:500]},
            {"label": "Safety downgrade", "status": "info", "detail": "Because the model response could not be parsed as the required schema, the verdict is conservatively downgraded to unverified."},
        ],
        "metrics": {
            "factualAccuracy": 50,
            "sourceQuality": source_quality,
            "logicalConsistency": 50,
            "biasNeutrality": 50,
            "temporalConsistency": 50,
        },
        "references": [],
        "riskFlags": ["model_json_parse_failed"],
        "usage": {},
        "router": {},
    }


def _extract_first_url(value):
    match = re.search(r"https?://[^\s<>'\")]+", str(value or ""))
    return match.group(0).rstrip(".,;!?") if match else ""


def _normalize_possible_url(value):
    url = _extract_first_url(value) or str(value or "").strip()
    if url.startswith("http://"):
        parsed_http = urlparse(url)
        if parsed_http.hostname and parsed_http.hostname.lower() not in {"localhost", "127.0.0.1", "0.0.0.0"}:
            url = "https://" + url[len("http://"):]
    return url


def _is_public_https_url(value):
    try:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        port = parsed.port or 443
        for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(item[4][0])
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
                return False
        return True
    except Exception:
        return False


def _strip_html(raw_html):
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    title = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
    published = ""
    for pattern in [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']date["\'][^>]+content=["\']([^"\']+)',
        r'<time[^>]+datetime=["\']([^"\']+)',
    ]:
        match = re.search(pattern, raw_html, flags=re.IGNORECASE)
        if match:
            published = match.group(1).strip()
            break
    text = re.sub(r"<(script|style|svg|noscript|template)[^>]*>[\s\S]*?</\1>", " ", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|article|section|h[1-6]|li|blockquote|br)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if len(line) >= 20]
    return title, published, "\n".join(lines)[:MAX_ARTICLE_CHARS]


def _fetch_article(url):
    url = _normalize_possible_url(url)
    if not _is_public_https_url(url):
        raise ValueError("Only public HTTPS article URLs are supported")
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; GonkaFactChecker/1.0; +https://muba-blockchain-hackathon-gonka-rou.vercel.app/)",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.8",
    })
    with urlopen(request, timeout=ARTICLE_TIMEOUT_SECONDS) as response:
        final_url = response.geturl()
        if not _is_public_https_url(final_url):
            raise ValueError("Article redirected to a disallowed address")
        content_type = response.headers.get("Content-Type", "")
        charset_match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
        charset = charset_match.group(1).strip('"\'') if charset_match else "utf-8"
        raw = response.read(1_500_000).decode(charset, errors="replace")
    if "json" in content_type:
        body_text = json.dumps(json.loads(raw), ensure_ascii=False)[:MAX_ARTICLE_CHARS]
        title, published = urlparse(final_url).hostname or "JSON source", ""
    else:
        title, published, body_text = _strip_html(raw)
    if len(body_text) < 120:
        raise ValueError("The article page did not expose enough readable text; it may block server-side access or require JavaScript/login")
    return {
        "url": final_url,
        "title": title or urlparse(final_url).hostname or "Article",
        "publisher": urlparse(final_url).hostname or "",
        "publishedAt": published,
        "text": body_text,
        "characters": len(body_text),
    }


def _extract_api_error_message(raw_detail):
    text = str(raw_detail or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return re.sub(r"\s+", " ", text)[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        code = str(error.get("code") or "").strip()
        if message and code:
            return f"{message} ({code})"
        return message or code
    if isinstance(error, str):
        return error.strip()
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("detail") or "").strip()
    return ""


def _format_http_error(exc, detail):
    provider_message = _extract_api_error_message(detail)
    if exc.code in {401, 403}:
        suffix = f": {provider_message}" if provider_message else ""
        return f"Gonka API key validation failed (HTTP {exc.code}){suffix}. Check that GONKA_API_KEY belongs to the configured broker and has not expired."
    if exc.code == 404:
        suffix = f": {provider_message}" if provider_message else ""
        return f"Gonka API endpoint was not found (HTTP 404){suffix}. Check GONKA_BASE_URL; it should be the broker base URL ending in /v1, not a full endpoint path."
    if exc.code in {429, 500, 502, 503, 504}:
        suffix = f": {provider_message}" if provider_message else ""
        return f"Gonka API request failed with HTTP {exc.code}{suffix}."
    suffix = f": {provider_message}" if provider_message else f": {str(detail or '').strip()[:500]}" if detail else ""
    return f"Gonka API request failed with HTTP {exc.code}{suffix}."


def _format_connection_error(exc):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLError):
        return f"Gonka HTTPS/TLS connection failed: {reason}. Check the broker HTTPS URL and the local certificate store."
    if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
        return f"Gonka connection timed out after {REQUEST_TIMEOUT_SECONDS}s. The broker or selected model may be unavailable or too slow."
    return f"Gonka connection failed: {reason}. Check GONKA_BASE_URL, network access, and DNS."


def _get_models(api_key):
    request = Request(
        f"{GONKA_BASE_URL}/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": "Mozilla/5.0 GonkaFactChecker/1.0"},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise ValueError(_format_http_error(exc, detail)) from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError(_format_connection_error(exc)) from exc
    return [item.get("id") for item in payload.get("data", []) if item.get("id")]


def _gonka_raw_call(api_key, model, system_prompt, user_prompt, temperature=0.2, timeout=None):
    """Generic sync Gonka call returning (content, request_id). Reused by translation & search."""
    import json as _json
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 1024,
    }
    request = Request(
        f"{GONKA_BASE_URL}/chat/completions",
        data=_json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 GonkaFactChecker/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout or REQUEST_TIMEOUT_SECONDS) as response:
        api_response = _json.loads(response.read().decode("utf-8"))
    message = api_response.get("choices", [{}])[0].get("message", {})
    content = message.get("content") or message.get("reasoning_content") or message.get("reasoning") or ""
    return content, api_response.get("id", "")


def _translate_to_english(api_key, claim):
    """
    中译英：用 DeepSeek 把中文声明翻译成英文。
    用于提升外网搜索命中率。失败时原样返回。
    """
    system = "You are a precise translator. Translate the given claim into clear, factual English. Output ONLY the English translation, nothing else."
    try:
        en, _reqid = _gonka_raw_call(
            api_key,
            MODEL_CONFIGS[0]["model"],  # DeepSeek（高可用）
            system,
            f"Translate this claim to English:\n{claim}",
            temperature=0.1,
            timeout=25,
        )
        en = en.strip()
        if en and len(en) > 3:
            return en
    except Exception as exc:
        logging.warning(f"[translate] failed, using original: {exc}")
    return claim


def _discover_sources(api_key, claim, english_claim):
    """
    来源发现：用 DeepSeek 基于（英文）声明生成 3~5 个权威信源（title/url/publisher/stance）。
    返回 [{title, url, publisher, stance}]。失败时返回空列表（不阻塞主流程）。
    """
    combine = english_claim if english_claim != claim else claim
    system = """You are a fact-checking source researcher. Based on the claim, list 3-5 AUTHORITATIVE real-world sources (news outlets, official reports, research) that would verify or refute it.
Return ONLY compact JSON array, no markdown:
[{"title":"...","url":"https://...","publisher":"...","relevance":0-100,"credibility":0-100,"stance":"supports|contradicts|unclear"}]"""
    try:
        content, _reqid = _gonka_raw_call(
            api_key,
            MODEL_CONFIGS[0]["model"],  # DeepSeek
            system,
            f"Claim:\n{combine}",
            temperature=0.1,
            timeout=30,
        )
        parsed = _extract_json(content)
        if isinstance(parsed, list):
            out = []
            for item in parsed[:5]:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                # 只保留 https 真实URL，过滤假的占位 URL
                if url and (url.startswith("https://") or url.startswith("http://")):
                    out.append({
                        "title": str(item.get("title") or "Source").strip()[:200],
                        "url": url,
                        "publisher": str(item.get("publisher") or "").strip()[:100],
                        "relevance": _clamp_number(item.get("relevance"), 70),
                        "credibility": _clamp_number(item.get("credibility"), 60),
                        "stance": str(item.get("stance") or "unclear").strip().lower(),
                        "sourceType": "research",
                    })
            return out
        return []
    except Exception as exc:
        logging.warning(f"[sources] discovery failed: {exc}")
        return []


def _search_tavily(query, max_results=5):
    """
    Tavily 实时外网搜索（仅用于搜索真实来源，不用于分析/推理）。
    返回 [{title, url, content, publishedAt}]。失败时返回空列表。
    """
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        logging.warning("[search] TAVILY_API_KEY missing, skipping web search")
        return []
    try:
        request = Request(
            "https://api.tavily.com/search",
            data=json.dumps({
                "api_key": tavily_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
                "search_depth": "advanced",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        out = []
        for item in payload.get("results", [])[:max_results]:
            url = str(item.get("url") or "").strip()
            if url.startswith("https://") or url.startswith("http://"):
                out.append({
                    "title": str(item.get("title") or "Source").strip()[:200],
                    "url": url,
                    "publisher": str(item.get("domain") or "").strip()[:100],
                    "content": str(item.get("content") or "")[:800],
                    "publishedAt": "",
                })
        return out
    except Exception as exc:
        logging.warning(f"[search] Tavily failed: {exc}")
        return []


def _normalize_reference(reference, article):
    if not isinstance(reference, dict):
        return None
    url = str(reference.get("url") or "").strip()
    if url and not url.startswith("https://"):
        url = ""
    if article and (not url or url == article.get("url")):
        url = article.get("url", url)
    return {
        "title": str(reference.get("title") or (article or {}).get("title") or "Reference").strip(),
        "url": url,
        "publisher": str(reference.get("publisher") or (article or {}).get("publisher") or "").strip(),
        "sourceType": str(reference.get("source_type") or "article").strip().lower(),
        "publishedAt": str(reference.get("published_at") or (article or {}).get("publishedAt") or "").strip(),
        "stance": str(reference.get("stance") or "unclear").strip().lower(),
        "relevance": _clamp_number(reference.get("relevance"), 70),
        "credibility": _clamp_number(reference.get("credibility"), 60),
        "quote": str(reference.get("quote") or "").strip()[:600],
    }


def _call_model(config, api_key, claim, article, language, search_results=None, debate_context=None, timeout_override=None):
    started = time.perf_counter()
    result = {
        "provider": config["provider"],
        "model": config["model"],
        "role": config["role"],
        "status": "pending",
        "latencyMs": None,
    }
    article_context = "No article URL was supplied. Assess only the claim and explicitly flag missing external evidence."
    if article:
        article_context = (
            f"ARTICLE URL: {article['url']}\n"
            f"ARTICLE TITLE: {article['title']}\n"
            f"PUBLISHER: {article['publisher']}\n"
            f"PUBLISHED AT: {article['publishedAt'] or 'not found'}\n"
            f"EXTRACTED ARTICLE TEXT:\n{article['text']}"
        )
    search_context = ""
    if search_results:
        lines = ["REAL-TIME WEB SEARCH RESULTS (use as primary evidence for fact-checking):"]
        for i, item in enumerate(search_results, 1):
            title = str(item.get("title") or "Source")
            url = str(item.get("url") or "")
            publisher = str(item.get("publisher") or "")
            content = str(item.get("content") or "")[:3000]
            lines.append(f"[{i}] {title}")
            if publisher:
                lines.append(f"    Publisher: {publisher}")
            if url:
                lines.append(f"    URL: {url}")
            if content:
                lines.append(f"    Content: {content}")
        search_context = "\n".join(lines)
    user_prompt = (
        f"Answer language: {language}\n\n"
        f"CLAIM OR USER INPUT:\n{claim}\n\n"
        f"AVAILABLE EVIDENCE:\n{article_context}\n\n"
        + (f"REAL-TIME WEB SEARCH RESULTS (use these as real, externally-verified sources; you may cite their URLs in references):\n{search_context}\n\n" if search_context else "")
        + "Perform the independent fact-check now and return only the required JSON."
    )
    if debate_context:
        user_prompt += f"\n\nPRO/CON SUBMISSIONS (complete structured outputs):\n{json.dumps(debate_context, ensure_ascii=False)}\n\nReturn the Judge decision now."
    timeout_seconds = timeout_override or config.get("timeout", REQUEST_TIMEOUT_SECONDS)
    deadline = started + timeout_seconds
    primary_timeout = timeout_seconds
    if config.get("fallback"):
        primary_timeout = max(5, timeout_seconds // 2)
    system_prompt = {"pro": PRO_SYSTEM_PROMPT, "con": CON_SYSTEM_PROMPT, "judge": JUDGE_SYSTEM_PROMPT}.get(config.get("panel_role"), SYSTEM_PROMPT)

    def _attempt(model_id, timeout):
        """单次 Gonka 调用，成功返回 (parsed_dict, request_id, usage, router)，失败抛异常。"""
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 3200,
            "stream": False,
        }
        request = Request(
            f"{GONKA_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 GonkaFactChecker/1.0",
                "X-Gonka-No-Fallback": "true",
            },
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            api_response = json.loads(response.read().decode("utf-8"))
        message = api_response.get("choices", [{}])[0].get("message", {})
        content = message.get("content") or message.get("reasoning_content") or message.get("reasoning") or ""
        parsed = _extract_json(content)
        request_id = response.headers.get("X-Request-Id") or api_response.get("id", "")
        return parsed, request_id, api_response.get("usage", {}), (api_response.get("x_gonka") or api_response.get("x_joingonka") or {})

    try:
        (parsed, request_id, usage, router) = _attempt(config["model"], primary_timeout)
        model_used = config["model"]
        fell_back = False
    except Exception as primary_error:
        # Kimi is best-effort: timeouts, 5xx responses, unavailable channels, and
        # malformed JSON all continue through the same MiniMax fallback path.
        fallback = config.get("fallback")
        if fallback and fallback != config["model"]:
            try:
                fallback_timeout = max(1, int(deadline - time.perf_counter()))
                (parsed, request_id, usage, router) = _attempt(fallback, fallback_timeout)
                model_used = fallback
                fell_back = True
                fallback_note = f"Kimi unavailable; completed with MiniMax fallback. Primary error: {primary_error}"
            except Exception as fallback_error:
                latency_ms = round((time.perf_counter() - started) * 1000)
                return _fallback_result(config, claim, article, f"Primary {config['model']}: {primary_error}; fallback {fallback}: {fallback_error}", latency_ms)
        else:
            latency_ms = round((time.perf_counter() - started) * 1000)
            return _fallback_result(config, claim, article, f"Model response failed: {primary_error}", latency_ms)

    metrics = parsed.get("metrics") if isinstance(parsed.get("metrics"), dict) else {}
    steps = parsed.get("reasoning_steps") if isinstance(parsed.get("reasoning_steps"), list) else []
    references = parsed.get("references") if isinstance(parsed.get("references"), list) else []
    result.update({
        "status": "ok",
        "verdict": _normalize_verdict(parsed.get("verdict")),
        "truthScore": _clamp_number(parsed.get("truth_score"), 50),
        "confidence": _clamp_number(parsed.get("confidence"), 50),
        "request_id": request_id,  # 🌟 Gonka Request ID（每个模型的推理凭据）
        "model_display": config["model"],
        "model_used": model_used,  # 实际执行模型（含降级情况）
        "fell_back": fell_back,
        "summary": (f"{fallback_note} " if fell_back else "") + str(parsed.get("summary") or "").strip(),
        "steps": [
            {
                "label": str(step.get("label") or "Verification step").strip(),
                "status": str(step.get("status") or "info").strip().lower(),
                "detail": str(step.get("detail") or "").strip(),
            }
            for step in steps if isinstance(step, dict)
        ][:10],
        "metrics": {
            "factualAccuracy": _clamp_number(metrics.get("factual_accuracy"), 50),
            "sourceQuality": _clamp_number(metrics.get("source_quality"), 50),
            "logicalConsistency": _clamp_number(metrics.get("logical_consistency"), 50),
            "biasNeutrality": _clamp_number(metrics.get("bias_neutrality"), 50),
            "temporalConsistency": _clamp_number(metrics.get("temporal_consistency"), 50),
        },
        "references": [ref for ref in (_normalize_reference(item, article) for item in references) if ref],
        "riskFlags": [str(flag).strip() for flag in parsed.get("risk_flags", []) if str(flag).strip()][:12],
        "usage": usage,
        "router": router,
        "latencyMs": round((time.perf_counter() - started) * 1000),
    })
    return result


def _aggregate(claim, article, results, started_at):
    claim_hash = generate_claim_hash(claim)
    evidence_seed = json.dumps({"claim": claim, "article": article, "models": [item.get("model") for item in results]}, ensure_ascii=False, sort_keys=True)
    evidence_hash = "0x" + hashlib.sha256(evidence_seed.encode("utf-8")).hexdigest()
    successful = [item for item in results if item.get("status") == "ok"]
    total = len(results)
    if not successful:
        model_errors = [
            f"{item.get('provider', 'Model')}: {item.get('error', 'unknown error')}"
            for item in results
            if item.get("status") == "error"
        ]
        error_detail = "; ".join(model_errors) or "No model returned a valid structured response."
        return {
            "id": f"gnk-{uuid.uuid4().hex[:10]}", "status": "error", "claim": claim,
            "inputType": "url" if article else "text", "article": article,
            "verdict": "unverified", "truthScore": 50, "confidence": 0,
            "consensus": f"0/{total} models returned valid results",
            "error": f"All configured Gonka models failed. {error_detail}",
            "summary": "No Gonka model returned a valid structured response. Review the model errors and API configuration.",
            "metrics": {"factualAccuracy": 50, "sourceQuality": 0, "logicalConsistency": 50, "biasNeutrality": 50, "temporalConsistency": 50, "consensus": 0},
            "models": results, "references": [], "riskFlags": ["all_models_failed"],
            "attestation": {"claimHash": claim_hash, "evidenceHash": evidence_hash, "schema": SCHEMA_ID, "network": CHAIN_NAME, "protocol": ATTESTATION_PROTOCOL, "uid": "pending", "status": "blocked", "metadataURI": "", "reason": "unverified_results_cannot_be_attested"},
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "latencyMs": round((time.perf_counter() - started_at) * 1000),
        }

    verdict_counts = {name: 0 for name in ("true", "false", "misleading", "unverified")}
    for item in successful:
        verdict_counts[item["verdict"]] = verdict_counts.get(item["verdict"], 0) + 1
    majority_verdict, agreement_count = max(verdict_counts.items(), key=lambda pair: pair[1])
    weights = [max(10, item["confidence"]) for item in successful]
    truth_score = round(sum(item["truthScore"] * weight for item, weight in zip(successful, weights)) / sum(weights))
    average_confidence = round(sum(item["confidence"] for item in successful) / len(successful))
    agreement_ratio = agreement_count / len(successful)
    confidence = round(average_confidence * (0.7 + 0.3 * agreement_ratio))
    if agreement_count == 1 and len(successful) > 1:
        majority_verdict = "unverified"
    metric_names = ["factualAccuracy", "sourceQuality", "logicalConsistency", "biasNeutrality", "temporalConsistency"]
    metrics = {name: round(sum(item["metrics"][name] for item in successful) / len(successful)) for name in metric_names}
    metrics["consensus"] = round(agreement_ratio * 100)

    references, seen_refs, risk_flags = [], set(), []
    if article:
        references.append({
            "title": article["title"], "url": article["url"], "publisher": article["publisher"],
            "sourceType": "article", "publishedAt": article.get("publishedAt", ""), "stance": "context",
            "relevance": 100, "credibility": 65, "quote": article["text"][:320], "citedBy": ["Article extractor"],
        })
        seen_refs.add(article["url"].lower())
    for item in successful:
        for flag in item.get("riskFlags", []):
            if flag and flag not in risk_flags:
                risk_flags.append(flag)
        for ref in item.get("references", []):
            key = (ref.get("url") or (ref.get("title", "") + ref.get("publisher", ""))).lower()
            if not key:
                continue
            if key in seen_refs:
                for existing in references:
                    existing_key = (existing.get("url") or (existing.get("title", "") + existing.get("publisher", ""))).lower()
                    if existing_key == key:
                        existing.setdefault("citedBy", []).append(item["provider"])
                        existing["relevance"] = max(existing.get("relevance", 0), ref.get("relevance", 0))
                        existing["credibility"] = max(existing.get("credibility", 0), ref.get("credibility", 0))
                continue
            seen_refs.add(key)
            ref["citedBy"] = [item["provider"]]
            references.append(ref)

    overview_item = next((item for item in successful if item.get("verdict") == majority_verdict and not item.get("fell_back") and item.get("summary")), None)
    if overview_item is None:
        overview_item = next((item for item in successful if item.get("verdict") == majority_verdict and item.get("summary")), None)
    overview_summary = overview_item.get("summary", "") if overview_item else "No model summary was returned."
    # 收集所有成功模型的 Gonka Request IDs（供合约存证）
    gonka_request_ids = [item.get("request_id", "") for item in successful if item.get("request_id")]
    attestation_status = "ready_to_mint" if len(gonka_request_ids) >= MIN_GONKA_PROOF_IDS else "blocked"
    attestation_reason = "" if attestation_status == "ready_to_mint" else f"insufficient_gonka_proof_ids: need {MIN_GONKA_PROOF_IDS}, got {len(gonka_request_ids)}"

    return {
        "id": f"gnk-{uuid.uuid4().hex[:10]}", "status": "ok" if len(successful) == total else "partial",
        "claim": claim, "inputType": "url" if article else "text", "article": article,
        "verdict": majority_verdict, "truthScore": truth_score, "confidence": confidence,
        "consensus": f"{agreement_count}/{len(successful)} successful models agree; {len(successful)}/{total} models responded",
        "summary": f"{majority_verdict.upper()} based on {agreement_count}/{len(successful)} successful models. {overview_summary}", "metrics": metrics, "models": results,
        "references": references[:20], "riskFlags": risk_flags[:20],
        "attestation": {"claimHash": claim_hash, "evidenceHash": evidence_hash, "schema": SCHEMA_ID, "network": CHAIN_NAME, "protocol": ATTESTATION_PROTOCOL, "uid": "pending", "status": attestation_status, "reason": attestation_reason,
                        "gonkaRequestIds": gonka_request_ids,  # 🌟 核心加分项
                        "timestamp": datetime.now(timezone.utc).isoformat()},
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "latencyMs": round((time.perf_counter() - started_at) * 1000),
    }


def _pin_verification(response):
    """Pin the report server-side; never expose the Pinata JWT to the browser."""
    token = os.environ.get("PINATA_JWT", "").strip()
    if not token:
        response.setdefault("riskFlags", []).append("pinata_not_configured")
        response["attestation"].update({"metadataURI": "", "status": "blocked", "reason": "PINATA_JWT is not configured"})
        return
    payload = {"pinataContent": response, "pinataMetadata": {"name": f"gonka-{response.get('id', 'verification')}"}}
    request = Request(
        "https://api.pinata.cloud/pinning/pinJSONToIPFS",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=PINATA_TIMEOUT_SECONDS) as pinata_response:
            pinata_result = json.loads(pinata_response.read().decode("utf-8"))
        cid = str(pinata_result.get("IpfsHash") or "").strip()
        if not cid:
            raise ValueError("Pinata response did not include IpfsHash")
        response["attestation"].update({"metadataURI": f"ipfs://{cid}", "pinataCid": cid})
    except Exception as exc:
        response.setdefault("riskFlags", []).append("pinata_upload_failed")
        response["attestation"].update({"metadataURI": "", "status": "blocked", "reason": str(exc)[:300]})


class VerifyRequestHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _json_response(self, 204, {})

    def do_GET(self):
        api_key = os.environ.get("GONKA_API_KEY")
        models = []
        error = None
        if api_key:
            try:
                models = _get_models(api_key)
            except Exception as exc:
                error = str(exc)
        status = "ok" if api_key and not error else "configuration_error" if error else "missing_api_key"
        _json_response(self, 200, {
            "name": "GONKA Adversarial Fact Checker API", "status": status,
            "baseUrl": GONKA_BASE_URL, "route": "/api/verify", "methods": ["GET", "POST", "OPTIONS"],
            "apiKeyConfigured": bool(api_key), "configuredModels": [item["model"] for item in MODEL_CONFIGS], "models": models, "modelsError": error,
            "requestBody": {"claim": "claim text or public HTTPS article URL", "settings": {"language": "zh", "agents": {"deepseek": True, "kimi": True, "minimax": True}}},
        })

    def do_POST(self):
        started_at = time.perf_counter()
        logging.getLogger("gonka.factchecker").info(
            "POST /api/verify from %s", self.client_address[0] if self.client_address else "?"
        )
        try:
            body = _read_json_body(self)
        except (json.JSONDecodeError, ValueError) as exc:
            _json_response(self, 400, {"status": "error", "error": str(exc)})
            return
        claim = str(body.get("claim") or body.get("text") or "").strip()
        if not claim:
            _json_response(self, 400, {"status": "error", "error": "Missing required field: claim"})
            return
        if len(claim) > MAX_INPUT_CHARS:
            _json_response(self, 413, {"status": "error", "error": f"Input is too long. Maximum {MAX_INPUT_CHARS} characters."})
            return
        api_key = os.environ.get("GONKA_API_KEY")
        if not api_key:
            _json_response(self, 503, {"status": "error", "error": "Server is missing GONKA_API_KEY. Add it to .env.local and Vercel Environment Variables."})
            return
        try:
            available_models = set(_get_models(api_key))
        except Exception as exc:
            _json_response(self, 502, {"status": "error", "error": str(exc), "baseUrl": GONKA_BASE_URL})
            return

        article, article_error = None, None
        candidate_url = _normalize_possible_url(claim)
        if _is_public_https_url(candidate_url):
            try:
                article = _fetch_article(candidate_url)
            except Exception as exc:
                article_error = str(exc)
        elif candidate_url.lower().startswith(("http://", "https://")):
            article_error = "Only public HTTPS article URLs are supported"

        settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
        enabled = settings.get("agents") if isinstance(settings.get("agents"), dict) else {}
        requested_configs = [config for config in MODEL_CONFIGS if enabled.get(config["provider"].lower(), True)]
        unavailable_models = [config["model"] for config in requested_configs if config["model"] not in available_models]
        configs = requested_configs
        panel_configs = {config["panel_role"]: config for config in configs}
        if set(panel_configs) != {"pro", "con", "judge"}:
            _json_response(self, 400, {"status": "error", "error": "Enable Kimi (Pro), DeepSeek (Con), and MiniMax (Judge) for Pro/Con/Judge verification."})
            return
        language = str(settings.get("language") or "en")[:20]

        # ── Tavily 实时搜索增强（仅检索真实信源，不用于分析/推理）──
        # 有文章 URL 时跳过（已用文章原文做证据）；否则翻译→发现信源→Tavily 搜索
        search_results = []
        search_summary = None
        if article is None and claim and settings.get("webSearch", True) is not False:
            try:
                search_en = claim
                # 仅当声明明显非英文时翻译（中→英提升外网命中率）；翻译失败不影响主流程
                if not re.search(r"[A-Za-z]{4,}", claim):
                    search_en = _translate_to_english(api_key, claim)
                discovered = _discover_sources(api_key, claim, search_en)
                search_query = search_en if search_en else claim
                for item in discovered:
                    item["query"] = search_query
                seen_urls = {item.get("url", "").lower() for item in discovered if item.get("url")}
                tavily_hits = _search_tavily(search_query, max_results=int(os.environ.get("TAVILY_MAX_RESULTS", "5")))
                for hit in tavily_hits:
                    if hit.get("url", "").lower() in seen_urls:
                        continue
                    discovered.append(hit)
                    seen_urls.add(hit.get("url", "").lower())
                search_results = discovered[: int(os.environ.get("TAVILY_MAX_RESULTS", "5"))]
                if search_results:
                    search_summary = {
                        "query": search_query,
                        "translated_from_zh": search_en != claim,
                        "count": len(search_results),
                        "sources": [
                            {
                                "title": item.get("title", "Source"),
                                "url": item.get("url", ""),
                                "publisher": item.get("publisher", ""),
                                "content": item.get("content", "")[:400],
                                "stance": item.get("stance", "unclear"),
                            }
                            for item in search_results
                        ],
                    }
            except Exception as exc:
                logging.warning(f"[search] web search stage failed (continuing without): {exc}")

        judge_reserve = min(panel_configs["judge"]["timeout"], 20)
        analysis_timeout = max(5, int(MAX_TOTAL_BUDGET_SECONDS - judge_reserve - (time.perf_counter() - started_at) - 2))
        with ThreadPoolExecutor(max_workers=2) as executor:
            pro_future = executor.submit(_call_model, panel_configs["pro"], api_key, claim, article, language, search_results, timeout_override=analysis_timeout)
            con_future = executor.submit(_call_model, panel_configs["con"], api_key, claim, article, language, search_results, timeout_override=analysis_timeout)
            pro_result = pro_future.result()
            con_result = con_future.result()
        elapsed = time.perf_counter() - started_at
        judge_timeout = max(5, min(panel_configs["judge"]["timeout"], int(MAX_TOTAL_BUDGET_SECONDS - elapsed - 3)))
        judge_result = _call_model(panel_configs["judge"], api_key, claim, article, language, search_results, debate_context={"pro": pro_result, "con": con_result}, timeout_override=judge_timeout)
        results = [con_result, pro_result, judge_result]
        response = _aggregate(claim, article, results, started_at)
        if unavailable_models:
            response.setdefault("riskFlags", []).append("unavailable_models:" + ",".join(unavailable_models))
        if response.get("verdict") == "unverified":
            response["attestation"].update({"status": "blocked", "reason": "unverified_results_cannot_be_attested"})
        else:
            response["attestation"]["contractVerdict"] = contract_verdict(response.get("verdict"))
        _pin_verification(response)
        response["timings"] = {
            "totalMs": round((time.perf_counter() - started_at) * 1000),
            "modelMs": max((item.get("latencyMs") or 0) for item in results) if results else 0,
            "pinataConfigured": bool(os.environ.get("PINATA_JWT")),
        }
        if article_error:
            response["articleError"] = article_error
            if "article_fetch_failed" not in response["riskFlags"]:
                response["riskFlags"].append("article_fetch_failed")
        # 把 Tavily 检索到的真实信源补充进 references（供前端展示
        if search_results:
            existing_urls = {ref.get("url", "").lower() for ref in response.get("references", []) if ref.get("url")}
            for item in search_results:
                url = item.get("url", "")
                if not url or url.lower() in existing_urls:
                    continue
                response["references"].append({
                    "title": str(item.get("title") or "Search result"),
                    "url": url,
                    "publisher": str(item.get("publisher") or ""),
                    "sourceType": "search",
                    "publishedAt": str(item.get("publishedAt") or ""),
                    "stance": str(item.get("stance") or "unclear").lower(),
                    "relevance": _clamp_number(item.get("relevance"), 60),
                    "credibility": _clamp_number(item.get("credibility"), 55),
                    "quote": str(item.get("content") or "")[:320],
                    "citedBy": ["Tavily"],
                })
                existing_urls.add(url.lower())
        response["search"] = search_summary
        _json_response(self, 200 if response["status"] in {"ok", "partial"} else 502, response)


# ── Vercel Python Serverless WSGI 入口 ───────────────────────────
# 标准 WSGI 适配（可选，供 gunicorn/uvicorn 等传统 WSGI 容器复用）。
# 注意：Vercel 的 /api 文件式 Python runtime 期望顶层 `handler` 是
# BaseHTTPRequestHandler 的【类】，不是这个 WSGI 函数。真正的 Vercel
# 入口在文件末尾 `handler = VerifyRequestHandler`。

def wsgi_handler(environ, start_response):
    """
    标准 WSGI app 接口（非 Vercel 入口；Vercel 走 handler 类）。
    environ: dict，类似 Flask/WSGI 的请求环境
    start_response(status_line, headers): 回调，用于发送响应头
    """
    import io

    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")
    query = environ.get("QUERY_STRING", "")

    # 从 environ 构建 HTTP 请求原始字节（供 BaseHTTPRequestHandler 解析）
    headers_out = {}
    for key, val in environ.items():
        if key.startswith("HTTP_"):
            headers_out[key[5:].replace("_", "-").title()] = val
    host = environ.get("HTTP_HOST", "localhost")
    headers_out["Host"] = host

    # 构造类似 HTTP 请求行的起始行
    request_line = f"{method} {path}"
    if query:
        request_line += f"?{query}"
    request_line += " HTTP/1.1\r\n"
    header_lines = request_line
    for k, v in headers_out.items():
        header_lines += f"{k}: {v}\r\n"
    header_lines += "\r\n"

    body_data = environ.get("wsgi.input", io.BytesIO()).read()
    if isinstance(body_data, str):
        body_data = body_data.encode("utf-8")
    raw_request = header_lines.encode("utf-8") + body_data

    # 用 BytesIO 捕获 handler 的输出
    response_buffer = io.BytesIO()

    # 实例化并运行 handler class
    h = HandlerForVercelWSGI(raw_request, response_buffer)
    handler_error = None
    try:
        h.handle()
    except Exception as exc:
        # NEVER silently swallow — surface to logs so Vercel function logs show the real cause.
        handler_error = exc
        logging.getLogger("gonka.factchecker").error(
            "WSGI handler raised: %s\n%s", exc, traceback.format_exc()
        )

    raw_response = response_buffer.getvalue()
    if not raw_response:
        err_msg = f"handler returned no output" + (f": {handler_error}" if handler_error else "")
        start_response("500 Internal Server Error", [("Content-Type", "application/json")])
        return [json.dumps({"status": "error", "error": err_msg}).encode("utf-8")]

    # 解析原始 HTTP 响应
    try:
        header_end = raw_response.index(b"\r\n\r\n")
        status_and_headers = raw_response[:header_end]
        body = raw_response[header_end + 4:]
        first_line, header_part = status_and_headers.split(b"\r\n", 1)
        status_code = int(first_line.split(b" ")[1])
        status_str = "200 OK" if status_code == 200 else f"{status_code} Error"
        resp_headers = []
        for line in header_part.decode("latin-1").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                resp_headers.append((k.strip(), v.strip()))
        # 过滤 transfer-encoding chunked
        resp_headers = [(k, v) for k, v in resp_headers
                        if k.lower() not in ("transfer-encoding", "connection")]
        start_response(status_str, resp_headers)
        return [body]
    except Exception:
        start_response("500 Internal Server Error", [("Content-Type", "application/json")])
        return [b'{"status":"error","error":"failed to parse handler response"}']


class HandlerForVercelWSGI(VerifyRequestHandler):
    """专用于 Vercel WSGI 的 handler：接收原始 HTTP 请求，输出到 BytesIO 缓冲区。

    必须继承 VerifyRequestHandler（而非 BaseHTTPRequestHandler），否则会丢失
    do_GET/do_POST/do_OPTIONS 方法，导致 Vercel 每个请求都返回 501。
    """

    # HTTP/1.0 → 每个请求后 close_connection=True，handle() 处理完一个请求即停止。
    # 不能用 HTTP/1.1：serverless 一次冷启动只应处理一个请求，keep-alive 循环会把
    # 请求体剩余字节当成下一条请求行，报 "Bad request version" 并污染响应。
    protocol_version = "HTTP/1.0"

    def __init__(self, raw_request, response_buffer):
        self._raw = raw_request
        self._buf = response_buffer
        # 先调用父类 __init__ 完成 setup（会设置 rfile/wfile）
        super().__init__(io.BytesIO(raw_request), ("127.0.0.1", 0), self)

    def setup(self):
        # 替换 setup：用 BytesIO 替代真实 socket
        self.rfile = io.BytesIO(self._raw)
        self.wfile = self._buf

    def finish(self):
        # 默认 StreamRequestHandler.finish() 会 close() self.wfile 与 self.rfile，
        # 但这里 self.wfile 就是调用方传入的 response_buffer——一旦被 close，
        # 调用方再 response_buffer.getvalue() 就会抛 "I/O operation on closed file"，
        # 导致 Vercel 每个请求都静默 500。这里覆盖为不关闭外部 buffer，只 flush。
        try:
            if not self.wfile.closed:
                self.wfile.flush()
        except (OSError, ValueError):
            pass

    def log_message(self, format, *args):
        pass  # 安静，不打印日志


# ── Vercel Lambda 入口点 ───────────────────────────────────────────
# Vercel 自动检测时调用 handler(event, context)
# 返回 dict: {statusCode, headers, body} — Vercel Python Runtime 标准格式

def vercel_entry(event, context):
    """
    Vercel Python Serverless 入口点（Lambda 风格）。
    将 Lambda event 转换为 WSGI 格式，调用 WSGI handler，再适配为 Vercel 响应。
    """
    import io

    method = (event.get("httpMethod") or "GET").upper()
    path = event.get("path") or "/"
    query = event.get("rawQuery") or ""
    headers = event.get("headers") or {}

    # 构造原始 HTTP 请求（供 VerifyRequestHandler 解析）
    request_lines = f"{method} {path}"
    if query:
        request_lines += f"?{query}"
    request_lines += " HTTP/1.1\r\nHost: localhost\r\n"
    for k, v in headers.items():
        request_lines += f"{k}: {v}\r\n"
    request_lines += "\r\n"

    body_bytes = event.get("body") or ""
    if isinstance(body_bytes, str):
        body_bytes = body_bytes.encode("utf-8")

    raw_request = request_lines.encode("utf-8") + body_bytes
    response_buffer = io.BytesIO()

    # 实例化 handler 并处理请求
    h = HandlerForVercelWSGI(raw_request, response_buffer)
    handler_error = None
    try:
        h.handle()
    except Exception as exc:
        # NEVER silently swallow — surface to Vercel function logs.
        handler_error = exc
        logging.getLogger("gonka.factchecker").error(
            "vercel_entry handler raised: %s\n%s", exc, traceback.format_exc()
        )

    raw = response_buffer.getvalue()
    if not raw:
        err_msg = "no output" + (f": {handler_error}" if handler_error else "")
        return {"statusCode": 500, "body": json.dumps({"status": "error", "error": err_msg})}

    try:
        header_end = raw.index(b"\r\n\r\n")
        status_line = raw[:raw.index(b"\r\n")]
        status_code = int(status_line.split(b" ")[1])
        body = raw[header_end + 4:].decode("utf-8", errors="replace")
    except Exception:
        status_code = 500
        body = raw.decode("utf-8", errors="replace")

    return {"statusCode": status_code, "body": body}


# ── Vercel 入口 ──────────────────────────────────────────────
# Vercel 的 /api 文件式 Python runtime 要求每个 .py 文件导出名为 `handler`
# 的顶层对象，且必须是 BaseHTTPRequestHandler 的【类】。Vercel 会实例化
# 该类并直接调用 do_GET / do_POST / do_OPTIONS。
# Ref: https://vercel.com/docs/functions/runtimes/python/api-directory
# 下面的 vercel_entry / HandlerForVercelWSGI 是旧版 Lambda 适配，现代
# Vercel 不会再调用它们，保留仅为向后兼容。

# Vercel 的检测器扫描 `class handler(` 模式识别 Python 函数入口。
# 用 class 定义（而非 handler = VerifyRequestHandler 赋值语句），
# 确保 Vercel 能检测到此文件为 Serverless Function。
class handler(VerifyRequestHandler):
    """Vercel 入口：继承 VerifyRequestHandler 的 do_GET/do_POST/do_OPTIONS。"""
    pass
