"""Test fixtures.

Monkeypatches the PaddleOCR engines so unit tests run in milliseconds
without loading the ~500 MB real models.
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest


# Ensure config defaults before importing the app.
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("INTERNAL_SECRET", "test-secret")
os.environ.setdefault("LOG_LEVEL", "WARNING")


class StubEngine:
    """Mimics PaddleOCR's `predict()` returning canned `rec_texts` / `rec_scores`."""

    def __init__(self, texts: list[str], scores: list[float]) -> None:
        self._texts = texts
        self._scores = scores

    def predict(self, _img) -> list[dict]:
        return [{"rec_texts": self._texts, "rec_scores": self._scores}]


def _stub_for(doc_type: str) -> tuple[list[str], list[float]]:
    samples = {
        "permis": (
            [
                "REPUBLIQUE TUNISIENNE",
                "PERMIS DE CONDUIRE",
                "1. 23/ 238943",
                "3. KARKOUB",
                "4. Mohamed",
                "5. 12-05-1990",
                "10. 30-12-2030",
                "B",
            ],
            [0.95, 0.93, 0.91, 0.92, 0.88, 0.90, 0.89, 0.94],
        ),
        "cin": (
            ["REPUBLIQUE TUNISIENNE", "CARTE D'IDENTITE", "12345678", "BEN ALI", "AHMED", "01/01/1990", "TUNIS"],
            [0.96, 0.93, 0.95, 0.91, 0.92, 0.89, 0.90],
        ),
        "carte_grise": (
            ["CARTE GRISE", "TOYOTA", "123 TU 4567", "JTDBT923771012345", "2018"],
            [0.94, 0.92, 0.96, 0.88, 0.90],
        ),
        "assurance": (
            ["ASSURANCE AUTO", "N° 2025/1234567", "STAR", "Validité Du 01/01/2025", "Au 31/12/2025"],
            [0.93, 0.95, 0.94, 0.91, 0.90],
        ),
    }
    return samples.get(doc_type, ([], []))


@pytest.fixture
def install_stub_engines(monkeypatch: pytest.MonkeyPatch) -> Iterator[callable]:
    """Returns a setter; call it with a doc_type to install matching stubs."""
    import ocr_engine

    def _install(doc_type: str = "permis") -> None:
        texts, scores = _stub_for(doc_type)
        # CIN runs only the Arabic engine in production (see
        # ocr_engine._AR_ONLY_DOC_TYPES), so its stub data must live on the
        # AR slot. Other doc types run both engines in parallel; we route
        # the canned data through the FR slot and leave AR empty.
        if doc_type == "cin":
            ocr_engine.set_engines(StubEngine([], []), StubEngine(texts, scores))
        else:
            ocr_engine.set_engines(StubEngine(texts, scores), StubEngine([], []))

    yield _install
    ocr_engine.set_engines(None, None)


@pytest.fixture
def app_no_lifespan(monkeypatch: pytest.MonkeyPatch):
    """Import the app but bypass the real lifespan (don't load PaddleOCR)."""
    from contextlib import asynccontextmanager

    import main as main_module

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    monkeypatch.setattr(main_module, "lifespan", noop_lifespan)
    main_module.app.router.lifespan_context = noop_lifespan
    return main_module.app


@pytest.fixture
def client(app_no_lifespan, install_stub_engines):
    from fastapi.testclient import TestClient

    install_stub_engines("permis")
    with TestClient(app_no_lifespan) as c:
        yield c
