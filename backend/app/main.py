"""港口集装箱作业管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import ROUTERS
from app.security import PermissionDenied
from app.services.pollutant import BusinessError
from app.store import store

app = FastAPI(title="港口集装箱作业管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PermissionDenied)
async def permission_denied_handler(_: Request, exc: PermissionDenied) -> JSONResponse:
    """越权统一 403：报文里点明当前角色与缺失的权限点。"""
    return JSONResponse(status_code=403, content={"detail": exc.payload()})


@app.exception_handler(BusinessError)
async def business_error_handler(_: Request, exc: BusinessError) -> JSONResponse:
    """业务规则不满足（如重复提交、状态锁定）按错误自带的状态码返回。"""
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": {"code": "business_rule", "message": str(exc)}})


for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()
