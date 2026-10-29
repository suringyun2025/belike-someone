from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("distill.errors")

# Stable, documented machine-readable codes. The human readable ``detail`` field
# is preserved alongside ``error`` so existing clients keep working.
CODE_BY_STATUS = {
    400: "INVALID_REQUEST",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def error_body(
    message: str,
    code: str,
    request_id: str = "",
    details: Any = None,
) -> dict[str, Any]:
    """Build the canonical error payload.

    ``detail`` mirrors ``error.message`` for backward compatibility with the
    first-generation frontend, which reads ``detail`` directly.
    """
    return {
        "detail": message,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details if details is not None else {},
        },
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("x-request-id", "")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, exc: HTTPException):  # noqa: ANN001
        code = CODE_BY_STATUS.get(exc.status_code, "ERROR")
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            code = str(detail["code"])
            message = str(detail.get("message") or detail)
            details = detail.get("details") or {}
        else:
            message = str(detail)
            details = {}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(message, code, _request_id(request), details),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(request: Request, exc: RequestValidationError):
        errors = []
        for item in exc.errors():
            errors.append(
                {
                    "location": ".".join(str(part) for part in item.get("loc", [])),
                    "message": item.get("msg", ""),
                    "type": item.get("type", ""),
                }
            )
        first = errors[0]["message"] if errors else "请求参数不合法"
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                f"请求参数不合法：{first}", "VALIDATION_ERROR", _request_id(request), {"errors": errors}
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN001
        request_id = _request_id(request)
        logger.exception("unhandled error", extra={"request_id": request_id, "path": request.url.path})
        # Never leak stack traces or provider payloads to the client.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(
                "服务器内部错误，请使用请求 ID 在日志中排查",
                "INTERNAL_ERROR",
                request_id,
            ),
        )