from __future__ import annotations

import re
from datetime import date
from typing import Any


_DATE_PATTERN = r"\b(\d{2}[\/\-]\d{2}[\/\-]\d{4})\b"
_UPPERCASE_WORD = r"\b([A-Z]{2,}(?:\s+[A-Z]{2,})*)\b"

_TUNISIAN_GOVERNORATES = {
    "TUNIS", "ARIANA", "BEN AROUS", "MANOUBA", "NABEUL", "ZAGHOUAN",
    "BIZERTE", "BEJA", "JENDOUBA", "KEF", "SILIANA", "SOUSSE",
    "MONASTIR", "MAHDIA", "SFAX", "KAIROUAN", "KASSERINE", "SIDI BOUZID",
    "GABES", "MEDNINE", "TATAOUINE", "GAFSA", "TOZEUR", "KEBILI",
}

# ── Arabic support (CIN parser) ────────────────────────────────────────────
# Tunisian CIN cards print fields predominantly in Arabic. The four ranges
# below cover Arabic base letters, Arabic Supplement, and presentation
# forms A and B — anything PaddleOCR-AR will plausibly emit.
_AR_LETTER = (
    "[؀-ٟ"   # Arabic block, up to but excluding the Indic digits at U+0660-U+0669
    "٪-ۿ"    # Arabic block, resuming after the digits
    "ݐ-ݿ"    # Arabic Supplement
    "ﭐ-﷿"    # Arabic Presentation Forms-A
    "ﹰ-ﻼ]"   # Arabic Presentation Forms-B
)
_AR_WORD = rf"{_AR_LETTER}{{2,}}"
_AR_DIGIT = "[٠-٩]"
_AR_TO_WESTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Tunisian CIN field labels. Tunisian usage prefers اللقب (surname) /
# الإسم (first name); we also accept the unprefixed forms and the form
# with shadda on the lām.
_LABEL_NOM_AR = r"(?:اللقب|اللّقب|لقب)"
_LABEL_PRENOM_AR = r"(?:الإسم|الاسم|اسم)"

# Stop-words for the "greedy name" fallback — if we can't anchor on a
# label we still want to avoid grabbing a label or date keyword as a name.
_AR_STOP_WORDS = {
    "اللقب", "اللّقب", "لقب",
    "الإسم", "الاسم", "اسم",
    "ولد", "ولدت", "في", "تاريخ", "الولادة", "الميلاد",
    "الجنسية", "تونسية", "تونسي",
    # Lineage connectors — never a name on their own.
    "بن", "بنت",
    # Verso-side parent labels — these are field labels, not the cardholder's name.
    "الأم", "الام", "الأب",
}

# Arabic ⇒ French governorate map. Variants with/without leading ال
# definite article are both common on OCR output. Ordered longest-first
# at lookup time so multi-word entries match before their prefixes.
_GOVERNORATES_AR_TO_FR = {
    "تونس": "TUNIS",
    "أريانة": "ARIANA", "اريانة": "ARIANA",
    "بن عروس": "BEN AROUS",
    "منوبة": "MANOUBA",
    "نابل": "NABEUL",
    "زغوان": "ZAGHOUAN",
    "بنزرت": "BIZERTE",
    "باجة": "BEJA",
    "جندوبة": "JENDOUBA",
    "الكاف": "KEF", "كاف": "KEF",
    "سليانة": "SILIANA",
    "سوسة": "SOUSSE",
    "المنستير": "MONASTIR", "منستير": "MONASTIR",
    "المهدية": "MAHDIA", "مهدية": "MAHDIA",
    "صفاقس": "SFAX",
    "القيروان": "KAIROUAN", "قيروان": "KAIROUAN",
    "القصرين": "KASSERINE", "قصرين": "KASSERINE",
    "سيدي بوزيد": "SIDI BOUZID",
    "قابس": "GABES",
    "مدنين": "MEDNINE",
    "تطاوين": "TATAOUINE",
    "قفصة": "GAFSA",
    "توزر": "TOZEUR",
    "قبلي": "KEBILI",
}

