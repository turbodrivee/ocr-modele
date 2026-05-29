# OCR Document Service

Internal FastAPI microservice that extracts structured data from Tunisian
document images (permis de conduire, CIN, carte grise, assurance) using
PaddleOCR (fr + ar pipelines).

**Audience**: called back-to-back by the Node backend. Not exposed to the
public internet, no CORS configured by design.

## Setup

### Option A — Docker (recommended)

```bash
cd ocr-service
cp .env.example .env
# Edit .env and set INTERNAL_SECRET to a strong random value

docker compose up -d --build   # ~5-10 min first time (bakes the 500 MB models in)
docker compose logs -f         # wait for "ocr_service_ready"
curl http://localhost:8000/v1/health/ready
```

The image is **multi-stage** (builder + runtime), serves with **gunicorn
+ uvicorn workers** (2 workers by default, tune via `WEB_CONCURRENCY`),
runs as **non-root**, and ships with a **HEALTHCHECK** that hits
`/v1/health/ready`. Models are baked at build time so cold starts are instant.

### Option B — Local Python (for development)

```bash
cd ocr-service

python -m venv .venv
source .venv/bin/activate                # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt      # includes pytest, httpx

cp .env.example .env
# Edit .env and set INTERNAL_SECRET

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> First local run downloads PaddleOCR models (~500 MB) into `~/.paddleocr/`.
> Subsequent starts reuse the cache.

### Make targets

| Target          | What it does                                       |
|-----------------|----------------------------------------------------|
| `make install`  | Create `.venv` and install dev deps                |
| `make dev`      | Run uvicorn locally with hot-reload                |
| `make test`     | Run the full pytest suite (112 tests)              |
| `make build`    | `docker compose build`                             |
| `make up`       | `docker compose up -d`                             |
| `make down`     | `docker compose down`                              |
| `make logs`     | Tail container logs                                |
| `make health`   | Curl the readiness endpoint                        |
| `make smoke`    | End-to-end OCR test (needs `sample.jpg` + env)     |

Run `make help` to list everything.

## Endpoints

All business routes are prefixed with `/v1`. `/metrics` is Prometheus-standard.

### `GET /v1/health/live`
Liveness probe. Returns `200 {"status": "ok"}`.

### `GET /v1/health/ready`
Readiness probe. Returns `200` once both PaddleOCR engines are warm, `503` otherwise.

### `POST /v1/ocr/extract`

**Headers**
| Header | Value |
|--------|-------|
| `X-Internal-Secret` | Must match `INTERNAL_SECRET` (or `INTERNAL_SECRET_PREVIOUS` during rotation) |
| `X-Request-ID` | Optional — echoed back in the response. Generated if absent. |
| `Content-Type` | `multipart/form-data` |

Legacy header `x-api-key` matched against `LEGACY_API_KEY` is accepted during rollout (logs a deprecation warning). Remove after one release.

**Form fields**
| Field | Type | Description |
|-------|------|-------------|
| `file` | File | Image — `image/jpeg`, `image/png`, or `image/webp`. Max 10 MB. |
| `doc_type` | string | `permis` \| `cin` \| `carte_grise` \| `assurance` |

**Success response — `200 OK`**
```json
{
  "success": true,
  "data": {
    "doc_type": "permis",
    "confidence": 91.4,
    "status": "ok",
    "data": {
      "nom": "BEN ALI",
      "prenom": "Mohamed",
      "numero": "12345678",
      "date_naissance": "1990-07-22",
      "date_delivrance": "2018-03-15",
      "date_expiration": "2028-03-15",
      "categories": ["A", "B"],
      "warnings": [],
      "raw_text": "full extracted text here"
    },
    "processing_time_ms": 340
  }
}
```

`status` mapping:

| Confidence | Status |
|------------|--------|
| ≥ 78 | `ok` |
| 55 – 77 | `review` |
| < 55 | `failed` |

> `status: "failed"` is still returned as **HTTP 200** — it means OCR completed but the result is unreliable. The client must read `status` and `confidence`, not just the HTTP code.

**Error response**
```json
{
  "success": false,
  "error": {
    "code": "OCR_INVALID_DOC_TYPE",
    "message": "Invalid doc_type 'foo'",
    "details": { "allowed": ["assurance", "carte_grise", "cin", "permis"] }
  }
}
```

| Code | HTTP | When |
|---|---|---|
| `OCR_UNAUTHORIZED` | 401 | Missing or invalid `X-Internal-Secret` |
| `OCR_INVALID_DOC_TYPE` | 400 | `doc_type` not in the allowlist |
| `OCR_UNSUPPORTED_MEDIA` | 415 | `Content-Type` not jpg/png/webp |
| `OCR_IMAGE_TOO_SMALL` | 400 | Image dimensions below 200×200 |
| `OCR_PAYLOAD_TOO_LARGE` | 413 | Upload > `MAX_UPLOAD_BYTES` OR decoded > 30 MP (decompression bomb guard) |
| `OCR_ENGINE_TIMEOUT` | 504 | OCR pipeline exceeded 45 s |
| `OCR_ENGINE_FAILURE` | 502/500 | OCR engine crashed |
| `OCR_RATE_LIMITED` | 429 | Per-IP rate limit exceeded |
| `OCR_VALIDATION_ERROR` | 400 | Other input validation failure |

### `GET /metrics`
Prometheus scrape endpoint. Exposes `ocr_latency_seconds`, `ocr_confidence`, `ocr_errors_total`, `ocr_field_present_total`. No `/v1` prefix (standard Prometheus convention).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `dev` | `dev` \| `staging` \| `prod`. Non-dev refuses to start without `INTERNAL_SECRET`. |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `INTERNAL_SECRET` | _(empty in dev → auth open)_ | Shared secret with the Node backend. **Required outside dev.** |
| `INTERNAL_SECRET_PREVIOUS` | _(empty)_ | During rotation: keep the old secret here so in-flight clients keep working. Remove after rollout. |
| `LEGACY_API_KEY` | _(empty)_ | Legacy `x-api-key` header value, accepted during rollout. Remove after one release. |
| `MAX_UPLOAD_BYTES` | `10485760` (10 MB) | Upload size cap. |
| `RATE_LIMIT_PER_MINUTE` | `30` | Per-IP rate limit on `/v1/ocr/extract`. |
| `OCR_USE_ORIENTATION_DETECTION` | `true` | Set to `false` for ~30% faster OCR on already-upright admin scans. Required `true` for photos taken sideways. |

### Secret rotation

1. Deploy new value as `INTERNAL_SECRET_PREVIOUS=<old>` and `INTERNAL_SECRET=<new>`.
2. Update the Node backend to send the new secret.
3. After all callers have rolled, drop `INTERNAL_SECRET_PREVIOUS`.

Both values are matched in constant time (`secrets.compare_digest`). Using the previous secret emits a `previous_secret_used` warning log.

## Supported document types

| `doc_type` | Extracted fields |
|------------|-----------------|
| `permis` | nom, prenom, numero, date_naissance, date_delivrance, date_expiration, categories, warnings, raw_text |
| `cin` | nom, prenom, pere, numero_cin, date_naissance, gouvernorat, language_detected, raw_text |
| `carte_grise` | immatriculation, vin, marque, annee, raw_text |
| `assurance` | numero_police, date_debut, date_fin, compagnie, raw_text |

## Example with curl

```bash
curl -X POST http://localhost:8000/v1/ocr/extract \
  -H "X-Internal-Secret: $INTERNAL_SECRET" \
  -F "file=@document.jpg" \
  -F "doc_type=permis"
