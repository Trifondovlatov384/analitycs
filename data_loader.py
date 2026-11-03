from __future__ import annotations

import csv
import hashlib
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import polars as pl

CRIMEA_PATH_DEFAULT = "august2026.csv"
MAIN_DATA_DEFAULT = "august2026.csv"
ANALYTIC_PATH_DEFAULT = "Analitic.csv"
KK2026_PATH_DEFAULT = "kk_august2026.csv"
KK2026_PATH_FALLBACK = "KK2026.csv"
# Newer bnMAP exports first; only one is loaded unless BNMAP_EXPORT_PATHS is set.
BNMAP_EXPORT_CANDIDATES = ("august2026.csv", "july2026.csv", "june2026.csv", "may2026.csv")

CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"
COMBINED_CACHE_PATH = CACHE_DIR / "combined_deals.parquet"
COMBINED_CACHE_META_PATH = CACHE_DIR / "combined_deals.meta"

BNMAP_USE_COLS = (
    "ID лота",
    "Проект",
    "Город",
    "Район",
    "Девелопер",
    "Тип объекта",
    "Дата договора",
    "Тип ипотеки",
    "Тип сделки",
    "Цена за кв. метр",
    "Расчетный бюджет объекта",
    "Площадь согласно ПД",
    "Площадь согласно ЕГРН",
    "Этаж",
    "Количество комнат",
    "Локация",
    "Участие объекта в оптовой сделке",
    "Залогодержатель/Банк",
    "Кол-во месяцев обременения",
    "Старт продаж",
    "Класс",
)

# Multi-line header in bnMAP exports — matched by prefix.
BNMAP_EXPOSURE_PREFIX = "Срок в экспозиции до момента сделки"

ANALYTIC_USE_COLS = (
    "object",
    "city",
    "loc_district",
    "developer",
    "type_lot",
    "date_sold",
    "ipoteka",
    "est_budget",
    "price_square_r",
    "do_square",
    "deal_status",
    "bank_name",
    "ipoteka_month",
    "class",
)

ANAPA_CITIES = {
    "Варваровка с.",
    "Анапа",
    "Нижняя Гостагайка х.",
    "Сукко с.",
    "село Супсех",
}

SOCHI_CITIES = {
    "Раздольное с.",
    "Сочи",
    "Красная поляна пгт",
    "пгт Дагомыс",
    "Агой с.",
    "Ольгинка с.",
}


@dataclass(frozen=True)
class DataConfig:
    data_path: str


def resolve_data_path() -> str:
    env_path = os.environ.get("DATA_PATH")
    if env_path:
        return env_path
    for name in BNMAP_EXPORT_CANDIDATES:
        if Path(name).exists():
            return name
    return MAIN_DATA_DEFAULT


def _source_tag_for_path(path: str) -> str:
    return Path(path).stem


def resolve_bnmap_export_paths() -> list[str]:
    """
    bnMAP CSV paths to load. By default picks the newest available export (august2026 > july2026 > …).
    Set BNMAP_EXPORT_PATHS=comma,separated,paths to load several files (e.g. for comparison).
    """
    explicit = os.environ.get("BNMAP_EXPORT_PATHS")
    if explicit:
        raw = [p.strip() for p in explicit.split(",") if p.strip()]
    else:
        raw = [p for p in BNMAP_EXPORT_CANDIDATES if Path(p).exists()]
        if raw:
            raw = [raw[0]]
        else:
            fallback = resolve_data_path()
            if Path(fallback).exists():
                raw = [fallback]

    out: list[str] = []
    for path in raw:
        if Path(path).exists() and not any(paths_point_to_same_file(path, seen) for seen in out):
            out.append(path)
    return out


def _csv_has_bnmap_columns(path: str) -> bool:
    with open(path, encoding="utf-8", errors="replace") as f:
        header = f.readline()
    return "Проект" in header and "Дата договора" in header and "Тип ипотеки" in header


