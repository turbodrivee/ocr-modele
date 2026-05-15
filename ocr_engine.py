"""OCR engine singletons + the dual-language extraction pipeline.

Holds the two PaddleOCR instances (French + Arabic) and exposes a single
`run_ocr(img_array)` entry point. Singletons are loaded by `main.lifespan`
and read here via accessor functions so tests can monkeypatch them.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np


logger = logging.getLogger(__name__)

_ocr_fr: Any = None
_ocr_ar: Any = None

# Two workers — one per language pipeline. PaddleOCR releases the GIL during
# native inference, so both threads run on separate cores.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr")


def set_engines(fr: Any, ar: Any) -> None:
    global _ocr_fr, _ocr_ar
    _ocr_fr = fr
    _ocr_ar = ar


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


def _run_one(label: str, engine: Any, img_array: np.ndarray) -> tuple[str, list[str], list[float], float]:
    try:
        result = engine.predict(img_array)
        texts, scores = _extract_texts_scores(result)
        return label, texts, scores, _compute_confidence(texts, scores)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ocr_engine_failed", extra={"engine": label, "error": str(exc)})
        return label, [], [], 0.0


def run_ocr(img_array: np.ndarray) -> tuple[str, float, dict[str, float]]:
    """Run both engines on the image. Returns (raw_text, confidence, per_engine_confidence)."""
    if not engines_ready():
        raise RuntimeError("OCR engines not loaded")

    futures = [
        _executor.submit(_run_one, "fr", _ocr_fr, img_array),
        _executor.submit(_run_one, "ar", _ocr_ar, img_array),
    ]

    all_texts: list[str] = []
    all_scores: list[float] = []
    per_engine: dict[str, float] = {}
    for fut in futures:
        label, texts, scores, conf = fut.result()
        per_engine[label] = conf
        all_texts.extend(texts)
        all_scores.extend(scores)

    raw_text = " ".join(t for t in all_texts if t.strip())
    confidence = _compute_confidence(all_texts, all_scores)
    return raw_text, confidence, per_engine
