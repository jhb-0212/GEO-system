"""FastAPI 应用入口：模块化单体，业务路由统一在 app.api 下挂载。

错误响应统一信封：{"error": {"code": "...", "message": "..."}}。
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import configure_logging, request_id_var

request_logger = logging.getLogger("geo.request")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """给每个请求一个可检索的 request_id，并用一行 JSON 记录结果。"""
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_logger.info(
                "request",
                extra={
                    "fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            request_id_var.reset(token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        """参数校验失败也走统一错误信封，避免 FastAPI 默认的 {"detail": [...]} 破约定。"""
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "请求参数校验失败",
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """未捕获异常同样返回统一信封：前端不会因为 {"detail": ...} 退化成语义丢失。"""
        request_logger.exception(
            "unhandled request error",
            extra={
                "fields": {
                    "request_id": request_id_var.get(),
                    "method": request.method,
                    "path": request.url.path,
                }
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "服务器内部错误，请稍后重试",
                }
            },
        )

    app.include_router(api_router)
    return app


app = create_app()
