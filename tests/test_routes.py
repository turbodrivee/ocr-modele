from __future__ import annotations

from tests._helpers import make_jpeg


SECRET = "test-secret"


def _post_extract(client, *, doc_type="permis", file_bytes=None, content_type="image/jpeg", headers=None):
    if file_bytes is None:
        file_bytes = make_jpeg()
    h = {"X-Internal-Secret": SECRET}
    if headers:
        h.update(headers)
    return client.post(
        "/v1/ocr/extract",
        headers=h,
        files={"file": ("doc.jpg", file_bytes, content_type)},
        data={"doc_type": doc_type},
    )


def test_health_live(client):
    r = client.get("/v1/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_ready_with_engines(client):
    # client fixture installs stub engines
    r = client.get("/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_missing_secret_returns_401(client):
    r = client.post(
        "/v1/ocr/extract",
        files={"file": ("doc.jpg", make_jpeg(), "image/jpeg")},
        data={"doc_type": "permis"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "OCR_UNAUTHORIZED"


def test_invalid_doc_type_returns_400(client):
    r = _post_extract(client, doc_type="foo")
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "OCR_INVALID_DOC_TYPE"
    assert "allowed" in body["error"]["details"]


def test_unsupported_mime_returns_415(client):
    r = _post_extract(client, content_type="image/gif")
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "OCR_UNSUPPORTED_MEDIA"


def test_payload_too_large_via_content_length(client, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")  # 1 KB cap
    get_settings.cache_clear()  # type: ignore[attr-defined]
    # IMPORTANT: clear the cache again after the test so env-cleanup is honored.
    monkeypatch.setattr(get_settings, "cache_clear", get_settings.cache_clear)
    # Register a finalizer via the request fixture instead — see test_payload_finalizer below.
    try:
        big = make_jpeg(1500, 1500)
        assert len(big) > 1024
        r = _post_extract(client, file_bytes=big)
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "OCR_PAYLOAD_TOO_LARGE"
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_request_id_roundtrip(client):
    r = _post_extract(client, headers={"X-Request-ID": "req-abc-123"})
    assert r.headers.get("X-Request-ID") == "req-abc-123"


def test_request_id_generated_when_missing(client):
    r = _post_extract(client)
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    assert len(rid) >= 8


def test_happy_path_permis(client):
    r = _post_extract(client, doc_type="permis")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    payload = body["data"]
    assert payload["doc_type"] == "permis"
    assert payload["status"] in {"ok", "review", "failed"}
    assert "confidence" in payload
    assert "processing_time_ms" in payload
    assert payload["data"]["numero"] == "23238943"


def test_happy_path_cin(client, install_stub_engines):
    install_stub_engines("cin")
    r = _post_extract(client, doc_type="cin")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["data"]["numero_cin"] == "12345678"
    assert body["data"]["data"]["gouvernorat"] == "TUNIS"


def test_happy_path_carte_grise(client, install_stub_engines):
    install_stub_engines("carte_grise")
    r = _post_extract(client, doc_type="carte_grise")
    assert r.status_code == 200
    data = r.json()["data"]["data"]
    assert data["immatriculation"] == "123TU4567"
    assert data["marque"] == "TOYOTA"
    assert data["annee"] == "2018"


def test_happy_path_assurance(client, install_stub_engines):
    install_stub_engines("assurance")
    r = _post_extract(client, doc_type="assurance")
    assert r.status_code == 200
    data = r.json()["data"]["data"]
    assert data["numero_police"] == "2025/1234567"
    assert data["compagnie"] == "STAR"


def test_envelope_shape_on_error(client):
    r = _post_extract(client, doc_type="foo")
    body = r.json()
    assert set(body.keys()) == {"success", "error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}


def test_envelope_shape_on_success(client):
    r = _post_extract(client)
    body = r.json()
    assert set(body.keys()) == {"success", "data"}
    payload = body["data"]
    assert set(payload.keys()) >= {"doc_type", "confidence", "status", "data", "processing_time_ms"}
