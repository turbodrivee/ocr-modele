from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)


class OCRErrorCode(str, Enum):
    UNAUTHORIZED = "OCR_UNAUTHORIZED"
    INVALID_DOC_TYPE = "OCR_INVALID_DOC_TYPE"
    UNSUPPORTED_MEDIA = "OCR_UNSUPPORTED_MEDIA"
    IMAGE_TOO_SMALL = "OCR_IMAGE_TOO_SMALL"
    PAYLOAD_TOO_LARGE = "OCR_PAYLOAD_TOO_LARGE"
    ENGINE_FAILURE = "OCR_ENGINE_FAILURE"
    ENGINE_TIMEOUT = "OCR_ENGINE_TIMEOUT"
    RATE_LIMITED = "OCR_RATE_LIMITED"
    VALIDATION_ERROR = "OCR_VALIDATION_ERROR"
    INTERNAL = "OCR_INTERNAL"


_HTTP_STATUS_MAP: dict[OCRErrorCode, int] = {
    OCRErrorCode.UNAUTHORIZED: 401,
    OCRErrorCode.INVALID_DOC_TYPE: 400,
    OCRErrorCode.UNSUPPORTED_MEDIA: 415,
    OCRErrorCode.IMAGE_TOO_SMALL: 400,
    OCRErrorCode.PAYLOAD_TOO_LARGE: 413,
    OCRErrorCode.ENGINE_FAILURE: 502,
    OCRErrorCode.ENGINE_TIMEOUT: 504,
    OCRErrorCode.RATE_LIMITED: 429,
    OCRErrorCode.VALIDATION_ERROR: 400,
    OCRErrorCode.INTERNAL: 500,
}


class OCRError(Exception):
    def __init__(
        self,
        code: OCRErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def status_code(self) -> int:
        return _HTTP_STATUS_MAP[self.code]


def envelope_error(code: OCRErrorCode, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "error": {
            "code": code.value,
            "message": message,
            "details": details or {},
        },
    }


async def ocr_error_handler(request: Request, exc: OCRError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = {"X-Request-ID": request_id} if request_id else {}
    try:
        from metrics import ocr_errors_total

        ocr_errors_total.labels(code=exc.code.value).inc()
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope_error(exc.code, exc.message, exc.details),
        headers=headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    headers = {"X-Request-ID": request_id} if request_id else {}
    logger.exception(
        "unhandled_exception",
        extra={"request_id": request_id, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content=envelope_error(
            OCRErrorCode.INTERNAL,
            "Internal server error",
            {"request_id": request_id} if request_id else {},
        ),
        headers=headers,
    )