```

## Mobile app integration

> **The mobile app never calls this service directly.** This service has no
> CORS, no public TLS, and trusts a shared `X-Internal-Secret` — exposing it to
> phones would leak that secret and the internal network. The mobile app talks
> to the **Node backend** (`dada-api`), which is the only thing that holds the
> secret and forwards images here.

### Topology

```
┌─────────────┐   multipart upload    ┌──────────────┐   X-Internal-Secret    ┌──────────────┐
│  Mobile app │ ────────────────────► │  Node backend │ ─────────────────────► │  ocr-service │
│  (Kotlin)   │ ◄──────────────────── │   (dada-api)  │ ◄───────────────────── │  (this repo) │
└─────────────┘    poll for result    └──────────────┘    JSON extraction      └──────────────┘
     public, no secret                   holds the secret                    internal network only
```

The backend exposes an **async upload + poll** API to the phone (so the device
isn't blocked for the 3–4 s OCR takes), and translates each request into a
single synchronous call to `POST /v1/ocr/extract` on this service.

### 1. Backend → ocr-service (the only caller)

The backend forwards the user's image untouched and injects the secret:

```ts
// dada-api — forwarding to the OCR service
const form = new FormData();
form.append("file", imageBuffer, { filename, contentType });
form.append("doc_type", docType); // "permis" | "cin" | "carte_grise" | "assurance"