# Arabic month names → month number. Tunisian dialect spellings first
# (جانفي/فيفري/أفريل/ماي/جوان/جويلية/أوت) then MSA fallbacks.
_AR_MONTHS = {
    "جانفي": 1, "يناير": 1,
    "فيفري": 2, "فبراير": 2,
    "مارس": 3,
    "أفريل": 4, "أبريل": 4, "ابريل": 4,
    "ماي": 5, "مايو": 5,
    "جوان": 6, "يونيو": 6,
    "جويلية": 7, "يوليو": 7,
    "أوت": 8, "أغسطس": 8,
    "سبتمبر": 9, "شتنبر": 9,
    "أكتوبر": 10, "اكتوبر": 10,
    "نوفمبر": 11, "نونبر": 11,
    "ديسمبر": 12, "دجنبر": 12,
}

_DATE_AR_LONG = rf"(\d{{1,2}})\s+({'|'.join(_AR_MONTHS)})\s+(\d{{4}})"
_DATE_AR_DIGITS = rf"({_AR_DIGIT}{{1,4}})[\/\-]({_AR_DIGIT}{{1,2}})[\/\-]({_AR_DIGIT}{{2,4}})"
_DATE_NUMERIC_FULL = r"(\d{1,4})[\/\-](\d{1,2})[\/\-](\d{2,4})"

# Permis date-label markers. Order = priority within each tuple.
# Latin (EU field numbers + French phrases) → Arabic.
_PERMIS_NAISSANCE_LABELS = (
    r"\b5\.\s*",
    r"N[eé]\(?e\)?\s+le\s*:?\s*",
    r"Date\s+de\s+naissance\s*:?\s*",
    r"تاريخ\s+الولادة\s*:?\s*",
    r"تاريخ\s+الميلاد\s*:?\s*",
)
_PERMIS_DELIVRANCE_LABELS = (
    r"\b4\s*a\.\s*",
    r"Date\s+de\s+d[eé]livrance\s*:?\s*",
    r"D[eé]livr[eé]e?\s+le\s*:?\s*",
    r"تاريخ\s+التسليم\s*:?\s*",
)
_PERMIS_EXPIRATION_LABELS = (
    r"\b4\s*b\.\s*",
    r"\b10\.\s*",
    r"Valable\s+jusqu['’]au\s*:?\s*",
    r"Valide\s+jusqu['’]au\s*:?\s*",
    r"Date\s+d['’]expiration\s*:?\s*",
    r"صالحة\s+لغاية\s*:?\s*",
    r"صالح(?:ة)?\s+إلى\s*:?\s*",
)

_CAR_BRANDS = {
    "TOYOTA", "VOLKSWAGEN", "PEUGEOT", "RENAULT", "HYUNDAI", "KIA",
    "FORD", "BMW", "MERCEDES", "MERCEDES-BENZ", "OPEL", "FIAT",
    "CITROEN", "NISSAN", "HONDA", "MAZDA", "MITSUBISHI", "SUZUKI",
    "SEAT", "SKODA", "AUDI", "VOLVO", "LAND ROVER", "JEEP", "DACIA",
    "CHEVROLET", "DODGE", "SUBARU", "LEXUS", "INFINITI", "ALFA ROMEO",
}

_TUNISIAN_INSURERS = {
    "STAR", "GAT", "COMAR", "MAGHREBIA", "ASTREE", "CTAMA",
    "TUNIS RE", "ASSURANCES SALIM", "BH ASSURANCE", "AMI ASSURANCES",
    "HEXAGONE", "HAYETT", "ZITOUNA TAKAFUL",
}


def _find_dates(text: str) -> list[str]:
    return re.findall(_DATE_PATTERN, text)


def _find_uppercase_names(text: str) -> list[str]:
    # exclude single letters (like category labels) and known non-name tokens
    matches = re.findall(r"\b([A-Z]{2,}(?:\s+[A-Z]{2,})*)\b", text)
    return [m for m in matches if not re.fullmatch(r"[A-Z]", m.strip())]


# ── Arabic helpers (used only by _parse_cin) ───────────────────────────────