def _csv_header_columns(path: str) -> set[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        row = next(csv.reader(f), [])
    return {str(c).strip() for c in row if c}


def _fingerprint_paths(paths: list[str]) -> str:
    parts: list[str] = []
    for path in sorted(paths):
        p = Path(path)
        if not p.exists():
            continue
        st = p.stat()
        parts.append(f"{os.path.abspath(path)}:{st.st_mtime_ns}:{st.st_size}")
    if not parts:
        return "no-sources"
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# Regional bnMAP exports dropped into the project folder as downloaded, e.g.
# «bnMAP_pro_Сделки_Краснодарский_край_19-10-2026_16-14_part1.csv».
REGIONAL_EXPORT_GLOB = "bnMAP_pro_Сделки_*.csv"
_REGION_RE = re.compile(r"bnMAP_pro_Сделки_(.+?)_(\d{2})-(\d{2})-(\d{4})")
REGION_KEYS = {
    "республика_крым": "crimea",
    "крым": "crimea",
    "краснодарский_край": "kuban",
    "республика_адыгея": "adygea",
    "адыгея": "adygea",
}


def find_regional_exports() -> dict[str, list[str]]:
    """{region_key: [paths, newest export first]} for every bnMAP regional export found."""
    found: dict[str, list[tuple[tuple[int, int, int], str]]] = {}
    for path in Path(".").glob(REGIONAL_EXPORT_GLOB):
        m = _REGION_RE.match(path.name)
        if not m:
            continue
        region_raw = m.group(1).strip("_").lower()
        key = REGION_KEYS.get(region_raw, re.sub(r"[^a-zа-я0-9]+", "_", region_raw))
        stamp = (int(m.group(4)), int(m.group(3)), int(m.group(2)))
        found.setdefault(key, []).append((stamp, str(path)))
    return {k: [p for _, p in sorted(v, reverse=True)] for k, v in found.items()}


def _collect_source_paths() -> list[str]:
    paths: list[str] = []
    paths.extend(resolve_bnmap_export_paths())
    regional = find_regional_exports()
    for region_paths in regional.values():
        paths.extend(region_paths)
    # Older Kuban sources are superseded by a bnMAP Krasnodar export (same deals, shorter history).
    if "kuban" not in regional:
        analitic_path = resolve_analitic_path()
        if Path(analitic_path).exists():
            paths.append(analitic_path)
        kk2026_path = resolve_kk2026_path()
        if kk2026_path:
            paths.append(kk2026_path)
    if "crimea" not in regional:
        crimea_path = resolve_crimea_path()
        if Path(crimea_path).exists():
            paths.append(crimea_path)

    out: list[str] = []
    for path in paths:
        if Path(path).exists() and not any(paths_point_to_same_file(path, seen) for seen in out):
            out.append(path)
    return out


def _is_serverless_runtime() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _can_write_cache() -> bool:
    if _is_serverless_runtime():
        return False
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _read_combined_cache() -> pl.DataFrame | None:
    if not COMBINED_CACHE_PATH.exists():
        return None

    # Vercel/Lambda: read-only FS — use bundled parquet, never rebuild at runtime.
    if _is_serverless_runtime():
        try:
            return pl.read_parquet(COMBINED_CACHE_PATH)
        except Exception:
            return None

    if not COMBINED_CACHE_META_PATH.exists():
        return None
    try:
        expected = COMBINED_CACHE_META_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if expected != _fingerprint_paths(_collect_source_paths()):
        return None
    try:
        return pl.read_parquet(COMBINED_CACHE_PATH)
    except Exception:
        return None


def _write_combined_cache(df: pl.DataFrame, fingerprint: str) -> None:
    if not _can_write_cache():
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.write_parquet(COMBINED_CACHE_PATH, compression="zstd")
    COMBINED_CACHE_META_PATH.write_text(fingerprint, encoding="utf-8")


def build_combined_deals_cache() -> pl.DataFrame:
    """Force-rebuild parquet cache (for local scripts / CI)."""
    load_combined_deals.cache_clear()
    if COMBINED_CACHE_PATH.exists():
        COMBINED_CACHE_PATH.unlink(missing_ok=True)
    if COMBINED_CACHE_META_PATH.exists():
        COMBINED_CACHE_META_PATH.unlink(missing_ok=True)
    return load_combined_deals()


def paths_point_to_same_file(a: str, b: str) -> bool:
    """Best-effort same underlying file (handles relative vs absolute)."""
    aa = os.path.abspath(a)
    bb = os.path.abspath(b)
    if os.path.normcase(aa) == os.path.normcase(bb):
        return True
    try:
        return os.path.normcase(os.path.realpath(aa)) == os.path.normcase(os.path.realpath(bb))
    except OSError:
        return False


def resolve_crimea_path() -> str:
    env_path = os.environ.get("CRIMEA_DEALS_PATH")
    if env_path:
        return env_path
    return CRIMEA_PATH_DEFAULT


def resolve_analitic_path() -> str:
    env_path = os.environ.get("ANALYTIC_PATH")
    if env_path:
        return env_path
    return ANALYTIC_PATH_DEFAULT


def resolve_kk2026_path() -> str | None:
    env_path = os.environ.get("KK2026_PATH")
    if env_path:
        return env_path if Path(env_path).exists() else None
    candidates = (
        KK2026_PATH_DEFAULT,
        KK2026_PATH_FALLBACK,
        str(Path.home() / "Downloads" / "KK2026.csv"),
    )
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _load_regional(key: str, paths: list[str]) -> pl.DataFrame:
    """Load every export of one region; the same lot sold on the same day counts once."""
    parts = [load_bnmap_deals(p, force_crimea_agglomeration=(key == "crimea")) for p in paths]
    df = pl.concat(parts, how="diagonal") if len(parts) > 1 else parts[0]
    if len(parts) > 1 and "lot_id" in df.columns:
        with_id = df.filter(pl.col("lot_id").is_not_null())
        no_id = df.filter(pl.col("lot_id").is_null())
        with_id = with_id.unique(subset=["lot_id", "sold_date", "deal_status"], keep="first", maintain_order=True)
        df = pl.concat([with_id, no_id], how="diagonal")
    return df.with_columns(pl.lit(key).alias("source"))


def _load_combined_deals_from_csv() -> pl.DataFrame:
    """Load regional bnMAP exports (Крым, Краснодарский край, Адыгея, …) plus legacy sources."""
    frames: list[pl.DataFrame] = []
    bnmap_paths = resolve_bnmap_export_paths()
    regional = find_regional_exports()

    loaded_paths: list[str] = []
    for bnmap_path in bnmap_paths:
        frames.append(
            load_deals(DataConfig(data_path=bnmap_path)).with_columns(
                pl.lit(_source_tag_for_path(bnmap_path)).alias("source")
            )
        )
        loaded_paths.append(bnmap_path)

    for key, paths in regional.items():
        paths = [p for p in paths if not any(paths_point_to_same_file(p, q) for q in loaded_paths)]
        if paths:
            frames.append(_load_regional(key, paths))
            loaded_paths.extend(paths)

    if "kuban" not in regional:
        analitic_path = resolve_analitic_path()
        if Path(analitic_path).exists() and not any(paths_point_to_same_file(analitic_path, p) for p in loaded_paths):
            frames.append(
                load_deals(DataConfig(data_path=analitic_path)).with_columns(pl.lit("analitic").alias("source"))
            )
            loaded_paths.append(analitic_path)
        kk2026_path = resolve_kk2026_path()
        if kk2026_path and not any(paths_point_to_same_file(kk2026_path, p) for p in loaded_paths):
            frames.append(
                load_deals(DataConfig(data_path=kk2026_path)).with_columns(pl.lit("kk2026").alias("source"))
            )
            loaded_paths.append(kk2026_path)

    if "crimea" not in regional:
        crimea_path = resolve_crimea_path()
        if Path(crimea_path).exists() and not any(paths_point_to_same_file(crimea_path, p) for p in loaded_paths):
            try:
                frames.append(load_crimea_deals(crimea_path).with_columns(pl.lit("crimea").alias("source")))
            except Exception:
                pass

    if not frames:
        return pl.DataFrame()

    out = pl.concat(frames, how="diagonal")
    if "bank" in out.columns:
        out = out.with_columns(pl.col("bank").map_elements(normalize_bank, return_dtype=pl.Utf8).alias("bank"))
    return normalize_places(out)


# ───────────────────────── Places: cities, districts, agglomerations ─────────────────────────

_CITY_PREFIX = (
    ("село ", "с."),
    ("с. ", "с."),
    ("пгт ", "пгт"),
    ("пгт. ", "пгт"),
    ("поселок ", "п."),
    ("посёлок ", "п."),
    ("п. ", "п."),
    ("хутор ", "х."),
    ("х. ", "х."),
    ("станица ", "ст-ца"),
    ("ст-ца ", "ст-ца"),
    ("город ", ""),
    ("г. ", ""),
)
_CITY_SUFFIX_FIX = {"пгт.": "пгт", "ст.": "ст-ца", "станица": "ст-ца", "село": "с.", "хутор": "х.", "поселок": "п."}


def normalize_city(value: object) -> str | None:
    """«пгт Дагомыс», «Дагомыс пгт.» → «Дагомыс пгт»; «село Сукко» → «Сукко с.»."""
    if value is None:
        return None
    raw = " ".join(str(value).split())
    if not raw:
        return None
    low = raw.lower()
    for prefix, kind in _CITY_PREFIX:
        if low.startswith(prefix):
            name = raw[len(prefix):].strip()
            return f"{name} {kind}".strip() if kind else name
    head, _, tail = raw.rpartition(" ")
    if head and tail.lower() in _CITY_SUFFIX_FIX:
        return f"{head} {_CITY_SUFFIX_FIX[tail.lower()]}"
    return raw


_DISTRICT_FIX = {
    "м.о. Анапа": "Анапа м.о.",
    "с. Супсех": "Анапа м.о.",
    "Каневской м.о": "Каневской м.о.",
    "Крымский": "Крымск м.о.",
}


def normalize_district(value: object) -> str | None:
    if value is None:
        return None
    raw = " ".join(str(value).split())
    return _DISTRICT_FIX.get(raw, raw) or None


# Resort agglomerations of Краснодарский край by municipal district.
KUBAN_AGGLOMERATIONS = {
    "Анапа м.о.": "Анапа",
    "Сочи г.о.": "Сочи",
    "Адлерский р-н": "Сочи",
    "Лазаревский р-н": "Сочи",
    "Новороссийск м.о.": "Новороссийск",
    "Южный Новороссийск": "Новороссийск",
    "Геленджик г.о.": "Геленджик",
    "Туапсинский м.о.": "Туапсинский р-н",
    "Темрюк м.о.": "Темрюк / Тамань",
    "Горячий ключ г.о.": "Горячий Ключ",
}
KUBAN_OTHER = "Кубань: другие города"


def normalize_places(df: pl.DataFrame) -> pl.DataFrame:
    """Unify city / district spellings across exports and assign agglomerations."""
    if df.is_empty():
        return df
    df = df.with_columns(
        pl.col("city").map_elements(normalize_city, return_dtype=pl.Utf8).alias("city"),
        pl.col("loc_district").map_elements(normalize_district, return_dtype=pl.Utf8).alias("loc_district"),
    )
    by_district = pl.col("loc_district").replace_strict(KUBAN_AGGLOMERATIONS, default=None, return_dtype=pl.Utf8)
    by_city = (
        pl.when(pl.col("city").is_in([normalize_city(c) for c in ANAPA_CITIES]))
        .then(pl.lit("Анапа"))
        .when(pl.col("city").is_in([normalize_city(c) for c in SOCHI_CITIES]))
        .then(pl.lit("Сочи"))
        .when(pl.col("city") == "Новороссийск")
        .then(pl.lit("Новороссийск"))
        .otherwise(None)
    )
    return df.with_columns(
        pl.when(pl.col("source") == "crimea")
        .then(pl.lit("Крым"))
        .when(pl.col("source") == "adygea")
        .then(pl.lit("Адыгея"))
        .otherwise(pl.coalesce(by_district, by_city, pl.lit(KUBAN_OTHER)))
        .alias("agglomeration")
    )


_BANK_ALIASES = (
    ("сбербанк", "Сбербанк"),
    ("втб", "ВТБ"),
    ("альфа", "Альфа-Банк"),
    ("российский национальный", "РНКБ"),
    ("рнкб", "РНКБ"),
    ("совкомбанк", "Совкомбанк"),
    ("промсвязьбанк", "ПСБ"),
    ("газпромбанк", "Газпромбанк"),
    ("россельхоз", "Россельхозбанк"),
    ("дом.рф", "Банк ДОМ.РФ"),
    ("дом рф", "Банк ДОМ.РФ"),
    ("райффайзен", "Райффайзенбанк"),
    ("кубань кредит", "Кубань Кредит"),
    ("аб россия", "Банк «Россия»"),
    ("ab россия", "Банк «Россия»"),
    ("открытие", "Открытие"),
    ("уралсиб", "Уралсиб"),
    ("московский кредитный", "МКБ"),
    ("центр-инвест", "Центр-инвест"),
    ("генбанк", "Генбанк"),
    ("т-банк", "Т-Банк"),
    ("тинькофф", "Т-Банк"),
)


def normalize_bank(value: object) -> str | None:
    """Collapse legal-form and spelling variants of the same bank into one name."""
    if value is None:
        return None
    raw = " ".join(str(value).split())
    if not raw or raw in {"-", "—", "0", "nan", "None"}:
        return None
    low = raw.lower().replace("ё", "е")
    for needle, name in _BANK_ALIASES:
        if needle in low:
            return name
    for prefix in ("пао ", "ао ", "ооо ", "оао ", "зао ", "кб ", "акб "):
        if low.startswith(prefix):
            raw = raw[len(prefix):]
            low = low[len(prefix):]
    return raw.strip(" «»\"") or None


@lru_cache(maxsize=1)
def load_combined_deals() -> pl.DataFrame:
    source_paths = _collect_source_paths()
    fingerprint = _fingerprint_paths(source_paths)

    cached = _read_combined_cache()
    if cached is not None:
        return cached

    if not source_paths:
        if COMBINED_CACHE_PATH.exists():
            return pl.read_parquet(COMBINED_CACHE_PATH)
        return pl.DataFrame()

    df = _load_combined_deals_from_csv()
    if not df.is_empty() and _can_write_cache():
        _write_combined_cache(df, fingerprint)
    return df


def load_deals(cfg: Optional[DataConfig] = None) -> pl.DataFrame:
    cfg = cfg or DataConfig(data_path=resolve_data_path())

    if _csv_has_bnmap_columns(cfg.data_path):
        return load_bnmap_deals(cfg.data_path, force_crimea_agglomeration=False)

    df = pl.read_csv(
        cfg.data_path,
        columns=[c for c in ANALYTIC_USE_COLS if c in _csv_header_columns(cfg.data_path)] or None,
        try_parse_dates=False,
        ignore_errors=True,
    )

    # Normalize schema we care about (some columns may contain nulls/empties).
    df = df.with_columns(
        [
            pl.col("object").cast(pl.Utf8).alias("object"),
            pl.col("city").cast(pl.Utf8).alias("city"),
            pl.col("loc_district").cast(pl.Utf8).alias("loc_district"),
            pl.col("developer").cast(pl.Utf8).alias("developer"),
            pl.col("type_lot").cast(pl.Utf8).alias("type_lot"),
            pl.col("date_sold").cast(pl.Utf8).alias("date_sold"),
            pl.col("ipoteka").cast(pl.Utf8).alias("ipoteka"),
            pl.col("est_budget").cast(pl.Float64, strict=False).alias("est_budget"),
            pl.col("price_square_r").cast(pl.Float64, strict=False).alias("price_sqm"),
            pl.col("do_square").cast(pl.Float64, strict=False).alias("area_sqm"),
            pl.lit(None).cast(pl.Float64).alias("floor_num"),
            pl.lit(None).cast(pl.Float64).alias("rooms_count"),
            (pl.col("bank_name").cast(pl.Utf8) if "bank_name" in df.columns else pl.lit(None).cast(pl.Utf8)).alias("bank"),
            (
                pl.col("ipoteka_month").cast(pl.Float64, strict=False)
                if "ipoteka_month" in df.columns
                else pl.lit(None).cast(pl.Float64)
            ).alias("mortgage_months"),
            (pl.col("class").cast(pl.Utf8) if "class" in df.columns else pl.lit(None).cast(pl.Utf8)).alias("class"),
            pl.lit(None).cast(pl.Date).alias("sales_start"),
            pl.lit(None).cast(pl.Float64).alias("exposure_days"),
        ]
    )

    # date_sold is expected to be YYYY-MM-DD.
    df = df.with_columns(
        [
            pl.col("date_sold")
            .str.strptime(pl.Date, format="%Y-%m-%d", strict=False)
            .alias("sold_date"),
        ]
    )

    df = df.with_columns(
        [
            pl.col("sold_date").dt.year().alias("year"),
            pl.col("sold_date").dt.month().alias("month"),
            pl.col("sold_date").dt.strftime("%Y-%m").alias("sold_month"),
        ]
    )

    df = df.with_columns(
        [
            (pl.col("ipoteka") == "Ипотека").fill_null(False).alias("is_mortgage"),
            pl.when(pl.col("price_sqm").is_not_null() & (pl.col("price_sqm") > 0))
            .then(pl.col("price_sqm"))
            .when(
                pl.col("est_budget").is_not_null()
                & (pl.col("est_budget") > 0)
                & pl.col("area_sqm").is_not_null()
                & (pl.col("area_sqm") > 0)
            )
            .then(pl.col("est_budget") / pl.col("area_sqm"))
            .otherwise(None)
            .alias("price_sqm"),
            pl.when(pl.col("city").is_in(list(ANAPA_CITIES)))
            .then(pl.lit("Анапа"))
            .when(pl.col("city").is_in(list(SOCHI_CITIES)))
            .then(pl.lit("Сочи"))
            .otherwise(pl.lit("без групп"))
            .alias("agglomeration"),
            pl.when(pl.col("type_lot").str.to_lowercase().fill_null("").str.contains("студ"))
            .then(pl.lit("Студии"))
            .otherwise(pl.lit("Не определено"))
            .alias("room_group"),
        ]
    )

    return df


def load_bnmap_deals(path: str, *, force_crimea_agglomeration: bool) -> pl.DataFrame:
    """
    bnMAP export (Russian column names) -> same schema as legacy `load_deals()` / Crimea loader.
    Dates: DD.MM.YYYY in «Дата договора».
    """
    header = _csv_header_columns(path)
    use_cols = [c for c in BNMAP_USE_COLS if c in header]
    exposure_col = next((c for c in header if c.startswith(BNMAP_EXPOSURE_PREFIX)), None)
    if exposure_col:
        use_cols.append(exposure_col)
    # Read everything as text: exports differ in which columns look numeric, and mixed
    # inferred types break merging several regions. Numbers are parsed explicitly below.
    df = pl.read_csv(
        path,
        columns=use_cols or None,
        try_parse_dates=False,
        ignore_errors=True,
        infer_schema_length=0,
    )

    def _num(col: str | None) -> pl.Expr:
        if not col or col not in df.columns:
            return pl.lit(None).cast(pl.Float64)
        return (
            pl.col(col)
            .cast(pl.Utf8)
            .str.replace_all(r"[\s\u00A0]", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
        )

    def _txt(col: str) -> pl.Expr:
        return pl.col(col).cast(pl.Utf8) if col in df.columns else pl.lit(None).cast(pl.Utf8)

    extra = [
        _txt("ID лота").alias("lot_id"),
        _txt("Залогодержатель/Банк").alias("bank"),
        _num("Кол-во месяцев обременения").alias("mortgage_months"),
        _txt("Класс").alias("class"),
        _num(exposure_col).alias("exposure_days"),
        (
            pl.col("Старт продаж")
            .cast(pl.Utf8)
            .str.strptime(pl.Date, format="%d.%m.%Y", strict=False)
            .fill_null(pl.col("Старт продаж").cast(pl.Utf8).str.slice(0, 10).str.strptime(pl.Date, format="%Y-%m-%d", strict=False))
            if "Старт продаж" in df.columns
            else pl.lit(None).cast(pl.Date)
        ).alias("sales_start"),
    ]

    is_crimea_loc = (
        pl.col("Локация").cast(pl.Utf8).fill_null("").str.contains("Крым")
        if "Локация" in df.columns
        else pl.lit(False)
    )

    df = df.with_columns(
        [
            pl.col("Проект").cast(pl.Utf8).alias("object"),
            pl.col("Город").cast(pl.Utf8).alias("city"),
            pl.col("Район").cast(pl.Utf8).alias("loc_district"),
            pl.col("Девелопер").cast(pl.Utf8).alias("developer"),
            pl.col("Тип объекта").cast(pl.Utf8).alias("type_lot"),
            pl.col("Дата договора").cast(pl.Utf8).alias("date_sold_raw"),
            pl.col("Тип ипотеки").cast(pl.Utf8).alias("ipoteka_raw"),
            pl.col("Тип сделки").cast(pl.Utf8).alias("deal_status"),
            pl.col("Цена за кв. метр")
            .cast(pl.Utf8)
            .str.replace_all(r"[\s\u00A0]", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
            .alias("price_sqm"),
            pl.col("Расчетный бюджет объекта")
            .cast(pl.Utf8)
            .str.replace_all(r"[\s\u00A0]", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
            .alias("est_budget"),
            pl.col("Площадь согласно ПД")
            .cast(pl.Utf8)
            .str.replace_all(r"[\s\u00A0]", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
            .alias("area_pd"),
            pl.col("Площадь согласно ЕГРН")
            .cast(pl.Utf8)
            .str.replace_all(r"[\s\u00A0]", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
            .alias("area_egrn"),
            pl.col("Этаж")
            .cast(pl.Utf8)
            .str.replace_all(r"[\s\u00A0]", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
            .alias("floor_num"),
            pl.col("Количество комнат")
            .cast(pl.Utf8)
            .str.replace_all(r"[\s\u00A0]", "")
            .str.replace_all(",", ".")
            .cast(pl.Float64, strict=False)
            .alias("rooms_count"),
            *extra,
        ]
    )

    df = df.with_columns(
        [
            pl.col("date_sold_raw")
            .str.strptime(pl.Date, format="%d.%m.%Y", strict=False)
            .fill_null(pl.col("date_sold_raw").str.strptime(pl.Date, format="%Y-%m-%d", strict=False))
            .alias("sold_date"),
        ]
    )

    if force_crimea_agglomeration:
        agg = pl.lit("Крым").alias("agglomeration")
    else:
        agg = (
            pl.when(pl.col("city").is_in(list(ANAPA_CITIES)))
            .then(pl.lit("Анапа"))
            .when(pl.col("city").is_in(list(SOCHI_CITIES)))
            .then(pl.lit("Сочи"))
            .when(is_crimea_loc)
            .then(pl.lit("Крым"))
            .otherwise(pl.lit("без групп"))
            .alias("agglomeration")
        )

    df = df.with_columns(
        [
            pl.col("sold_date").dt.year().alias("year"),
            pl.col("sold_date").dt.month().alias("month"),
            pl.col("sold_date").dt.strftime("%Y-%m").alias("sold_month"),
            (pl.col("ipoteka_raw") == "Ипотека").fill_null(False).alias("is_mortgage"),
            agg,
            pl.when(pl.col("area_pd").is_not_null() & (pl.col("area_pd") > 0))
            .then(pl.col("area_pd"))
            .otherwise(pl.col("area_egrn"))
            .alias("area_sqm"),
            pl.col("ipoteka_raw").cast(pl.Utf8).alias("ipoteka"),
            pl.when(pl.col("rooms_count").is_null())
            .then(
                pl.when(pl.col("type_lot").str.to_lowercase().fill_null("").str.contains("студ"))
                .then(pl.lit("Студии"))
                .otherwise(pl.lit("Не определено"))
            )
            .when(pl.col("rooms_count") <= 0)
            .then(pl.lit("Студии"))
            .when(pl.col("rooms_count") < 1.5)
            .then(pl.lit("1-комнатные"))
            .when(pl.col("rooms_count") < 2.5)
            .then(pl.lit("2-комнатные"))
            .when(pl.col("rooms_count") < 3.5)
            .then(pl.lit("3-комнатные"))
            .otherwise(pl.lit("4+ комнатные"))
            .alias("room_group"),
        ]
    )

    df = df.with_columns(
        [
            pl.when(pl.col("price_sqm").is_not_null() & (pl.col("price_sqm") > 0))
            .then(pl.col("price_sqm"))
            .when(
                pl.col("est_budget").is_not_null()
                & (pl.col("est_budget") > 0)
                & pl.col("area_sqm").is_not_null()
                & (pl.col("area_sqm") > 0)
            )
            .then(pl.col("est_budget") / pl.col("area_sqm"))
            .otherwise(None)
            .alias("price_sqm"),
        ]
    )

    df = df.drop(["date_sold_raw", "ipoteka_raw", "area_pd", "area_egrn"], strict=False)
    return df


def load_crimea_deals(path: Optional[str] = None) -> pl.DataFrame:
    """
    Loads bnMAP Crimea deals export (CSV) and normalizes to the same schema as `load_deals()`.
    Expected columns (RU): Проект, Город, Район, Девелопер, Тип объекта, Дата договора, Тип ипотеки, Расчетный бюджет объекта
    """
    p = path or resolve_crimea_path()
    return load_bnmap_deals(p, force_crimea_agglomeration=True)


def list_sorted(values: Iterable[str]) -> list[str]:
    uniq = sorted({v for v in values if v is not None and str(v).strip() != ""})
    return uniq