const res = await fetch(`${OCR_SERVICE_URL}/v1/ocr/extract`, {
  method: "POST",
  headers: { "X-Internal-Secret": process.env.INTERNAL_SECRET },
  body: form,
});
const { data } = await res.json(); // { doc_type, confidence, status, data, processing_time_ms }
```

Always branch on `data.status` (`ok` / `review` / `failed`), **not** on the HTTP
code — a `failed` extraction is still HTTP 200 (see [Endpoints](#post-v1ocrextract)).

### 2. Mobile → backend (Retrofit)

The phone uploads the image to the backend, gets a document id back, then polls
until the OCR finishes:

```kotlin
interface OcrApi {
    // Upload — returns immediately with status "queued"
    @Multipart
    @POST("upload/document/ocr")
    suspend fun upload(
        @Part file: MultipartBody.Part,
        @Part("docType") docType: RequestBody,
    ): OcrUploadResponseDto

    // Poll — status becomes "ok" | "review" | "failed" once OCR resolves
    @GET("upload/document/ocr/{id}")
    suspend fun poll(@Path("id") id: String): OcrPollResponseDto
}
```

Polling loop (simplified):

```kotlin
val uploaded = ocrApi.upload(filePart, docType.toRequestBody())
var result = ocrApi.poll(uploaded.document.id)
while (result.status == null) {            // null == still processing
    delay(1_000)
    result = ocrApi.poll(uploaded.document.id)
}

when (result.status) {
    "ok"     -> prefillForm(result.fields)            // trust the fields
    "review" -> prefillForm(result.fields, editable = true) // ask the user to confirm
    "failed" -> promptRetake()                         // confidence too low → re-shoot
}
```

The DTOs (`OcrUploadResponseDto`, `OcrPollResponseDto`, `OcrFieldsDto`) live in
the mobile repo under `data/network/dto/OcrDtos.kt`. Field names mirror this
service's response (`nom`, `prenom`, `numero_cin`, `date_naissance`,
`date_delivrance`, `categories`, …).

### Capture tips for good OCR

- Shoot in **landscape**, fill the frame with the document, avoid glare.
- Send the original JPEG; don't downscale below ~1000 px on the long edge.
- Keep `OCR_USE_ORIENTATION_DETECTION=true` (default) so sideways phone photos
  are still read correctly.

## Project structure

```
ocr-service/
├── main.py                  # FastAPI app, lifespan (PaddleOCR warmup + shutdown)
├── config.py                # Pydantic settings (cached)
├── ocr_engine.py            # Dual-engine pipeline (fr + ar), per-engine locks, global timeout
├── errors.py                # OCRError + envelope + handlers
├── schemas.py               # Pydantic response models
├── metrics.py               # Prometheus counters/histograms
├── rate_limit.py            # SlowAPI limiter (per-IP)
├── prefetch_models.py       # Docker build-time model download
├── routers/
│   ├── ocr.py               # POST /v1/ocr/extract
│   ├── health.py            # GET /v1/health/live, /v1/health/ready
│   └── metrics.py           # GET /metrics
├── middleware/
│   ├── auth.py              # X-Internal-Secret check (constant-time)
│   ├── request_id.py        # X-Request-ID propagation via ContextVar
│   └── logging.py           # JSON structured logs with request_id
├── utils/
│   ├── image_processor.py   # Decode + resize + grayscale + contrast + bomb guard
│   └── parser.py            # Regex parsers per doc_type (FR + AR + Arabic-Indic digits)
├── tests/                   # 30 parser golden tests + 12 route tests
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Tests

```bash
pytest -v
```

30 golden parser tests freeze the current behaviour — any change to `utils/parser.py` must add a failing test first.