def _to_iso_date(d: str, m: str, y: str) -> str | None:
    """Normalise (day, month, year) tuple to ISO YYYY-MM-DD.

    Accepts Western or Arabic-Indic digits. Resolves 2-digit years using
    a sliding window: ≤ (current year - 2000) + 30 → 20YY, else 19YY.
    The input groups may be passed in (D, M, Y) or (Y, M, D) order; we
    detect by which side carries 4 digits.
    """
    a = d.translate(_AR_TO_WESTERN_DIGITS)
    b = m.translate(_AR_TO_WESTERN_DIGITS)
    c = y.translate(_AR_TO_WESTERN_DIGITS)

    # If the first group is 4 digits and the last is short, it's YYYY-MM-DD.
    if len(a) == 4 and len(c) <= 2:
        year_s, month_s, day_s = a, b, c
    else:
        day_s, month_s, year_s = a, b, c

    try:
        day = int(day_s)
        month = int(month_s)
        year = int(year_s)
    except ValueError:
        return None

    if len(year_s) == 2:
        cutoff = (date.today().year - 2000) + 30
        year = 2000 + year if year <= cutoff else 1900 + year

    if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _find_date_arabic(text: str) -> str | None:
    """First Arabic-month or Arabic-Indic numeric date in text, ISO format."""
    m = re.search(_DATE_AR_LONG, text)
    if m:
        day = m.group(1)
        month_num = _AR_MONTHS[m.group(2)]
        year = m.group(3)
        return _to_iso_date(day, str(month_num), year)

    m = re.search(_DATE_AR_DIGITS, text)
    if m:
        return _to_iso_date(m.group(1), m.group(2), m.group(3))

    return None


def _find_date_arabic_loose(text: str) -> str | None:
    """Tolerant date scan when the day/month/year are not adjacent.

    PaddleOCR concatenates text-lines in detection order, which can scramble
    `<day> <month> <year>` on cards where these are visually stacked. For
    each Arabic month occurrence, look ±40 chars for a 4-digit year and a
    1-2 digit day; pick the oldest year (birth date heuristic).
    """
    months_pattern = "|".join(sorted(_AR_MONTHS.keys(), key=len, reverse=True))
    best: tuple[int, str] | None = None  # (year, iso)
    for m in re.finditer(months_pattern, text):
        month_num = _AR_MONTHS[m.group(0)]
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 40)
        window = text[start:end]

        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", window)
        if not year_match:
            continue
        year = year_match.group(1)

        # Day: 1-2 western digits NOT inside the year span we just picked.
        day = None
        for d_match in re.finditer(r"\b(\d{1,2})\b", window):
            if d_match.start() == year_match.start():
                continue
            n = int(d_match.group(1))
            if 1 <= n <= 31:
                day = d_match.group(1)
                break
        if day is None:
            # Try Arabic-Indic digits in the window.
            for d_match in re.finditer(rf"({_AR_DIGIT}{{1,2}})", window):
                translated = d_match.group(1).translate(_AR_TO_WESTERN_DIGITS)
                n = int(translated)
                if 1 <= n <= 31:
                    day = translated
                    break
        if day is None:
            continue

        iso = _to_iso_date(day, str(month_num), year)
        if iso is None:
            continue
        year_int = int(year)
        if best is None or year_int < best[0]:
            best = (year_int, iso)

    return best[1] if best else None


def _find_cin_number(text: str) -> str | None:
    """8-digit CIN, Western digits preferred; fall back to Arabic-Indic.

    `\\d` in Python 3 matches any Unicode digit, including Arabic-Indic
    glyphs — so we use explicit `[0-9]` to keep the two branches distinct
    and only translate the Indic branch.
    """
    m = re.search(r"(?<!\d)([0-9]{8})(?!\d)", text)
    if m:
        return m.group(1)
    m = re.search(rf"({_AR_DIGIT}{{8}})", text)
    if m:
        return m.group(1).translate(_AR_TO_WESTERN_DIGITS)
    return None


_LINEAGE_MARKERS = ("بن", "بنت")


