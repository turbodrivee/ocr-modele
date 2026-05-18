"""BUG-3 — `_parse_assurance` must not extract a date from "DAR25/10/2025" etc.

The previous pattern `(?<=[Dd])({_DATE_LOOSE})` used a 1-char lookbehind that
matched ANY word ending in D/d glued to a date, producing false positives on
common OCR artefacts like "DAR25/10/2025", "ID25/10/2025", "BAD25/10/2025".
"""

from __future__ import annotations

from utils.parser import parse_fields


# ── False-positive cases (must NOT extract a date_debut) ────────────────────


def test_bug_3_dar_prefix_no_false_positive():
    raw = "POLICE 2025/1234567 STAR DAR25/10/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    # date_debut should NOT be "25/10/2025" extracted from "DAR25/10/2025"
    assert out["date_debut"] != "25/10/2025"


def test_bug_3_id_prefix_no_false_positive():
    raw = "POLICE 2025/9999 GAT ID25/10/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    assert out["date_debut"] != "25/10/2025"


def test_bug_3_random_word_ending_d_no_false_positive():
    # "BAD25/10/2025" — the previous lookbehind matched the trailing D of BAD.
    raw = "POLICE 2025/1111 BAD25/10/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    assert out["date_debut"] != "25/10/2025"


# ── True-positive cases (must STILL extract correctly) ──────────────────────


def test_bug_3_du_with_space_valid():
    raw = "ASSURANCE N° 2025/1234567 STAR Du 25/10/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    assert out["date_debut"] == "25/10/2025"


def test_bug_3_validite_du_valid():
    raw = "ASSURANCE N° 2025/1234567 STAR Validité Du 01/01/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    assert out["date_debut"] == "01/01/2025"


def test_bug_3_glued_du_still_works():
    # OCR can glue "Du" to the date without space: "Du25/10/2025".
    # This is the original case the lookbehind was added for — must still work.
    raw = "ASSURANCE N° 2025/9999 GAT Du25/10/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    assert out["date_debut"] == "25/10/2025"


def test_bug_3_glued_d_still_works():
    # The shorter "D25/10/2025" case from the original fixture
    # (see existing test_assurance_glued_date_d_prefix).
    raw = "ASSURANCE N° 2025/9999 GAT D25/10/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    assert out["date_debut"] == "25/10/2025"
