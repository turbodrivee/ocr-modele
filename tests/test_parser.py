"""Golden tests for the regex parsers.

These freeze the current behaviour. ANY change to utils/parser.py must
first add a failing test here; never edit a regex without a test pinning
the new behaviour.
"""

from __future__ import annotations

import re
from datetime import date

from utils.parser import parse_fields


# ───────────────────────── PERMIS ─────────────────────────

def test_permis_full():
    raw = (
        "REPUBLIQUE TUNISIENNE PERMIS DE CONDUIRE "
        "1. 23/ 238943 3. KARKOUB 4. Mohamed 5. 12-05-1990 8. B 4a. 10-06-2018"
    )
    out = parse_fields(raw, "permis")
    assert out["numero"] == "23238943"
    assert out["nom"] == "KARKOUB"
    assert out["prenom"] == "Mohamed"
    assert out["date_naissance"] == "1990-05-12"
    assert out["date_delivrance"] == "2018-06-10"
    assert out["date_expiration"] is None
    assert out["categories"] == ["B"]


def test_permis_numero_8_digits_plain():
    raw = "PERMIS 87654321 3. DUPONT 5. 01-01-1980"
    out = parse_fields(raw, "permis")
    assert out["numero"] == "87654321"


def test_permis_numero_ignores_cin_before_field_1():
    # Tunisian permis prints the holder's CIN in the header; field 1. is the
    # actual license number. A naive first-8-digit scan returns the CIN.
    raw = (
        "REPUBLIQUE TUNISIENNE 12345678 PERMIS DE CONDUIRE "
        "1. 23/ 238943 3. KARKOUB 4. Mohamed 5. 12-05-1990 "
        "4a. 10-06-2018 4b. 30-12-2030 B"
    )
    out = parse_fields(raw, "permis")
    assert out["numero"] == "23238943"
    assert out["numero"] != "12345678"


def test_permis_prenom_via_t_dot_misread():
    raw = "PERMIS 12345678 3. KARKOUB t.mohamed 5. 12-05-1990"
    out = parse_fields(raw, "permis")
    assert out["nom"] == "KARKOUB"
    assert (out["prenom"] or "").lower() == "mohamed"


def test_permis_multiple_categories_sorted_unique():
    raw = "PERMIS 12345678 8. B C A 5. 01-01-1990"
    out = parse_fields(raw, "permis")
    assert out["categories"] == ["A", "B", "C"]


def test_permis_missing_fields_return_none():
    raw = "completely unrelated text without any markers"
    out = parse_fields(raw, "permis")
    assert out["numero"] is None
    assert out["nom"] is None
    assert out["categories"] == []


# ─────────────────── PERMIS: three-date disambiguation ───────────────────

def test_permis_three_distinct_dates_eu_markers():
    # EU markers 5./4a. on recto; global expiry (4b) is applied on verso scan.
    raw = (
        "PERMIS 11223344 3. BENALI 4. Sami "
        "5. 14-02-1988 4a. 10-06-2018 4b. 09-06-2028 8. B"
    )
    out = parse_fields(raw, "permis")
    assert out["date_naissance"] == "1988-02-14"
    assert out["date_delivrance"] == "2018-06-10"
    assert out["date_expiration"] is None
    assert out["categories"] == ["B"]


def test_permis_french_labels():
    raw = (
        "PERMIS 22334455 KARKOUB Mohamed "
        "Né le 12/05/1990 Délivré le 03/04/2022 Valable jusqu'au 02/04/2032 8. B"
    )
    out = parse_fields(raw, "permis")
    assert out["date_naissance"] == "1990-05-12"
    assert out["date_delivrance"] == "2022-04-03"
    assert out["date_expiration"] is None


def test_permis_arabic_labels():
    # Arabic-Indic digit dates after Arabic labels.
    raw = (
        "11223344 "
        "تاريخ الولادة ١٢/٠٥/١٩٩٠ "
        "تاريخ التسليم ٠٣/٠٤/٢٠٢٢ "
        "صالح إلى ٠٢/٠٤/٢٠٣٢ 8. B"
    )
    out = parse_fields(raw, "permis")
    assert out["date_naissance"] == "1990-05-12"
    assert out["date_delivrance"] == "2022-04-03"
    assert out["date_expiration"] is None