def _extract_arabic_name(text: str, label_pattern: str) -> str | None:
    """Find the first Arabic word immediately after one of the given labels.

    Tunisian CIN fields use a single word per name slot — compound names and
    father lineage are handled separately in `_parse_cin` via the بن/بنت
    post-fix. The one exception is compound surnames that start with بن
    (e.g. "بن علي"): in that case we grab the next Arabic word too, so the
    surname survives intact.

    Returns None when the label is absent.
    """
    m = re.search(rf"{label_pattern}[\s:،,]{{0,5}}({_AR_WORD})", text)
    if not m:
        return None
    first = m.group(1)
    if first in _LINEAGE_MARKERS:
        tail = re.match(rf"\s+({_AR_WORD})", text[m.end():])
        if tail and tail.group(1) not in _AR_STOP_WORDS:
            return f"{first} {tail.group(1)}"
        return None
    if first in _AR_STOP_WORDS:
        # Label is present but immediately followed by another label/keyword
        # (e.g. "ولقب الأم" on the verso) — no real name to extract here.
        return None
    return first


def _resolve_pere_and_fix_prenom(
    text: str,
    nom: str | None,
    prenom: str | None,
) -> tuple[str | None, str | None]:
    """Use the بن/بنت connector to extract father's name and (if needed)
    correct a prenom that was actually the father's first name.

    Canonical layout: `… اللقب <nom> الاسم <prenom> بن <pere> …`
        → label-anchored prenom IS the cardholder's given name; pere is
          the token after بن.

    Scrambled OCR layout: `… اللقب <nom> <given_name> الاسم <pere> بن … …`
        → label-anchored prenom is the father's first name (token before بن).
          The given name was concatenated by PaddleOCR after `nom`; recover
          it as the first non-stop-word token between `nom` and `الاسم`.

    Returns (prenom, pere). Either may be None.
    """
    if not prenom:
        return prenom, None

    tokens = _find_arabic_words_in_order(text)
    if not tokens:
        return prenom, None

    # If the nom is a compound starting with بن (e.g. "بن علي"), the
    # marker inside the surname must NOT be treated as a lineage connector.
    nom_parts = nom.split() if nom else []
    surname_marker_idx = None
    if len(nom_parts) >= 2 and nom_parts[0] in _LINEAGE_MARKERS:
        for i in range(len(tokens) - 1):
            if tokens[i] == nom_parts[0] and tokens[i + 1] == nom_parts[1]:
                surname_marker_idx = i
                break

    # Find the first lineage marker that isn't part of the surname.
    marker_idx = next(
        (
            i for i, t in enumerate(tokens)
            if t in _LINEAGE_MARKERS and i != surname_marker_idx
        ),
        -1,
    )
    if marker_idx == -1:
        return prenom, None

    before = tokens[marker_idx - 1] if marker_idx - 1 >= 0 else None
    after = tokens[marker_idx + 1] if marker_idx + 1 < len(tokens) else None

    # Disambiguator: is there a non-stop-word Arabic token wedged between
    # nom and the label-anchored prenom? If yes → OCR scrambled the lines
    # (the wedged token is the real given name, and the label-anchored
    # prenom is actually the father's first name). If no → canonical layout.
    wedged: str | None = None
    if nom_parts and prenom in tokens:
        last_nom_word = nom_parts[-1]
        nom_idx = next(
            (i for i in range(len(tokens) - 1, -1, -1) if tokens[i] == last_nom_word),
            -1,
        )
        prenom_idx = tokens.index(prenom)
        if 0 <= nom_idx < prenom_idx:
            gov_tokens = {tok for k in _GOVERNORATES_AR_TO_FR for tok in k.split()}
            stops = _AR_STOP_WORDS | gov_tokens | set(_AR_MONTHS.keys())
            wedged_candidates = [
                t for t in tokens[nom_idx + 1:prenom_idx]
                if t not in stops and t not in nom_parts
            ]
            if wedged_candidates:
                wedged = wedged_candidates[0]

    if wedged is not None:
        # Scrambled OCR: the token wedged after `nom` is the real prenom,
        # and the label-anchored prenom is the father's first name.
        return wedged, prenom

    # Canonical layout: keep the label-anchored prenom; pere is the token
    # immediately after the marker.
    if before == prenom:
        return prenom, after

    # Edge: marker present but neither layout matches — best-effort pere.
    if before is None or before in _AR_STOP_WORDS:
        return prenom, after if after and after not in _AR_STOP_WORDS else None
    return prenom, before


