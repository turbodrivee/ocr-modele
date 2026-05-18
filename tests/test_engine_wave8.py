"""Wave 8 — `PaddleEngine` Protocol + bulkhead executors per language.

- `_ocr_fr`/`_ocr_ar` are now typed `PaddleEngine | None` (was `Any`).
- `_executor` (single, max_workers=2) was split into `_executor_fr` and
  `_executor_ar` (each max_workers=1). A wedged FR engine no longer steals
  the only worker from AR — true bulkhead between language pipelines.
- `shutdown_executor()` was renamed `shutdown_engines()` and drains both.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

import ocr_engine
from ocr_engine import PaddleEngine


class _Stub:
    """Minimal engine matching the PaddleEngine Protocol."""

    def __init__(self, texts=("hello",), scores=(0.9,), sleep_s: float = 0.0) -> None:
        self._texts = list(texts)
        self._scores = list(scores)
        self._sleep_s = sleep_s

    def predict(self, _img: np.ndarray) -> list[dict]:
        if self._sleep_s:
            time.sleep(self._sleep_s)
        return [{"rec_texts": self._texts, "rec_scores": self._scores}]


def _img() -> np.ndarray:
    return np.full((50, 50, 3), 255, dtype=np.uint8)


# ── Protocol ────────────────────────────────────────────────────────────────


def test_wave8_paddle_engine_protocol_runtime_checkable():
    # A class implementing `predict(img) -> list[dict]` must pass isinstance.
    assert isinstance(_Stub(), PaddleEngine)


def test_wave8_arbitrary_object_does_not_match_protocol():
    class NoPredict:
        pass

    assert not isinstance(NoPredict(), PaddleEngine)


# ── Bulkhead: two distinct executors ────────────────────────────────────────


def test_wave8_two_executors_exist_and_are_distinct():
    assert isinstance(ocr_engine._executor_fr, ThreadPoolExecutor)
    assert isinstance(ocr_engine._executor_ar, ThreadPoolExecutor)
    assert ocr_engine._executor_fr is not ocr_engine._executor_ar


def test_wave8_executor_old_name_removed():
    # Belt-and-braces: the old `_executor` global must be gone — anyone
    # still importing it would silently submit work nowhere.
    assert not hasattr(ocr_engine, "_executor")


# ── Bulkhead behaviour: slow FR does not block AR-only doc_type ─────────────


@pytest.mark.asyncio
async def test_wave8_bulkhead_fr_slow_does_not_block_ar():
    # Saturate the FR executor with a long-running task.
    blocked = ocr_engine._executor_fr.submit(time.sleep, 1.5)

    ocr_engine.set_engines(_Stub(["fr"], [0.9]), _Stub(["محمد"], [0.9]))
    try:
        # CIN is AR-only — must not touch the FR executor at all.
        t0 = time.perf_counter()
        raw, _, per = await ocr_engine.run_ocr_async(_img(), doc_type="cin", timeout=2.0)
        elapsed = time.perf_counter() - t0
        assert "محمد" in raw
        assert set(per.keys()) == {"ar"}
        # Must complete well before the 1.5 s FR sleep — proof of bulkhead.
        assert elapsed < 0.5, f"AR call took {elapsed:.2f}s — FR blocked it?"
    finally:
        ocr_engine.set_engines(None, None)
        # Drain the blocking task before the next test starts.
        blocked.result(timeout=3.0)


# ── shutdown_engines drains both executors ──────────────────────────────────


def test_wave8_shutdown_engines_function_exists():
    assert callable(getattr(ocr_engine, "shutdown_engines", None))
    # Old name removed: callers must migrate.
    assert not hasattr(ocr_engine, "shutdown_executor")


def test_wave8_shutdown_engines_marks_both_shutdown(monkeypatch):
    # Build a throwaway module state so we don't kill the executors
    # that the rest of the test suite still uses.
    fake_fr = ThreadPoolExecutor(max_workers=1)
    fake_ar = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(ocr_engine, "_executor_fr", fake_fr)
    monkeypatch.setattr(ocr_engine, "_executor_ar", fake_ar)

    assert fake_fr._shutdown is False
    assert fake_ar._shutdown is False

    ocr_engine.shutdown_engines()

    assert fake_fr._shutdown is True
    assert fake_ar._shutdown is True


# ── set_engines back-compat ─────────────────────────────────────────────────


def test_wave8_set_engines_accepts_none():
    # Conftest teardown calls `set_engines(None, None)` — must not raise.
    ocr_engine.set_engines(None, None)
    assert ocr_engine._ocr_fr is None
    assert ocr_engine._ocr_ar is None
