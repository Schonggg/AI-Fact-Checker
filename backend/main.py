"""
WARNING: Deprecated local FastAPI backend. Production runs from
Muba Blockchain Hackathon (Gonka Router)/api/verify.py on Vercel.

AI Fact Checker - FastAPI Backend Entry Point
队员 1 - Jin Yi
Version 3.0 - 5维雷达图 + Kimi超时自动降级 + 合约存证
"""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from dotenv import load_dotenv

load_dotenv()  # 加载 backend/.env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 50)
    logger.info("AI Fact Checker Backend 启动")
    logger.info(f"Gonka Router: {GONKA_BASE_URL}")
    logger.info("Models: PRO=Kimi-K2.6 | CON=MiniMax-M2.7 | JUDGE=DeepSeek-V4-Flash")
    logger.info("=" * 50)
    yield
    logger.info("Backend 关闭")


app = FastAPI(
    title="AI Fact Checker API",
    description="Gonka 去中心化事实核查引擎 - 5维雷达图 + 合约存证",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS - 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "name": "AI Fact Checker",
        "version": "3.0.0",
        "docs": "/docs",
        "health": "/health",
        "verify": "/api/verify",
        "mock": "/api/mock/verify",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)