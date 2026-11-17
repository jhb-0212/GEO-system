"""统一错误信封：未捕获异常也必须返回 {"error": {...}}，不能退回 FastAPI 的 {"detail": ...}。"""

import asyncio
import json

from starlette.requests import Request

from app.main import app


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/boom",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
        }
    )


def test_unhandled_exception_returns_error_envelope():
    handler = app.exception_handlers[Exception]
    response = asyncio.run(handler(_request(), RuntimeError("boom")))
    payload = json.loads(response.body)
    assert response.status_code == 500
    assert payload["error"]["code"] == "internal_error"
    assert payload["error"]["message"]
    assert "detail" not in payload
