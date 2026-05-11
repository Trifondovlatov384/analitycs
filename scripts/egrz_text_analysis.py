from __future__ import annotations

import re

COLUMN_REGION = "Субъект РФ"
COLUMN_OBJECT = (
    "Наименование и адрес (местоположение) объекта капитального строительства, "
    "применительно к которому подготовлена проектная документация"
)
COLUMN_DEVELOPER = (
    "Сведения о застройщике, обеспечившем подготовку проектной документации"
)
COLUMN_WORK_TYPE = "Вид работ"

TARGET_REGIONS = [
    "Краснодарский край",
    "Республика Крым",
    "алтай",
    "карачаево-черкесская республика",
]

KEYWORD_GROUPS: dict[str, list[str]] = {
    "апартаментный": [
        "апартамент",
        "апарт-",
        "апарт ",
        "апартотель",
        "апарт-отель",
        "апартаментов",
    ],
    "гостиничный": [
        "гостиница",
        "гостиничный",
        "гостинично",
        "отель",
        "hotel",
    ],
    "санаторий": [
        "санаторий",
        "санаторно",
    ],
    "лечебно-оздоровительный": [
        "лечебный",
        "лечебно",
        "оздоровительный",
        "оздоровит",
        "рекреацион",
        "wellness",
        "spa",
    ],
    "пансионат": [
        "пансионат",
        "пансион",
        "пансионн",
        "пансионатн",
    ],
}

# Canonical keyword list used for metadata/exports.
KEYWORDS = list(KEYWORD_GROUPS.keys())

# Word forms where typo tolerance (<=1 edit) is useful.
FUZZY_KEYWORDS = [
    "апартаментный",
    "гостиница",
    "гостиничный",
    "санаторий",
    "лечебный",
    "оздоровительный",
    "пансионат",
]


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().replace("ё", "е")


def is_target_region(region_value: str, regions: list[str]) -> bool:
    region_norm = normalize_text(region_value)
    for region in regions:
        if normalize_text(region) in region_norm:
            return True
    return False


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    text_norm = normalize_text(text)
    hits: list[str] = []
    # Direct semantic matching by groups/stems.
    for keyword in keywords:
        variants = KEYWORD_GROUPS.get(keyword, [keyword])
        if any(normalize_text(variant) in text_norm for variant in variants):
            hits.append(keyword)

    # Fuzzy fallback for common typos.
    missing_for_fuzzy = [kw for kw in keywords if kw not in hits]
    if missing_for_fuzzy:
        tokens = [t for t in re.split(r"[^0-9a-zа-я-]+", text_norm) if t]
        for token in tokens:
            for fuzzy in FUZZY_KEYWORDS:
                if _is_within_one_edit(token, fuzzy):
                    canonical = _canonical_for_fuzzy(fuzzy)
                    if canonical in missing_for_fuzzy and canonical not in hits:
                        hits.append(canonical)
    return hits


def _canonical_for_fuzzy(fuzzy_keyword: str) -> str:
    for canonical, variants in KEYWORD_GROUPS.items():
        if fuzzy_keyword in [normalize_text(v) for v in variants] or normalize_text(canonical) == normalize_text(
            fuzzy_keyword
        ):
            return canonical
    return fuzzy_keyword


def _is_within_one_edit(a: str, b: str) -> bool:
    a = normalize_text(a)
    b = normalize_text(b)
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    # Single-pass check for edit distance <= 1.
    i = 0
    j = 0
    edits = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if len(a) > len(b):
            i += 1
        elif len(a) < len(b):
            j += 1
        else:
            i += 1
            j += 1
    if i < len(a) or j < len(b):
        edits += 1
    return edits <= 1


def compose_search_text(row: dict[str, str]) -> str:
    return " ".join(
        [
            row.get(COLUMN_OBJECT, ""),
            row.get(COLUMN_DEVELOPER, ""),
            row.get(COLUMN_WORK_TYPE, ""),
        ]
    )


def filter_rows(
    rows: list[dict[str, str]],
    regions: list[str] | None = None,
    keywords: list[str] | None = None,
) -> list[dict[str, str]]:
    selected_regions = regions or TARGET_REGIONS
    selected_keywords = keywords or KEYWORDS
    result: list[dict[str, str]] = []
    for row in rows:
        region_value = row.get(COLUMN_REGION, "") or ""
        object_value = row.get(COLUMN_OBJECT, "") or ""
        region_match = is_target_region(region_value, selected_regions)

        # "Архыз" используем как алиас региона только если в строке
        # субъект не заполнен либо уже содержит указание на Карачаево-Черкессию.
        region_norm = normalize_text(region_value)
        object_norm = normalize_text(object_value)
        archyz_alias_match = "архыз" in object_norm and (
            not region_norm or "карачаево" in region_norm
        )

        if not (region_match or archyz_alias_match):
            continue
        hits = matched_keywords(compose_search_text(row), selected_keywords)
        if not hits:
            continue
        prepared = dict(row)
        prepared["MatchedKeywords"] = ", ".join(hits)
        result.append(prepared)
    return result
