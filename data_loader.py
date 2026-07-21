from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import polars as pl

CRIMEA_PATH_DEFAULT = "july2026.csv"
MAIN_DATA_DEFAULT = "july2026.csv"
ANALYTIC_PATH_DEFAULT = "Analitic.csv"
KK2026_PATH_DEFAULT = "KK2026.csv"
# Newer bnMAP exports first; only one is loaded unless BNMAP_EXPORT_PATHS is set.
BNMAP_EXPORT_CANDIDATES = ("july2026.csv", "june2026.csv", "may2026.csv")

CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"
COMBINED_CACHE_PATH = CACHE_DIR / "combined_deals.parquet"
COMBINED_CACHE_META_PATH = CACHE_DIR / "combined_deals.meta"

BNMAP_USE_COLS = (
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
)

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
    bnMAP CSV paths to load. By default picks the newest available export (july2026 > june2026 > may2026).
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


def _collect_source_paths() -> list[str]:
    paths: list[str] = []
    paths.extend(resolve_bnmap_export_paths())
    analitic_path = resolve_analitic_path()
    if Path(analitic_path).exists():
        paths.append(analitic_path)
    kk2026_path = resolve_kk2026_path()
    if kk2026_path:
        paths.append(kk2026_path)
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
        str(Path.home() / "Downloads" / "KK2026.csv"),
    )
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _load_combined_deals_from_csv() -> pl.DataFrame:
    """Load bnMAP exports, Analitic, KK2026 (Краснодарский край), and optional Crimea."""
    frames: list[pl.DataFrame] = []
    bnmap_paths = resolve_bnmap_export_paths()
    analitic_path = resolve_analitic_path()
    crimea_path = resolve_crimea_path()

    loaded_paths: list[str] = []
    for bnmap_path in bnmap_paths:
        frames.append(
            load_deals(DataConfig(data_path=bnmap_path)).with_columns(
                pl.lit(_source_tag_for_path(bnmap_path)).alias("source")
            )
        )
        loaded_paths.append(bnmap_path)

    if Path(analitic_path).exists() and not any(
        paths_point_to_same_file(analitic_path, p) for p in loaded_paths
    ):
        frames.append(
            load_deals(DataConfig(data_path=analitic_path)).with_columns(pl.lit("analitic").alias("source"))
        )

    kk2026_path = resolve_kk2026_path()
    if kk2026_path and not any(paths_point_to_same_file(kk2026_path, p) for p in loaded_paths):
        same_as_analitic = paths_point_to_same_file(kk2026_path, analitic_path)
        if not same_as_analitic:
            frames.append(
                load_deals(DataConfig(data_path=kk2026_path)).with_columns(pl.lit("kk2026").alias("source"))
            )
            loaded_paths.append(kk2026_path)

    if Path(crimea_path).exists():
        same_as_loaded = any(paths_point_to_same_file(crimea_path, p) for p in loaded_paths)
        same_as_analitic = paths_point_to_same_file(crimea_path, analitic_path)
        if not same_as_loaded and not same_as_analitic:
            try:
                frames.append(
                    load_crimea_deals(crimea_path).with_columns(pl.lit("crimea").alias("source"))
                )
            except Exception:
                pass

    if not frames:
        return pl.DataFrame()

    return pl.concat(frames, how="diagonal")


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
    df = pl.read_csv(
        path,
        columns=use_cols or None,
        try_parse_dates=False,
        ignore_errors=True,
    )

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

