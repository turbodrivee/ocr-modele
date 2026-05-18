"""BUG-5 — Latin fallback in `_parse_cin` must not absorb governorate tokens
into the cardholder's `nom`/`prenom`.

BUG-7 — Latin date fallback in `_parse_cin` must never return a non-ISO string
(the previous `_to_iso_date(...) or m.group(1)` leaked raw "31/04/2025" when
the date was calendar-invalid, breaking the "all dates ISO or None" contract).
"""

from __future__ import annotations

from utils.parser import parse_fields


# ─────────────────────────── BUG-5 ──────────────────────────────────────────


def test_bug_5_governorate_not_absorbed_into_nom():
    raw = "12345678 OMRI SALAH 03-03-1985 SFAX VILLE"
    out = parse_fields(raw, "cin")
    # Nom must be just "OMRI", not "OMRI SALAH SFAX VILLE".
    assert out["nom"] == "OMRI"
    assert out["prenom"] == "SALAH"
    # Governorate still resolved via the substring match downstream.
    assert out["gouvernorat"] == "SFAX"


def test_bug_5_no_governorate_in_match_unchanged():
    raw = "12345678 TRABELSI AHMED 01-01-1990"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "TRABELSI"
    assert out["prenom"] == "AHMED"


def test_bug_5_compound_governorate_tokens_filtered():
    # "BEN AROUS" is a 2-word governorate. Both tokens must be filtered.
    raw = "12345678 KARKOUB SOFIANE 05-05-1992 BEN AROUS"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "KARKOUB"
    assert out["prenom"] == "SOFIANE"
    assert out["gouvernorat"] == "BEN AROUS"


def test_bug_5_city_modifier_ville_filtered():
    # "TUNIS VILLE" — VILLE is glued to a governorate, must be filtered too.
    raw = "12345678 BENALI MOHAMED 10-10-1980 TUNIS VILLE"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "BENALI"
    assert out["prenom"] == "MOHAMED"


def test_bug_5_only_governorate_no_name_returns_none():
    # If the OCR captured only the governorate, no name should be invented.
    raw = "12345678 03-03-1985 SFAX"
    out = parse_fields(raw, "cin")
    assert out["nom"] is None or out["nom"] != "SFAX"


# ─────────────────────────── BUG-7 ──────────────────────────────────────────


def test_bug_7_invalid_date_returns_none_not_raw_string():
    # April has 30 days — "31/04/2025" is calendar-invalid.
    raw = "12345678 TRABELSI SAMI 31/04/2025 TUNIS"
    out = parse_fields(raw, "cin")
    # Before fix : date_naissance == "31/04/2025" (non-ISO leak).
    assert out["date_naissance"] is None


def test_bug_7_valid_date_normalised_to_iso():
    raw = "12345678 BENALI AHMED 15/06/1990 TUNIS"
    out = parse_fields(raw, "cin")
    assert out["date_naissance"] == "1990-06-15"


def test_bug_7_feb_29_non_leap_returns_none():
    raw = "12345678 KARKOUB MOHAMED 29/02/2023 SFAX"
    out = parse_fields(raw, "cin")
    assert out["date_naissance"] is None


def test_bug_7_feb_29_leap_valid_iso():
    raw = "12345678 KARKOUB MOHAMED 29/02/2024 SFAX"
    out = parse_fields(raw, "cin")
    assert out["date_naissance"] == "2024-02-29"