def test_permis_chronological_fallback_three_dates():
    # EU labels pin naissance + delivrance; expiry is not guessed on recto.
    raw = (
        "PERMIS 33445566 8. B "
        "5. 05/06/1985 4a. 12/03/2020 4b. 30/12/2030"
    )
    out = parse_fields(raw, "permis")
    assert out["date_naissance"] == "1985-06-05"
    assert out["date_delivrance"] == "2020-03-12"
    assert out["date_expiration"] is None


def test_permis_only_two_dates_warns():
    # Recto never guesses a global expiration date.
    raw = "PERMIS 44556677 8. B 5. 01/01/1985 30/12/2030"
    out = parse_fields(raw, "permis")
    assert out["date_naissance"] == "1985-01-01"
    assert out["date_expiration"] is None


def test_permis_expired_license_warning():
    # Past global expiry on verso — keep value and warn.
    raw = "10. 09-06-2020\nA 10-06-2010\nB 10-06-2010"
    out = parse_fields(raw, "permis")
    assert out["date_expiration"] == "2020-06-09"
    assert "date_expiration_in_past" in out["warnings"]


def test_permis_naissance_too_recent_warning():
    # Synthesise a birth date < 16 years ago (today is 2026-05-15 in this env).
    recent_year = date.today().year - 10
    raw = (
        f"PERMIS 66778899 5. 01-01-{recent_year} "
        f"4a. 10-06-2024 4b. 09-06-2034 B"
    )
    out = parse_fields(raw, "permis")
    assert out["date_naissance"] == f"{recent_year}-01-01"
    assert "date_naissance_too_recent" in out["warnings"]


def test_permis_iso_format_consistency():
    raw = (
        "PERMIS 77889900 3. BENALI 4. Sami "
        "5. 14-02-1988 4a. 10-06-2018 8. B"
    )
    out = parse_fields(raw, "permis")
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for key in ("date_naissance", "date_delivrance"):
        assert iso_re.match(out[key]), f"{key}={out[key]} not ISO"


def test_permis_no_dates_detected_warning():
    raw = "PERMIS 12345678 B"
    out = parse_fields(raw, "permis")
    assert out["date_naissance"] is None
    assert out["date_delivrance"] is None
    assert out["date_expiration"] is None
    assert "no_dates_detected" in out["warnings"]


def test_permis_benali_does_not_add_false_b_category():
    raw = (
        "PERMIS 11223344 3. BENALI 4. Sami "
        "5. 14-02-1988 4a. 10-06-2018 4b. 09-06-2028"
    )
    out = parse_fields(raw, "permis")
    assert out["categories"] == []


def test_permis_verso_expiration_and_category_grid():
    # Back side only: field 10 + per-category delivery dates (no recto header).
    raw = (
        "Délivrance par catégorie\n"
        "10. 15-08-2032\n"
        "A 10-06-2018\n"
        "B 10-06-2018\n"
        "C 10-06-2018\n"
    )
    out = parse_fields(raw, "permis")
    assert out["numero"] is None
    assert out["date_expiration"] == "2032-08-15"
    assert out["categories"] == ["A", "B", "C"]


def test_permis_verso_ignores_grid_dates_for_global_expiry():
    # Global expiry is field 10, not the per-category delivery dates in the grid.
    raw = (
        "10. 30-12-2030\n"
        "A 10-06-2018\n"
        "B 23-09-2022\n"
    )
    out = parse_fields(raw, "permis")
    assert out["date_expiration"] == "2030-12-30"
    assert out["categories"] == ["A", "B"]


def test_permis_recto_does_not_guess_expiration():
    raw = (
        "REPUBLIQUE TUNISIENNE PERMIS DE CONDUIRE "
        "1. 23/ 238943 3. KARKOUB 4. Mohamed 5. 12-05-1990 4a. 23-09-2022"
    )
    out = parse_fields(raw, "permis")
    assert out["date_delivrance"] == "2022-09-23"
    assert out["date_expiration"] is None


