"""
Backend Config - Environment Variables
队员 1 - AI 后端工程师
"""
import os
from dotenv import load_dotenv

load_dotenv()  # 加载 .env 文件


# ── Gonka Router（必须） ────────────────────────
GONKA_API_KEY = os.getenv("GONKA_API_KEY", "")
GONKA_BASE_URL = os.getenv("GONKA_BASE_URL", "https://api.gonkarouter.io/v1")

if not GONKA_API_KEY:
    raise ValueError(
        "GONKA_API_KEY is not set! "
        "Get your key at https://gonkarouter.io and add to .env"
    )

# ── Search APIs（推荐至少一个） ─────────────────
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")

# ── Server Config ────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# ── CORS（允许前端跨域） ────────────────────────
ALLOWED_ORIGINS = [
    "http://localhost:3000",       # Next.js dev
    "http://localhost:5173",       # Vite dev
    "https://your-frontend.com",   # 生产环境（替换为实际 URL）
]

# ── Logging ────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")