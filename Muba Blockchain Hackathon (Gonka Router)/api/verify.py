import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


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


GONKA_BASE_URL = _normalize_gonka_base_url(os.environ.get("GONKA_BASE_URL", "https://api.gonkarouter.io/v1"))

MODEL_CONFIGS = [
    {
        "provider": "DeepSeek",
        "model": os.environ.get("GONKA_DEEPSEEK_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731"),
        "role": "Adversarial evidence auditor",
    },
    {
        "provider": "Kimi",
        "model": os.environ.get("GONKA_KIMI_MODEL", "moonshotai/Kimi-K2.6"),
        "role": "Long-context source and timeline analyst",
    },
    {
        "provider": "MiniMax",
        "model": os.environ.get("GONKA_MINIMAX_MODEL", "MiniMaxAI/MiniMax-M2.7"),
        "role": "Logic, framing, and consensus verifier",
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
        "status": "ok",
        "latencyMs": latency_ms,
        "verdict": "unverified",
        "truthScore": 50,
        "confidence": 20 if has_article else 10,
        "summary": summary,
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


def _call_model(config, api_key, claim, article, language):
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
    user_prompt = (
        f"Answer language: {language}\n\n"
        f"CLAIM OR USER INPUT:\n{claim}\n\n"
        f"AVAILABLE EVIDENCE:\n{article_context}\n\n"
        "Perform the independent fact-check now and return only the required JSON."
    )
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            api_response = json.loads(response.read().decode("utf-8"))
        message = api_response.get("choices", [{}])[0].get("message", {})
        content = message.get("content") or message.get("reasoning_content") or message.get("reasoning") or ""
        parsed = _extract_json(content)
        metrics = parsed.get("metrics") if isinstance(parsed.get("metrics"), dict) else {}
        steps = parsed.get("reasoning_steps") if isinstance(parsed.get("reasoning_steps"), list) else []
        references = parsed.get("references") if isinstance(parsed.get("references"), list) else []
        result.update({
            "status": "ok",
            "verdict": _normalize_verdict(parsed.get("verdict")),
            "truthScore": _clamp_number(parsed.get("truth_score"), 50),
            "confidence": _clamp_number(parsed.get("confidence"), 50),
            "request_id": api_response.get("id", ""),  # 🌟 Gonka Request ID（每个模型的推理凭据）
            "model_display": config["model"],
            "summary": str(parsed.get("summary") or "").strip(),
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
            "usage": api_response.get("usage", {}),
            "router": api_response.get("x_gonka") or api_response.get("x_joingonka") or {},
        })
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        result.update({"status": "error", "error": _format_http_error(exc, detail)})
    except (URLError, TimeoutError) as exc:
        result.update({"status": "error", "error": _format_connection_error(exc)})
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return _fallback_result(config, claim, article, f"Invalid model response: {exc}", latency_ms)
    finally:
        result["latencyMs"] = round((time.perf_counter() - started) * 1000)
    return result


def _aggregate(claim, article, results, started_at):
    claim_hash = "0x" + hashlib.sha256(claim.encode("utf-8")).hexdigest()
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
            "attestation": {"claimHash": claim_hash, "evidenceHash": evidence_hash, "schema": "#gonka-fact-v1", "network": "Base Mainnet", "uid": "pending", "status": "ready_to_mint"},
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

    summaries = [f"{item['provider']}: {item['summary']}" for item in successful if item.get("summary")]
    # 收集所有成功模型的 Gonka Request IDs（供合约存证）
    gonka_request_ids = [item.get("request_id", "") for item in successful if item.get("request_id")]

    return {
        "id": f"gnk-{uuid.uuid4().hex[:10]}", "status": "ok" if len(successful) == total else "partial",
        "claim": claim, "inputType": "url" if article else "text", "article": article,
        "verdict": majority_verdict, "truthScore": truth_score, "confidence": confidence,
        "consensus": f"{agreement_count}/{len(successful)} successful models agree; {len(successful)}/{total} models responded",
        "summary": " ".join(summaries), "metrics": metrics, "models": results,
        "references": references[:20], "riskFlags": risk_flags[:20],
        "attestation": {"claimHash": claim_hash, "evidenceHash": evidence_hash, "schema": "#gonka-fact-v1", "network": "Base Sepolia", "uid": "pending", "status": "ready_to_mint",
                        "gonkaRequestIds": gonka_request_ids,  # 🌟 核心加分项
                        "timestamp": datetime.now(timezone.utc).isoformat()},
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "latencyMs": round((time.perf_counter() - started_at) * 1000),
    }


class handler(BaseHTTPRequestHandler):
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
        configs = [config for config in MODEL_CONFIGS if enabled.get(config["provider"].lower(), True)]
        unavailable_models = [config["model"] for config in configs if config["model"] not in available_models]
        if unavailable_models:
            _json_response(self, 502, {
                "status": "error",
                "error": "Configured model IDs are not available from the Gonka broker. Update the GONKA_*_MODEL values to match GET /models.",
                "unavailableModels": unavailable_models,
                "availableModels": sorted(available_models),
                "baseUrl": GONKA_BASE_URL,
            })
            return
        if len(configs) < 2:
            _json_response(self, 400, {"status": "error", "error": "Enable at least two AI agents for adversarial verification."})
            return
        language = str(settings.get("language") or "en")[:20]
        with ThreadPoolExecutor(max_workers=len(configs)) as executor:
            futures = [executor.submit(_call_model, config, api_key, claim, article, language) for config in configs]
            results = [future.result() for future in as_completed(futures)]
        order = {config["provider"]: i for i, config in enumerate(MODEL_CONFIGS)}
        results.sort(key=lambda item: order.get(item.get("provider"), 99))
        response = _aggregate(claim, article, results, started_at)
        if article_error:
            response["articleError"] = article_error
            if "article_fetch_failed" not in response["riskFlags"]:
                response["riskFlags"].append("article_fetch_failed")
        _json_response(self, 200 if response["status"] in {"ok", "partial"} else 502, response)
