
"""FastAPI 应用入口。"""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging_config import configure_logging
from app.core.request_context import request_id_var


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())
        token = request_id_var.set(request_id)
        

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id

            logging.getLogger("app.request").info(
                "HTTP request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )

            return response

        except Exception:
            logging.getLogger("app.request").exception(
                "HTTP request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise

        finally:
            request_id_var.reset(token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(
        request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                }
            },
        )

    app.include_router(api_router)
    return app


app = create_app()
