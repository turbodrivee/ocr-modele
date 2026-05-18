# syntax=docker/dockerfile:1.7

# ─── Stage 1: builder ──────────────────────────────────────────────────────
# Compiles dependencies and pre-fetches the ~500 MB PaddleOCR weights into
# a separate layer so the runtime stage doesn't carry pip's build cache.
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 libglib2.0-0 libsm6 libxext6 libxrender1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# Bake the PaddleOCR weights into /models so we can copy them into the
# runtime image without a network round-trip on first start.
ENV PADDLEOCR_HOME=/models
COPY prefetch_models.py .
RUN PYTHONPATH=/install/lib/python3.11/site-packages python prefetch_models.py


# ─── Stage 2: runtime ──────────────────────────────────────────────────────
# Minimal image: only the runtime libs + installed packages + model weights.
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PADDLEOCR_HOME=/models \
    PATH=/install/bin:$PATH \
    PYTHONPATH=/install/lib/python3.11/site-packages

# Runtime-only system libs (no compilers).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libglib2.0-0 libsm6 libxext6 libxrender1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages + pre-fetched models from the builder stage.
COPY --from=builder /install /install
COPY --from=builder /models /models

WORKDIR /app
COPY . .

# Non-root user. Owns /app, /install, /models so gunicorn can read them.
RUN useradd -m -u 10001 ocr \
    && chown -R ocr:ocr /app /install /models
USER ocr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/v1/health/ready || exit 1

# Production server: gunicorn supervises N uvicorn workers.
# - workers=2: one per CPU is fine for an OCR workload (each worker
#   already runs fr+ar engines in parallel via the bulkhead executors).
# - timeout=120: an OCR request can legitimately take 10-45 s.
# Override via `docker run -e WEB_CONCURRENCY=4` if you have more CPUs.
ENV WEB_CONCURRENCY=2 \
    GUNICORN_TIMEOUT=120

CMD gunicorn main:app \
    --workers ${WEB_CONCURRENCY} \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout ${GUNICORN_TIMEOUT} \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --forwarded-allow-ips=* \
    --access-logfile - \
    --error-logfile -