def test_permis_delivre_label_does_not_add_d_category():
    raw = (
        "PERMIS 22334455 KARKOUB Mohamed "
        "Né le 12/05/1990 Délivré le 03/04/2022 Valable jusqu'au 02/04/2032 8. B"
    )
    out = parse_fields(raw, "permis")
    assert out["categories"] == ["B"]


# ─────────────────────────── CIN (Latin) ──────────────────

def test_cin_full():
    raw = "CARTE D'IDENTITE 12345678 BEN ALI AHMED 01/01/1990 TUNIS"
    out = parse_fields(raw, "cin")
    assert out["numero_cin"] == "12345678"
    # Dates now normalise to ISO YYYY-MM-DD across all CIN paths.
    assert out["date_naissance"] == "1990-01-01"
    assert out["gouvernorat"] == "TUNIS"
    assert out["language_detected"] == "fr"


def test_cin_governorate_match_within_text():
    raw = "12345678 OMRI SALAH 03-03-1985 SFAX VILLE"
    out = parse_fields(raw, "cin")
    assert out["gouvernorat"] == "SFAX"


def test_cin_missing_returns_none():
    out = parse_fields("hello world", "cin")
    assert out["numero_cin"] is None
    assert out["gouvernorat"] is None


# ─────────────────────── CIN (Arabic) ──────────────────────

def test_cin_arabic_full():
    raw = "12345678 اللقب بن علي الإسم محمد 16 سبتمبر 1990 تونس"
    out = parse_fields(raw, "cin")
    assert out["numero_cin"] == "12345678"
    assert out["nom"] == "بن علي"
    assert out["prenom"] == "محمد"
    assert out["date_naissance"] == "1990-09-16"
    assert out["gouvernorat"] == "TUNIS"
    assert out["language_detected"] == "ar"


def test_cin_arabic_indic_digits_date():
    raw = "12345678 اللقب الترابلسي الإسم سامي ١٢/٠٥/١٩٩٠ صفاقس"
    out = parse_fields(raw, "cin")
    assert out["date_naissance"] == "1990-05-12"
    assert out["gouvernorat"] == "SFAX"
    assert out["nom"] == "الترابلسي"
    assert out["prenom"] == "سامي"


def test_cin_arabic_no_labels_uses_word_order():
    raw = "87654321 العمري سامي ٠١/٠١/١٩٨٥ سوسة"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "العمري"
    assert out["prenom"] == "سامي"
    assert out["gouvernorat"] == "SOUSSE"


def test_cin_recto_header_misread_doubled_letter_skipped():
    # Real-world failure (May 2026): PaddleOCR emitted "التعرريف"
    # (extra ر) instead of "التعريف" for the header word. Exact-match
    # stop-words missed it, so it leaked into `nom` and pushed the real
    # name out of the candidate pool. Pattern-match on the root must
    # still skip the misread.
    raw = (
        "الجمهورية التونسية بطاقة التعرريف الوطنية 14523154 "
        "كركوب سهيلة 16 جويلية 2003 تونس"
    )
    out = parse_fields(raw, "cin")
    assert out["nom"] == "كركوب"
    assert out["prenom"] == "سهيلة"
    assert out["numero_cin"] == "14523154"
    assert out["date_naissance"] == "2003-07-16"
    assert out["gouvernorat"] == "TUNIS"


def test_cin_recto_header_words_skipped_in_fallback():
    # Real-world failure: PaddleOCR captured the printed header
    # "الجمهورية التونسية بطاقة التعريف الوطنية" but missed the
    # field labels (اللقب / الاسم), so the word-order fallback
    # was promoting header tokens into nom/prenom. The header
    # must be filtered so the cardholder's actual names win.
    raw = (
        "الجمهورية التونسية بطاقة التعريف الوطنية 14523154 "
        "كركوب سهيلة بن علي 16 جويلية 2003 تونس"
    )
    out = parse_fields(raw, "cin")
    assert out["nom"] == "كركوب"
    assert out["prenom"] == "سهيلة"
    assert out["pere"] == "علي"
    assert out["numero_cin"] == "14523154"
    assert out["date_naissance"] == "2003-07-16"
    assert out["gouvernorat"] == "TUNIS"


