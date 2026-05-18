"""BUG-2 — _AR_LETTER must match Arabic letters only, not punctuation/tatweel.

Before the fix the range `[؀-ٟ٪-ۿ...]` included:
    - U+060C ، (comma), U+061B ؛, U+061F ؟ (punctuation)
    - U+0640 ـ (tatweel — calligraphic stretch, not a letter)
    - U+0600-U+0603 Arabic signs

Consequence: `_AR_WORD = _AR_LETTER{2,}` matched runs of punctuation as
"Arabic words", polluting the word-order fallback in `_parse_cin`.
"""

from __future__ import annotations

import re

from utils.parser import _AR_LETTER, _AR_WORD, parse_fields


_AR_LETTER_RE = re.compile(_AR_LETTER)
_AR_WORD_RE = re.compile(_AR_WORD)


# ── Negative cases (must NOT match) ─────────────────────────────────────────


def test_bug_2_arabic_comma_not_letter():
    assert _AR_LETTER_RE.fullmatch("،") is None


def test_bug_2_arabic_question_mark_not_letter():
    assert _AR_LETTER_RE.fullmatch("؟") is None


def test_bug_2_arabic_semicolon_not_letter():
    assert _AR_LETTER_RE.fullmatch("؛") is None


def test_bug_2_tatweel_not_letter():
    # U+0640 — calligraphic stretch character, never a letter.
    assert _AR_LETTER_RE.fullmatch("ـ") is None


def test_bug_2_punctuation_runs_not_ar_word():
    assert _AR_WORD_RE.fullmatch("،،،") is None
    assert _AR_WORD_RE.fullmatch("؟؟") is None
    assert _AR_WORD_RE.fullmatch("ـــ") is None


# ── Positive cases (must still match) ───────────────────────────────────────


def test_bug_2_real_letters_match():
    assert _AR_LETTER_RE.fullmatch("ع") is not None  # Ain
    assert _AR_LETTER_RE.fullmatch("ل") is not None  # Lam
    assert _AR_LETTER_RE.fullmatch("ي") is not None  # Ya
    assert _AR_LETTER_RE.fullmatch("ء") is not None  # Hamza


def test_bug_2_real_names_match_ar_word():
    assert _AR_WORD_RE.fullmatch("علي") is not None
    assert _AR_WORD_RE.fullmatch("بن") is not None
    assert _AR_WORD_RE.fullmatch("محمد") is not None
    assert _AR_WORD_RE.fullmatch("كركوب") is not None


def test_bug_2_presentation_form_letters_still_match():
    # U+FB50-U+FDFF and U+FE70-U+FEFC — common when OCR emits ligatures.
    assert _AR_LETTER_RE.fullmatch("ﻻ") is not None  # Lam-Alef ligature


# ── Regression : parser still extracts CIN names correctly ──────────────────


def test_bug_2_existing_cin_parse_unaffected():
    raw = "12345678 اللقب كركوب الإسم سهيلة 16 جويلية 2003 تونس"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "كركوب"
    assert out["prenom"] == "سهيلة"
    assert out["date_naissance"] == "2003-07-16"
    assert out["gouvernorat"] == "TUNIS"
