"""BUG-1 — _to_iso_date must reject calendar-invalid dates (Feb 29 non-leap, Apr 31, etc.)
instead of returning a string that later crashes _iso_to_date() with ValueError."""

from __future__ import annotations

from utils.parser import _to_iso_date, parse_fields


def test_bug_1_february_non_leap_returns_none():
    assert _to_iso_date("29", "2", "2023") is None


def test_bug_1_february_leap_valid():
    assert _to_iso_date("29", "2", "2024") == "2024-02-29"


def test_bug_1_april_31_returns_none():
    assert _to_iso_date("31", "4", "2023") is None


def test_bug_1_june_31_returns_none():
    assert _to_iso_date("31", "6", "2020") is None


def test_bug_1_year_zero_padding_preserved():
    assert _to_iso_date("01", "01", "2020") == "2020-01-01"


def test_bug_1_year_out_of_range_returns_none():
    assert _to_iso_date("01", "01", "1800") is None
    assert _to_iso_date("01", "01", "2200") is None


def test_bug_1_parse_fields_no_crash_on_feb_29_non_leap():
    # Live-reproduced crash before fix: ValueError: day is out of range for month
    raw = "PERMIS 11111111 5. 29-02-2023 4a. 10-06-2020 4b. 09-06-2028 B"
    out = parse_fields(raw, "permis")
    assert isinstance(out, dict)
    # The bogus Feb-29-2023 date must not propagate as if it were valid.
    assert out["date_naissance"] != "2023-02-29"


def test_bug_1_arabic_indic_digits_still_validate():
    # Arabic-Indic for "29/02/2023" must also be rejected.
    assert _to_iso_date("٢٩", "٢", "٢٠٢٣") is None
    # Valid leap date in Arabic-Indic.
    assert _to_iso_date("٢٩", "٢", "٢٠٢٤") == "2024-02-29"