def test_cin_mixed_french_arabic_keeps_french_for_governorate():
    raw = "12345678 اللقب بن علي الإسم محمد 16/09/1990 TUNIS"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "بن علي"
    assert out["prenom"] == "محمد"
    assert out["gouvernorat"] == "TUNIS"
    assert out["date_naissance"] == "1990-09-16"
    assert out["language_detected"] == "mixed"


def test_cin_governorate_without_alif_lam():
    raw = "12345678 اللقب البوسالمي الإسم نور 01/01/1990 قيروان"
    out = parse_fields(raw, "cin")
    assert out["gouvernorat"] == "KAIROUAN"


def test_cin_arabic_month_tunisian_dialect():
    # Tunisian uses أفريل / جويلية / أوت instead of أبريل / يوليو / أغسطس
    raw = "12345678 اللقب الفقيه الإسم رنا 03 جويلية 1995 المنستير"
    out = parse_fields(raw, "cin")
    assert out["date_naissance"] == "1995-07-03"
    assert out["gouvernorat"] == "MONASTIR"


def test_cin_arabic_8_digit_in_arabic_indic():
    # CIN number printed in Arabic-Indic digits should still resolve.
    raw = "١٢٣٤٥٦٧٨ اللقب الزواري الإسم ياسين 01/01/1990 صفاقس"
    out = parse_fields(raw, "cin")
    assert out["numero_cin"] == "12345678"


# ──────────────── CIN: lineage marker (بن / بنت) ────────────────

def test_cin_recto_real_ocr_text():
    # Exact raw_text from a real Tunisian CIN extracted with PaddleOCR.
    # PaddleOCR concatenated text-lines out of canonical order: the cardholder's
    # given name (سهيلة) ended up between اللقب-value and the الاسم label,
    # and the date appears as `جويلية ... 2003 16` (month, year, day).
    raw = (
        " gag S 14523154 1 ADI 1c 5 DIEL 2003 16 46 "
        "الجمهورية التونسية بطاقة التحريف الوطنية 14523154 "
        "اللقب كركوب سهيلة الاسم علي بن سهيل بنت جويلية ناعخ الولادة "
        "2003 16 مكاتها تونس"
    )
    out = parse_fields(raw, "cin")
    assert out["numero_cin"] == "14523154"
    assert out["nom"] == "كركوب"
    assert out["prenom"] == "سهيلة"
    assert out["pere"] == "علي"
    assert out["date_naissance"] == "2003-07-16"
    assert out["gouvernorat"] == "TUNIS"


def test_cin_canonical_ben_chain_extracts_pere():
    # Canonical layout: name appears directly before بن in the stream.
    raw = "12345678 اللقب كركوب الاسم سهيلة بن علي 16 جويلية 2003 تونس"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "كركوب"
    assert out["prenom"] == "سهيلة"
    assert out["pere"] == "علي"
    assert out["date_naissance"] == "2003-07-16"


def test_cin_bint_marker_for_female():
    # بنت ("daughter of") is the female-gender lineage marker.
    raw = "12345678 اللقب الزواري الاسم فاطمة بنت محمد 05 أوت 1995 سوسة"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "الزواري"
    assert out["prenom"] == "فاطمة"
    assert out["pere"] == "محمد"
    assert out["date_naissance"] == "1995-08-05"
    assert out["gouvernorat"] == "SOUSSE"


def test_cin_no_lineage_marker_pere_is_none():
    raw = "12345678 اللقب العمري الاسم سامي 01/01/1990 صفاقس"
    out = parse_fields(raw, "cin")
    assert out["nom"] == "العمري"
    assert out["prenom"] == "سامي"
    assert out["pere"] is None
    assert out["date_naissance"] == "1990-01-01"


def test_cin_arabic_full_pere_field_is_none():
    # Pre-existing fixture: nom is the compound surname "بن علي"; the
    # marker inside the surname must NOT be treated as a lineage connector,
    # so pere should remain None.
    raw = "12345678 اللقب بن علي الإسم محمد 16 سبتمبر 1990 تونس"
    out = parse_fields(raw, "cin")
    assert out["pere"] is None