def _find_arabic_words_in_order(text: str) -> list[str]:
    """All Arabic words (≥2 letters) in the order they appear.

    Returns individual words rather than greedy phrases — the
    label-anchored extractor already handles compound names; the
    fallback only kicks in when labels failed, in which case the safer
    bet is to assign words 1:1 (first → nom, second → prenom) the same
    way the Latin fallback does.
    """
    return re.findall(_AR_WORD, text)


def _match_arabic_governorate(text: str) -> str | None:
    """Match against the AR governorate map, longest key first."""
    for ar_name in sorted(_GOVERNORATES_AR_TO_FR, key=len, reverse=True):
        if ar_name in text:
            return _GOVERNORATES_AR_TO_FR[ar_name]
    return None


def _detect_language(text: str) -> str:
    has_ar = bool(re.search(_AR_LETTER, text))
    has_fr = bool(re.search(r"[A-Za-z]{3,}", text))
    if has_ar and has_fr:
        return "mixed"
    if has_ar:
        return "ar"
    return "fr"


def _iso_to_date(iso: str) -> date:
    y, m, d = iso.split("-")
    return date(int(y), int(m), int(d))


def _find_labeled_date(text: str, label_patterns: tuple[str, ...]) -> str | None:
    """First ISO date that appears within ~60 chars after any of the labels.

    Labels are tried in declared priority order. For each label match the
    forward window is scanned for, in turn: Western-digit DD-MM-YYYY,
    Arabic-Indic numeric date, then `<day> <arabic-month> <year>`. The
    first hit wins.
    """
    for label_re in label_patterns:
        for label_match in re.finditer(label_re, text, re.IGNORECASE):
            window = text[label_match.end(): label_match.end() + 60]

            m = re.search(_DATE_NUMERIC_FULL, window)
            if m:
                iso = _to_iso_date(m.group(1), m.group(2), m.group(3))
                if iso:
                    return iso

            m = re.search(_DATE_AR_DIGITS, window)
            if m:
                iso = _to_iso_date(m.group(1), m.group(2), m.group(3))
                if iso:
                    return iso

            m = re.search(_DATE_AR_LONG, window)
            if m:
                iso = _to_iso_date(
                    m.group(1), str(_AR_MONTHS[m.group(2)]), m.group(3)
                )
                if iso:
                    return iso
    return None


