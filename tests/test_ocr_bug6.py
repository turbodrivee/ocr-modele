"""BUG-6 — The OCR route is `async def`, but it used to call `preprocess_image`
(sync, ~50-200 ms PIL+numpy) and `run_ocr` (sync, blocks on `Future.result()`
for up to 45 s) directly. A single in-flight request would freeze the entire
uvicorn event loop, including `/health/ready`.

Fix:
- `routers/ocr.py` calls `await asyncio.to_thread(preprocess_image, ...)`
  and `await run_ocr_async(...)`.
- `ocr_engine.run_ocr_async` schedules engine work via `loop.run_in_executor`
  and awaits with `asyncio.wait_for(..., timeout=...)`.
"""

from __future__ import annotations

import asyncio
import inspect
import time

import pytest

import ocr_engine


# ── run_ocr_async exists and is a coroutine function ────────────────────────


def test_bug_6_run_ocr_async_is_coroutine_function():
    assert inspect.iscoroutinefunction(ocr_engine.run_ocr_async)


# ── Happy path: returns the same shape as the sync version ──────────────────


class _StubEngine:
    def __init__(self, texts, scores, sleep_s: float = 0.0):
        self._texts = texts
        self._scores = scores
        self._sleep_s = sleep_s

    def predict(self, _img):
        if self._sleep_s:
            time.sleep(self._sleep_s)
        return [{"rec_texts": self._texts, "rec_scores": self._scores}]


@pytest.mark.asyncio
async def test_bug_6_happy_path_returns_text_and_confidence():
    fr = _StubEngine(["bonjour"], [0.9])
    ar = _StubEngine(["مرحبا"], [0.95])
    ocr_engine.set_engines(fr, ar)
    try:
        raw, conf, per = await ocr_engine.run_ocr_async(_dummy_img(), doc_type="permis")
        assert "bonjour" in raw and "مرحبا" in raw
        assert 0 <= conf <= 100
        assert set(per.keys()) == {"fr", "ar"}
    finally:
        ocr_engine.set_engines(None, None)


@pytest.mark.asyncio
async def test_bug_6_ar_only_doc_type_skips_fr_engine():
    fr = _StubEngine(["SHOULD_NOT_APPEAR"], [0.9])
    ar = _StubEngine(["محمد"], [0.95])
    ocr_engine.set_engines(fr, ar)
    try:
        raw, conf, per = await ocr_engine.run_ocr_async(_dummy_img(), doc_type="cin")
        assert "SHOULD_NOT_APPEAR" not in raw
        assert "محمد" in raw
        assert set(per.keys()) == {"ar"}  # fr skipped
    finally:
        ocr_engine.set_engines(None, None)


# ── Event loop stays responsive while OCR runs in the executor ──────────────
# NOTE: this test must run BEFORE the timeout test below, because the timeout
# test leaves engine threads still sleeping in the executor (PaddleOCR can't
# be interrupted) — they would steal the executor workers from any subsequent
# test until they drain on their own.


@pytest.mark.asyncio
async def test_bug_6_event_loop_not_blocked_during_ocr():
    """While `run_ocr_async` is awaiting the slow executor work, another
    coroutine on the same event loop must keep making progress."""
    slow_fr = _StubEngine(["x"], [0.9], sleep_s=0.3)
    slow_ar = _StubEngine(["y"], [0.9], sleep_s=0.3)
    ocr_engine.set_engines(slow_fr, slow_ar)

    ticks = []

    async def heartbeat():
        # If the event loop were blocked, sleep(0.05) wouldn't return on time.
        for _ in range(5):
            await asyncio.sleep(0.05)
            ticks.append(time.perf_counter())

    try:
        ocr_task = asyncio.create_task(
            ocr_engine.run_ocr_async(_dummy_img(), doc_type="permis", timeout=5.0)
        )
        heart_task = asyncio.create_task(heartbeat())
        await asyncio.gather(ocr_task, heart_task)
    finally:
        ocr_engine.set_engines(None, None)

    # Heartbeat ran all 5 ticks during the ~0.3 s OCR — proof the loop wasn't frozen.
    assert len(ticks) == 5


# ── Timeout: a slow engine must not stall the caller beyond the deadline ────
# Runs last because the engine threads keep sleeping after the timeout fires.


@pytest.mark.asyncio
async def test_bug_6_run_ocr_async_timeout_raises_quickly():
    slow_fr = _StubEngine(["x"], [0.9], sleep_s=0.8)
    slow_ar = _StubEngine(["y"], [0.9], sleep_s=0.8)
    ocr_engine.set_engines(slow_fr, slow_ar)
    try:
        t0 = time.perf_counter()
        with pytest.raises(TimeoutError):
            await ocr_engine.run_ocr_async(_dummy_img(), doc_type="permis", timeout=0.2)
        elapsed = time.perf_counter() - t0
        # Must abort within ~0.5 s, not wait for the full engine sleep.
        assert elapsed < 0.6, f"timeout took {elapsed:.2f}s (expected < 0.6s)"
    finally:
        ocr_engine.set_engines(None, None)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _dummy_img():
    import numpy as np

    return np.full((50, 50, 3), 255, dtype=np.uint8)