def test_cin_recto_date_delivrance_label():
    raw = (
        "12345678 اللقب كركوب الاسم سهيلة 16 جويلية 2003 تونس "
        "صادرة بتونس في 15 مارس 2024"
    )
    out = parse_fields(raw, "cin")
    assert out["date_naissance"] == "2003-07-16"
    assert out["date_delivrance"] == "2024-03-15"


def test_cin_verso_date_delivrance_from_arabic_month_year():
    # Verso OCR often has only "2024 جوان" near a misread "صادرة في" label.
    raw = "20878141 اريانة الام فلانة 2024 جوان ترض في"
    out = parse_fields(raw, "cin")
    assert out["date_delivrance"] == "2024-06-01"
    assert out["date_naissance"] is None


def test_cin_verso_scattered_year_and_day_month():
    # Exact pattern from production PaddleOCR on CIN verso (May 2026).
    raw = (
        "2024 13 oS Rh 20878141 06 04 "
        "اسم رلقب الأم منجية العياري اريانة الشمالية اريانة ترش فجو "
        "6.S Rh 20878141 06 04"
    )
    out = parse_fields(raw, "cin")
    assert out["date_delivrance"] == "2024-04-06"
    assert out["numero_cin"] == "20878141"
    assert out["date_naissance"] is None


def test_cin_verso_returns_null_name_and_dob():
    # Real OCR output from cinverso.png — contains the mother label "الأم",
    # parent info, address, and the card's issue date. The cardholder's
    # name and DOB live on the recto, not here.
    raw = (
        "EeTETeLOEALe 56 2024 GS Rh 20878141 06 04 NAOAACAKA "
        "اس ولقب الأم منجية العياري بجامعة خاصة طالبة المبنة الجوهرة "
        "اقامةرحمانةنهج العنوان اريانة اريانة الشمالية .. 2024 جوان ترض في "
        "GS Rh 20878141 06 04"
    )
    out = parse_fields(raw, "cin")
    assert out["nom"] is None
    assert out["prenom"] is None
    assert out["pere"] is None
    assert out["date_naissance"] is None
    # The CIN number and governorate (residence) still resolve.
    assert out["numero_cin"] == "20878141"
    assert out["gouvernorat"] == "ARIANA"
    assert out["date_delivrance"] is not None


# ────────────────────── CARTE GRISE ──────────────────────

def test_carte_grise_full():
    raw = "CARTE GRISE TOYOTA 123 TU 4567 JTDBT923771012345 Year 2018"
    out = parse_fields(raw, "carte_grise")
    assert out["immatriculation"] == "123TU4567"
    assert out["vin"] == "JTDBT923771012345"
    assert out["marque"] == "TOYOTA"
    assert out["annee"] == "2018"


def test_carte_grise_plate_spacing_variants():
    out = parse_fields("123TU4567", "carte_grise")
    assert out["immatriculation"] == "123TU4567"


# ────────────────────── ASSURANCE ──────────────────────

def test_assurance_full():
    raw = "ASSURANCE AUTO N° 2025/1234567 STAR Validité Du 01/01/2025 Au 31/12/2025"
    out = parse_fields(raw, "assurance")
    assert out["numero_police"] == "2025/1234567"
    assert out["compagnie"] == "STAR"
    assert out["date_debut"] == "01/01/2025"
    assert out["date_fin"] == "31/12/2025"


def test_assurance_glued_date_d_prefix():
    """OCR sometimes glues 'Du' onto the date producing 'D25/10/2025'."""
    raw = "ASSURANCE N° 2025/9999 GAT D25/10/2025 Au pour 24/10/2026"
    out = parse_fields(raw, "assurance")
    assert out["date_debut"] == "25/10/2025"
    assert out["compagnie"] == "GAT"


def test_assurance_company_whole_word_only():
    """'CARTE STAR' shouldn't false-match on 'STAR' as a substring inside 'CARTE'."""
    raw = "POLICE 2024/12345 NOTASTAR INSURANCE Du 01/01/2024 Au 31/12/2024"
    out = parse_fields(raw, "assurance")
    assert out["compagnie"] is None  # NOTASTAR not in our list


# ────────────── Unknown doc type ──────────────

def test_unknown_doc_type_returns_empty_dict():
    assert parse_fields("anything", "passport") == {}
