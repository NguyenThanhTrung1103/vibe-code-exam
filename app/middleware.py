"""HTTP middlewares — request_id binding and error logging."""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate or pass through X-Request-ID and bind it to structlog context."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        clear_contextvars()
        bind_contextvars(request_id=request_id, path=request.url.path, method=request.method)
        log = structlog.get_logger("http")
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed")
            raise
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
