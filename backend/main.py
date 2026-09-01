"""
AI Fact Checker - FastAPI Main Entry Point
队员 1 - AI 后端工程师
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import ALLOWED_ORIGINS, DEBUG
from app.api.routes import router

# ── Logging ─────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Lifespan（启动/关闭钩子） ────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 AI Fact Checker Backend starting...")
    logger.info("📡 Gonka Router: https://gonkarouter.io/v1")
    yield
    logger.info("👋 Backend shutting down...")


# ── FastAPI App ──────────────────────────────────
app = FastAPI(
    title="AI Fact Checker API",
    description="Gonka-based decentralized fact verification engine",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",       # Swagger UI
    redoc_url="/redoc",    # ReDoc (alternative docs)
)

# CORS（允许前端跨域调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)


# ── Root ─────────────────────────────────────────
@app.get("/", tags=["root"])
async def root():
    return {
        "service": "AI Fact Checker",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# ── 本地运行 ─────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    from app.core.config import HOST, PORT
    uvicorn.run("main:app", host=HOST, port=PORT, reload=DEBUG)