def _collect_all_iso_dates(text: str) -> list[str]:
    """Every recognizable date in text, normalised to ISO, deduped.

    Latin numeric, Arabic-Indic numeric, and day-+-Arabic-month forms are
    all considered. Order of first appearance is preserved.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _add(iso: str | None) -> None:
        if iso and iso not in seen:
            seen.add(iso)
            found.append(iso)

    for m in re.finditer(_DATE_NUMERIC_FULL, text):
        _add(_to_iso_date(m.group(1), m.group(2), m.group(3)))
    for m in re.finditer(_DATE_AR_DIGITS, text):
        _add(_to_iso_date(m.group(1), m.group(2), m.group(3)))
    for m in re.finditer(_DATE_AR_LONG, text):
        _add(_to_iso_date(m.group(1), str(_AR_MONTHS[m.group(2)]), m.group(3)))
    return found


def _disambiguate_permis_dates(
    text: str,
    naissance: str | None,
    delivrance: str | None,
    expiration: str | None,
    warnings: list[str],
) -> tuple[str | None, str | None, str | None]:
    """Fill missing slots via chronological ordering of the remaining dates.

    The label-anchored pass already wins when it can; this fallback only
    looks at dates that weren't claimed there. Heuristics:
      - All 3 slots empty: oldest → naissance, most-recent past → delivrance,
        a future date → expiration.
      - Partial fills: greedy chronological placement (future → expiration,
        old enough to be a birth year → naissance, else → delivrance).
    A `date_delivrance_unidentified` warning is appended when we can locate
    naissance + expiration but not delivrance. `no_dates_detected` and
    `date_ambiguous` cover the degenerate cases.
    """
    today = date.today()
    all_iso = _collect_all_iso_dates(text)
    assigned = {d for d in (naissance, delivrance, expiration) if d}
    remaining = sorted(set(all_iso) - assigned, key=_iso_to_date)

    if not remaining and not assigned:
        warnings.append("no_dates_detected")
        return naissance, delivrance, expiration

    if naissance is None and delivrance is None and expiration is None:
        past = [d for d in remaining if _iso_to_date(d) < today]
        future = [d for d in remaining if _iso_to_date(d) >= today]
        if len(remaining) >= 3:
            naissance = past[0] if past else remaining[0]
            expiration = future[-1] if future else remaining[-1]
            if len(past) >= 2:
                delivrance = past[-1]
        elif len(remaining) == 2:
            naissance = remaining[0]
            expiration = remaining[1]
        elif len(remaining) == 1:
            y = _iso_to_date(remaining[0]).year
            if y > today.year:
                expiration = remaining[0]
            elif y < today.year - 5:
                naissance = remaining[0]
            else:
                warnings.append("date_ambiguous")
    else:
        for d in remaining:
            d_obj = _iso_to_date(d)
            if expiration is None and d_obj > today:
                expiration = d
            elif naissance is None and (today.year - d_obj.year) >= 16:
                naissance = d
            elif delivrance is None and d_obj <= today:
                delivrance = d

    if naissance and expiration and not delivrance:
        warnings.append("date_delivrance_unidentified")

    return naissance, delivrance, expiration


def _parse_permis(text: str) -> dict[str, Any]:
    warnings: list[str] = []

    # ── numéro permis ──
    # Permis tunisien format: 8 chiffres, l'OCR peut insérer un espace ou slash
    # ex. "23/ 238943" → on colle les blocs de chiffres autour de "1."
    numero = None
    m = re.search(r"\b(\d{8})\b", text)
    if m:
        numero = m.group(1)
    else:
        # Reconstruit depuis "1. 23/ 238943" ou "1. 23 238943"
        m = re.search(r"(?:^|\s)1\.\s*(\d[\d\s\/]+\d)", text)
        if m:
            candidate = re.sub(r"[\s\/]", "", m.group(1))
            if len(candidate) == 8:
                numero = candidate
        if not numero:
            # Dernier recours: deux groupes de chiffres adjacents → 8 digits
            m = re.search(r"\b(\d{2,4})\s*[\/]\s*(\d{4,6})\b", text)
            if m:
                candidate = m.group(1) + m.group(2)
                if len(candidate) == 8:
                    numero = candidate

    # ── catégories: A B C D E (seules ou suivies d'un chiffre ex. C4) ──
    categories = sorted(set(re.findall(r"\b([ABCDE])\d?\b", text)))

    # ── nom: premier mot majuscule après "3." (champ EU = Nom de famille) ──
    nom = None
    m = re.search(r"\b3\.\s+([A-Z]{2,}(?:\s+[A-Z]{2,})*)", text)
    if m:
        # Prendre uniquement la première suite de mots en majuscules
        nom = m.group(1).split()[0]  # "KARKOUB t.mdiy..." → "KARKOUB"

    # ── prenom: champ 4 EU (OCR lit parfois "4." comme "t." ou "4a.") ──
    prenom = None
    _FIELD_LABELS = r"(?:Nom|Pr[eé]nom|Date|Lieu|Num[eé]ro|Nature|Nombre|Adresse|Identit|Cat[eé]g|transform)"
    # Essai 1 : "4." explicite — exclut "4a."/"4b." qui sont des labels de dates.
    m = re.search(r"\b4\.\s+([A-Za-z][A-Za-z\s\-\']{2,30})(?=\s+\d+\.|\s{2}|$)", text)
    if m:
        candidate = m.group(1).strip()
        if not re.search(_FIELD_LABELS, candidate, re.IGNORECASE):
            prenom = candidate
    # Essai 2 : "t." juste après le nom → OCR misread de "4."
    if not prenom and nom:
        m = re.search(rf"{re.escape(nom)}\s+t\.\s*([A-Za-z]{{2,}})", text, re.IGNORECASE)
        if m:
            prenom = m.group(1).strip()

    # ── dates: label-anchored extraction → chronological fallback ──
    date_naissance = _find_labeled_date(text, _PERMIS_NAISSANCE_LABELS)
    date_delivrance = _find_labeled_date(text, _PERMIS_DELIVRANCE_LABELS)
    date_expiration = _find_labeled_date(text, _PERMIS_EXPIRATION_LABELS)

    if not (date_naissance and date_delivrance and date_expiration):
        date_naissance, date_delivrance, date_expiration = _disambiguate_permis_dates(
            text, date_naissance, date_delivrance, date_expiration, warnings
        )

    today = date.today()
    if date_expiration and _iso_to_date(date_expiration) < today:
        warnings.append("date_expiration_in_past")
    if date_delivrance and _iso_to_date(date_delivrance) > today:
        warnings.append("date_delivrance_in_future")
    if date_naissance and (today.year - _iso_to_date(date_naissance).year) < 16:
        warnings.append("date_naissance_too_recent")

    return {
        "nom": nom,
        "prenom": prenom,
        "numero": numero,
        "date_naissance": date_naissance,
        "date_delivrance": date_delivrance,
        "date_expiration": date_expiration,
        "categories": categories,
        "warnings": warnings,
    }


def _parse_cin(text: str) -> dict[str, Any]:
    numero = _find_cin_number(text)

    # ── Names: AR labels → AR fallback → Latin (legacy) ─────────────────
    nom = _extract_arabic_name(text, _LABEL_NOM_AR)
    prenom = _extract_arabic_name(text, _LABEL_PRENOM_AR)

    # Verso scans contain parent/address info, not the cardholder's name.
    # If the "mother" label is present, the word-order fallback would
    # promote OCR noise — skip it.
    is_verso = bool(re.search(r"الأم|الام|الأب", text))

    if not (nom and prenom) and not is_verso:
        gov_words = set(_GOVERNORATES_AR_TO_FR)
        # Words consumed by the label-anchored matches must be excluded
        # from the fallback pool, otherwise a 1-word `nom` ("العمري")
        # gets handed to `prenom` as well.
        taken_words: set[str] = set()
        for v in (nom, prenom):
            if v:
                taken_words.update(v.split())
        # Governorate keys may be multi-word ("بن عروس"); split them too
        # so individual tokens still get filtered out.
        gov_tokens = {tok for k in gov_words for tok in k.split()}
        stops = _AR_STOP_WORDS | gov_tokens | taken_words

        candidates = [w for w in _find_arabic_words_in_order(text) if w not in stops]
        if not nom and candidates:
            nom = candidates.pop(0)
        if not prenom and candidates:
            prenom = candidates.pop(0)

    if not (nom and prenom) and not is_verso:
        legacy = _find_uppercase_names(text)
        if not nom and legacy:
            nom = legacy[0]
        if not prenom and len(legacy) > 1:
            prenom = legacy[1]

    # ── Lineage marker (بن / بنت): recover prenom/pere from chain ────────
    prenom, pere = _resolve_pere_and_fix_prenom(text, nom, prenom)

    # ── Date: Arabic strict → Arabic loose → Western numeric ────────────
    # Skip on verso scans (the only date there is the card-issue date).
    date_naissance: str | None = None
    if not is_verso:
        date_naissance = _find_date_arabic(text)
        if not date_naissance:
            date_naissance = _find_date_arabic_loose(text)
        if not date_naissance:
            m = re.search(_DATE_PATTERN, text)
            if m:
                day, month, year = m.group(1).replace("-", "/").split("/")
                date_naissance = _to_iso_date(day, month, year) or m.group(1)

    # ── Governorate: AR map → Latin set ─────────────────────────────────
    gouvernorat = _match_arabic_governorate(text)
    if not gouvernorat:
        upper = text.upper()
        gouvernorat = next((g for g in _TUNISIAN_GOVERNORATES if g in upper), None)

    return {
        "nom": nom,
        "prenom": prenom,
        "pere": pere,
        "numero_cin": numero,
        "date_naissance": date_naissance,
        "gouvernorat": gouvernorat,
        "language_detected": _detect_language(text),
    }


def _parse_carte_grise(text: str) -> dict[str, Any]:
    # Tunisian plate: digits + TU + digits  (e.g. 123 TU 4567)
    immatriculation = None
    m = re.search(r"\b(\d+\s*TU\s*\d+)\b", text, re.IGNORECASE)
    if m:
        immatriculation = m.group(1).replace(" ", "")

    vin = None
    m = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text)
    if m:
        vin = m.group(1)

    upper_text = text.upper()
    marque = next((b for b in _CAR_BRANDS if b in upper_text), None)

    annee = None
    m = re.search(r"\b(19[6-9]\d|20[0-4]\d)\b", text)
    if m:
        annee = m.group(1)

    return {
        "immatriculation": immatriculation,
        "vin": vin,
        "marque": marque,
        "annee": annee,
    }


def _parse_assurance(text: str) -> dict[str, Any]:
    # ── numéro de police: format YYYY/XXXXXXX ou alphanumérique ──
    numero_police = None
    # Priorité 1: format N° YYYY/NNNNNNN juste après "N°"
    m = re.search(r"N[°o°]\s*(\d{4}/\d{4,8})", text)
    if m:
        numero_police = m.group(1)
    if not numero_police:
        # Priorité 2: format YYYY/NNNNNNN seul
        m = re.search(r"\b(\d{4}/\d{4,8})\b", text)
        if m:
            numero_police = m.group(1)
    if not numero_police:
        # Fallback: premier token alphanumérique long
        m = re.search(r"\b([A-Z0-9]{6,20})\b", text)
        if m:
            numero_police = m.group(1)

    # ── dates: regex sans \b en début pour gérer "D25/10/2025" (OCR colle "Du") ──
    _DATE_LOOSE = r"\d{2}[\/\-]\d{2}[\/\-]\d{4}"

    date_debut = None
    date_fin = None

    # "Validité Du/D …" → date de début
    m = re.search(rf"[Vv]alidit[eé]\s+[Dd][Uu]?\s*({_DATE_LOOSE})", text)
    if not m:
        # OCR peut coller "D" directement: "D25/10/2025"
        m = re.search(rf"(?<=[Dd])({_DATE_LOOSE})", text)
    if m:
        date_debut = m.group(1)

    # "Validité AU …" ou "Au …" → date de fin
    m = re.search(rf"(?:[Vv]alidit[eé]\s+)?[Aa][Uu]\s+\S+\s+({_DATE_LOOSE})", text)
    if not m:
        m = re.search(rf"[Vv]alable\s+jusqu[‘’]au\s*:?\s*({_DATE_LOOSE})", text)
    if m:
        date_fin = m.group(1)

    # "effectuée le" → date alternative pour début
    if not date_debut:
        m = re.search(rf"effectu[eé]e?\s*le\s*:?\s*({_DATE_LOOSE})", text, re.IGNORECASE)
        if m:
            date_debut = m.group(1)

    # Fallback: toutes les dates (sans \b pour attraper "D25/10/2025")
    if not date_debut or not date_fin:
        all_dates = re.findall(_DATE_LOOSE, text)
        if not date_debut and all_dates:
            date_debut = all_dates[0]
        if not date_fin and len(all_dates) > 1:
            date_fin = all_dates[-1]

    # ── compagnie: mot entier uniquement (évite faux positifs sur "N° DE LA CARTE") ──
    upper_text = text.upper()
    compagnie = next(
        (c for c in _TUNISIAN_INSURERS if re.search(rf"\b{re.escape(c)}\b", upper_text)),
        None,
    )

    return {
        "numero_police": numero_police,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "compagnie": compagnie,
    }


_PARSERS = {
    "permis": _parse_permis,
    "cin": _parse_cin,
    "carte_grise": _parse_carte_grise,
    "assurance": _parse_assurance,
}


def parse_fields(raw_text: str, doc_type: str) -> dict[str, Any]:
    parser = _PARSERS.get(doc_type)
    if parser is None:
        return {}
    return parser(raw_text)
