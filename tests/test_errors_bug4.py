"""BUG-4 — unhandled_exception_handler must return code OCR_INTERNAL (mapped to 500),
not OCR_ENGINE_FAILURE (mapped to 502). The HTTP status_code (500) and the body
`error.code`'s implied status MUST agree.

Also regression-tests that OCR_ENGINE_FAILURE still maps to 502 (used for real
engine failures raised explicitly via OCRError, not the catch-all handler).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from errors import OCRError, OCRErrorCode, _HTTP_STATUS_MAP, unhandled_exception_handler


def _fake_request(request_id: str | None = None) -> Request:
    """Minimal Starlette Request with the bits the handler reads."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/ocr/extract",
        "headers": [],
        "query_string": b"",
    }
    req = Request(scope)
    req.state.request_id = request_id
    return req


def test_bug_4_internal_code_mapped_to_500():
    assert _HTTP_STATUS_MAP[OCRErrorCode.INTERNAL] == 500


def test_bug_4_engine_failure_still_502_regression():
    # The original code stays mapped to 502 — used for explicit engine failures.
    assert _HTTP_STATUS_MAP[OCRErrorCode.ENGINE_FAILURE] == 502


@pytest.mark.asyncio
async def test_bug_4_unhandled_handler_returns_500():
    req = _fake_request(request_id="req-xyz")
    response = await unhandled_exception_handler(req, RuntimeError("boom"))
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_bug_4_unhandled_handler_body_code_is_internal():
    import json

    req = _fake_request(request_id="req-xyz")
    response = await unhandled_exception_handler(req, RuntimeError("boom"))
    body = json.loads(response.body)
    assert body["success"] is False
    assert body["error"]["code"] == "OCR_INTERNAL"
    # Must NOT be the old/wrong code anymore.
    assert body["error"]["code"] != "OCR_ENGINE_FAILURE"


@pytest.mark.asyncio
async def test_bug_4_request_id_propagated_in_header_and_body():
    import json

    req = _fake_request(request_id="req-abc-123")
    response = await unhandled_exception_handler(req, ValueError("nope"))
    assert response.headers.get("X-Request-ID") == "req-abc-123"
    body = json.loads(response.body)
    assert body["error"]["details"].get("request_id") == "req-abc-123"


def test_bug_4_engine_failure_via_ocrerror_returns_502():
    # If application code raises OCRError(ENGINE_FAILURE), status must be 502.
    err = OCRError(OCRErrorCode.ENGINE_FAILURE, "paddle crashed")
    assert err.status_code == 502


def test_bug_4_internal_via_ocrerror_returns_500():
    err = OCRError(OCRErrorCode.INTERNAL, "totally unexpected")
    assert err.status_code == 500
