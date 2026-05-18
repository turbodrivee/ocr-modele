"""OCR engine singletons + the dual-language extraction pipeline.

Holds the two PaddleOCR instances (French + Arabic) and exposes a single
`run_ocr(img_array)` entry point. Singletons are loaded by `main.lifespan`
and read here via accessor functions so tests can monkeypatch them.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class PaddleEngine(Protocol):
    """Structural interface for a PaddleOCR-compatible engine.

    Anything we plug in (real `paddleocr.PaddleOCR`, test stub, future
    Tesseract adapter) must expose `predict(img) -> list[dict]`. The list
    contains a single dict with `rec_texts` and `rec_scores` keys.
    """

    def predict(self, img: np.ndarray) -> list[dict[str, Any]]: ...


logger = logging.getLogger(__name__)

# Hard ceiling for one OCR request. A healthy run is ~5–8 s; anything past
# this is a stuck PaddleOCR call (we've seen 3-min hangs on rare images).
# Failing fast is much better than letting the upstream proxy time out.
# Applied as a single global deadline across all futures, not per-future,
# so the worst case stays at 45 s end-to-end even when fr + ar run together.
_OCR_REQUEST_TIMEOUT_SECONDS = 45

_ocr_fr: PaddleEngine | None = None
_ocr_ar: PaddleEngine | None = None

# PaddleOCR's `predict()` is NOT documented as thread-safe on a single
# instance. Two concurrent calls into the same engine could corrupt
# internal state (intermediate tensors, paddle-runtime caches). Serialise
# per engine with a lock — kept even though each executor now has
# `max_workers=1`, so a future bump to >1 worker still stays safe.
_ocr_fr_lock = threading.Lock()
_ocr_ar_lock = threading.Lock()

# Bulkhead: one executor PER engine, each with a single worker. If the FR
# engine wedges on a pathological image, AR requests still flow through
# their own executor. Total parallelism stays the same as the previous
# single `max_workers=2` pool — but isolation is now real.
_executor_fr = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr-fr")
_executor_ar = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr-ar")


def set_engines(fr: PaddleEngine | None, ar: PaddleEngine | None) -> None:
    global _ocr_fr, _ocr_ar
    _ocr_fr = fr
    _ocr_ar = ar


def shutdown_engines() -> None:
    """Drain in-flight OCR work on app shutdown (both executors)."""
    _executor_fr.shutdown(wait=True, cancel_futures=False)
    _executor_ar.shutdown(wait=True, cancel_futures=False)


def engines_ready() -> bool:
    return _ocr_fr is not None and _ocr_ar is not None


def _extract_texts_scores(result: list) -> tuple[list[str], list[float]]:
    if not result:
        return [], []
    res = result[0]
    texts = res.get("rec_texts", []) or []
    scores = res.get("rec_scores", []) or []
    return list(texts), [float(s) for s in scores]


def _compute_confidence(texts: list[str], scores: list[float]) -> float:
    total_weight = 0
    weighted_sum = 0.0
    for text, score in zip(texts, scores):
        w = max(len(text), 1)
        weighted_sum += score * w
        total_weight += w
    if total_weight == 0:
        return 0.0
    return round((weighted_sum / total_weight) * 100, 2)


def confidence_to_status(confidence: float) -> str:
    if confidence >= 78:
        return "ok"
    if confidence >= 55:
        return "review"
    return "failed"


def _run_one(
    label: str,
    engine: PaddleEngine,
    lock: threading.Lock,
    img_array: np.ndarray,
) -> tuple[str, list[str], list[float], float]:
    try:
        with lock:
            result = engine.predict(img_array)
        texts, scores = _extract_texts_scores(result)
        return label, texts, scores, _compute_confidence(texts, scores)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ocr_engine_failed", extra={"engine": label, "error": str(exc)})
        return label, [], [], 0.0


_AR_ONLY_DOC_TYPES = frozenset({"cin"})


def run_ocr(
    img_array: np.ndarray,
    doc_type: str | None = None,
) -> tuple[str, float, dict[str, float]]:
    """Run the OCR engines on the image.

    By default both engines (fr + ar) run in parallel. For doc types listed
    in `_AR_ONLY_DOC_TYPES` (CIN — purely Arabic text + Latin digits the
    Arabic engine handles fine), only the Arabic engine runs, halving
    latency without measurable accuracy loss on those fields.
    """
    if not engines_ready():
        raise RuntimeError("OCR engines not loaded")

    if doc_type in _AR_ONLY_DOC_TYPES:
        futures = [_executor_ar.submit(_run_one, "ar", _ocr_ar, _ocr_ar_lock, img_array)]
    else:
        futures = [
            _executor_fr.submit(_run_one, "fr", _ocr_fr, _ocr_fr_lock, img_array),
            _executor_ar.submit(_run_one, "ar", _ocr_ar, _ocr_ar_lock, img_array),
        ]

    # Global deadline across all futures — not per-future. With 2 engines
    # this caps total wait at _OCR_REQUEST_TIMEOUT_SECONDS instead of 2x.
    deadline = time.monotonic() + _OCR_REQUEST_TIMEOUT_SECONDS
    all_texts: list[str] = []
    all_scores: list[float] = []
    per_engine: dict[str, float] = {}
    for fut in futures:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            label, texts, scores, conf = fut.result(timeout=remaining)
        except FuturesTimeoutError as exc:
            logger.warning("ocr_engine_timeout", extra={"timeout_s": _OCR_REQUEST_TIMEOUT_SECONDS})
            for pending in futures:
                pending.cancel()
            raise TimeoutError(f"OCR engine exceeded {_OCR_REQUEST_TIMEOUT_SECONDS}s") from exc
        per_engine[label] = conf
        all_texts.extend(texts)
        all_scores.extend(scores)

    raw_text = " ".join(t for t in all_texts if t.strip())
    confidence = _compute_confidence(all_texts, all_scores)
    return raw_text, confidence, per_engine


async def run_ocr_async(
    img_array: np.ndarray,
    doc_type: str | None = None,
    timeout: float | None = None,
) -> tuple[str, float, dict[str, float]]:
    """Async counterpart to `run_ocr`.

    The HTTP route is `async def`, so calling the sync `run_ocr` (which blocks
    on `Future.result()` for up to 45 s) would freeze the entire uvicorn event
    loop — including `/health/ready` — while a single request is in flight.
    Here we schedule the per-engine work via `loop.run_in_executor` and await
    them with `asyncio.gather`, so the event loop stays responsive.

    `timeout` defaults to `_OCR_REQUEST_TIMEOUT_SECONDS` and is enforced as a
    single global deadline across all engines (not per-engine).
    """
    if not engines_ready():
        raise RuntimeError("OCR engines not loaded")

    deadline = timeout if timeout is not None else _OCR_REQUEST_TIMEOUT_SECONDS
    loop = asyncio.get_running_loop()

    if doc_type in _AR_ONLY_DOC_TYPES:
        coros = [
            loop.run_in_executor(_executor_ar, _run_one, "ar", _ocr_ar, _ocr_ar_lock, img_array),
        ]
    else:
        coros = [
            loop.run_in_executor(_executor_fr, _run_one, "fr", _ocr_fr, _ocr_fr_lock, img_array),
            loop.run_in_executor(_executor_ar, _run_one, "ar", _ocr_ar, _ocr_ar_lock, img_array),
        ]

    try:
        results = await asyncio.wait_for(asyncio.gather(*coros), timeout=deadline)
    except asyncio.TimeoutError as exc:
        logger.warning("ocr_engine_timeout", extra={"timeout_s": deadline})
        # Best-effort cancellation. The underlying executor threads keep
        # running (PaddleOCR doesn't expose interruption), but we no longer
        # await them so the request returns immediately.
        for c in coros:
            c.cancel()
        raise TimeoutError(f"OCR engine exceeded {deadline}s") from exc

    all_texts: list[str] = []
    all_scores: list[float] = []
    per_engine: dict[str, float] = {}
    for label, texts, scores, conf in results:
        per_engine[label] = conf
        all_texts.extend(texts)
        all_scores.extend(scores)

    raw_text = " ".join(t for t in all_texts if t.strip())
    confidence = _compute_confidence(all_texts, all_scores)
    return raw_text, confidence, per_engine
