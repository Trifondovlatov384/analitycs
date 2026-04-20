from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional

import polars as pl

CRIMEA_PATH_DEFAULT = "bnMAP_pro_Сделки_Республика_Крым_10-04-2026_11-16_part1.xlsx - Sheet1.csv"

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
    return "Analitic.csv"


def resolve_crimea_path() -> str:
    env_path = os.environ.get("CRIMEA_DEALS_PATH")
    if env_path:
        return env_path
    return CRIMEA_PATH_DEFAULT


def load_deals(cfg: Optional[DataConfig] = None) -> pl.DataFrame:
    cfg = cfg or DataConfig(data_path=resolve_data_path())

    df = pl.read_csv(
        cfg.data_path,
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
        ]
    )

    return df


def load_crimea_deals(path: Optional[str] = None) -> pl.DataFrame:
    """
    Loads bnMAP Crimea deals export (CSV) and normalizes to the same schema as `load_deals()`.
    Expected columns (RU): Проект, Город, Район, Девелопер, Тип объекта, Дата договора, Тип ипотеки, Расчетный бюджет объекта
    """
    p = path or resolve_crimea_path()
    df = pl.read_csv(p, try_parse_dates=False, ignore_errors=True)

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
        ]
    )

    # Parse date: expected DD.MM.YYYY
    df = df.with_columns(
        [
            pl.col("date_sold_raw")
            .str.strptime(pl.Date, format="%d.%m.%Y", strict=False)
            .alias("sold_date"),
        ]
    )

    df = df.with_columns(
        [
            pl.col("sold_date").dt.year().alias("year"),
            pl.col("sold_date").dt.month().alias("month"),
            pl.col("sold_date").dt.strftime("%Y-%m").alias("sold_month"),
            (pl.col("ipoteka_raw") == "Ипотека").fill_null(False).alias("is_mortgage"),
            pl.lit("Крым").alias("agglomeration"),
        ]
    )

    df = df.drop(["date_sold_raw", "ipoteka_raw"], strict=False)
    return df


def list_sorted(values: Iterable[str]) -> list[str]:
    uniq = sorted({v for v in values if v is not None and str(v).strip() != ""})
    return uniq

