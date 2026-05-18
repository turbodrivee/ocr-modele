"""Wave 7 — response_model strict + image_processor exception coverage.

- The /v1/ocr/extract route now declares `response_model=OCRExtractResponse`
  so FastAPI validates the response shape and OpenAPI exposes a real schema.
- `preprocess_image` now also catches `UnidentifiedImageError` / `OSError` /
  `SyntaxError`, mapping them to `OCR_VALIDATION_ERROR` (400) instead of
  letting them bubble up as 500.
- `CINData` exposes the `pere` field that the parser has been returning since
  Wave 5+7 — schema and reality must agree.
"""

from __future__ import annotations

from tests._helpers import make_jpeg


SECRET = "test-secret"


def _post(client, *, doc_type="permis", file_bytes=None, content_type="image/jpeg"):
    if file_bytes is None:
        file_bytes = make_jpeg()
    return client.post(
        "/v1/ocr/extract",
        headers={"X-Internal-Secret": SECRET},
        files={"file": ("doc.jpg", file_bytes, content_type)},
        data={"doc_type": doc_type},
    )


# ── response_model: shape strict ────────────────────────────────────────────


def test_wave7_response_shape_matches_model(client):
    r = _post(client)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"success", "data"}
    assert body["success"] is True

    payload = body["data"]
    assert set(payload.keys()) == {
        "doc_type",
        "confidence",
        "status",
        "data",
        "processing_time_ms",
    }
    assert isinstance(payload["confidence"], (int, float))
    assert payload["status"] in {"ok", "review", "failed"}
    assert isinstance(payload["processing_time_ms"], int)


def test_wave7_openapi_exposes_oc_extract_response(client):
    # OpenAPI must reference OCRExtractResponse (not just `dict`).
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas", {})
    assert "OCRExtractResponse" in schemas
    assert "OCRExtractPayload" in schemas
    # POST /v1/ocr/extract 200 response must reference the model.
    op = spec["paths"]["/v1/ocr/extract"]["post"]
    ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/OCRExtractResponse")


# ── CINData now exposes `pere` ──────────────────────────────────────────────


def test_wave7_cin_data_schema_has_pere_field():
    from schemas import CINData

    fields = CINData.model_fields
    assert "pere" in fields
    # Default should be None (Optional).
    instance = CINData()
    assert instance.pere is None


# ── image_processor: corrupted bytes → 400, never 500 ──────────────────────


def test_wave7_random_bytes_returns_400_not_500(client):
    # 4 KB of pure noise served as image/jpeg — PIL.UnidentifiedImageError.
    junk = b"\x00\x01\x02\x03" * 1024
    r = _post(client, file_bytes=junk, content_type="image/jpeg")
    assert r.status_code == 400, f"got {r.status_code}, body={r.text}"
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "OCR_VALIDATION_ERROR"


def test_wave7_truncated_jpeg_returns_400(client):
    # JPEG magic header followed by a single byte → triggers OSError on load().
    truncated = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00"
    r = _post(client, file_bytes=truncated, content_type="image/jpeg")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "OCR_VALIDATION_ERROR"


def test_wave7_valid_image_still_returns_200(client):
    # Regression: don't break the happy path.
    r = _post(client)
    assert r.status_code == 200


# ── image_unreadable propagates from preprocess_image directly ──────────────


def test_wave7_preprocess_raises_image_unreadable_for_junk():
    from utils.image_processor import preprocess_image
    import pytest

    with pytest.raises(ValueError) as exc:
        preprocess_image(b"not an image at all")
    assert str(exc.value) == "image_unreadable"
