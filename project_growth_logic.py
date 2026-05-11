from __future__ import annotations

import polars as pl

from aggregations import apply_filters


def _normalize_multi_str(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for x in value:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    s = str(value).strip()
    return [s] if s else []


def _dash_year(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filter_project_growth_deals(
    df: pl.DataFrame,
    *,
    deals_source: str,
    year: object,
    agglomeration: str,
    cities_sel: object,
    districts_sel: object,
    type_lot_sel: object,
    mortgage_mode: str,
    data_quality_flags: object = None,
) -> pl.DataFrame:
    flags = set(_normalize_multi_str(data_quality_flags))
    dff = df
    if deals_source and deals_source != "all":
        dff = dff.filter(pl.col("source") == deals_source)

    y = _dash_year(year)
    if y is not None:
        dff = dff.filter(pl.col("year") == y)

    if agglomeration and agglomeration != "all":
        dff = dff.filter(pl.col("agglomeration") == agglomeration)

    districts = _normalize_multi_str(districts_sel)
    if districts:
        dff = dff.filter(pl.col("loc_district").is_in(districts))

    filtered = apply_filters(
        dff,
        years=None,
        months=None,
        agglomeration=None,
        cities=_normalize_multi_str(cities_sel) or None,
        mortgage_mode=mortgage_mode,
        sources=None,
        developers=None,
        type_lots=_normalize_multi_str(type_lot_sel) or None,
    )

    if "exclude_wholesale" in flags and "Участие объекта в оптовой сделке" in filtered.columns:
        filtered = filtered.filter(
            ~pl.col("Участие объекта в оптовой сделке")
            .cast(pl.Utf8, strict=False)
            .str.to_lowercase()
            .fill_null("")
            .str.contains("да")
        )

    if "known_budget_only" in flags:
        filtered = filtered.filter(pl.col("est_budget").is_not_null() & (pl.col("est_budget") > 0))

    return filtered


def project_growth_dimension_options(
    df: pl.DataFrame,
    *,
    deals_source: str,
    agglomeration: str,
    year: int | None,
) -> tuple[list[str], list[str], list[str]]:
    dff = df
    if deals_source and deals_source != "all":
        dff = dff.filter(pl.col("source") == deals_source)
    y = _dash_year(year)
    if y is not None:
        dff = dff.filter(pl.col("year") == y)
    if agglomeration and agglomeration != "all":
        dff = dff.filter(pl.col("agglomeration") == agglomeration)

    def _list_sorted(values: list[object]) -> list[str]:
        return sorted({str(v) for v in values if v is not None and str(v).strip() != ""})

    cities = _list_sorted(dff.select("city").unique().to_series().to_list())
    districts = _list_sorted(dff.select("loc_district").unique().to_series().to_list())
    types = _list_sorted(dff.select("type_lot").unique().to_series().to_list())
    return cities, districts, types


def compute_project_growth(dff: pl.DataFrame) -> pl.DataFrame:
    dff = dff.filter(pl.col("object").is_not_null() & (pl.col("object") != ""))
    dff = dff.filter(pl.col("sold_month").is_not_null())
    dff = dff.filter(pl.col("est_budget").is_not_null() & (pl.col("est_budget") > 0))
    dff = dff.filter(pl.col("price_sqm").is_not_null() & (pl.col("price_sqm") > 0))

    if dff.is_empty():
        return pl.DataFrame()

    monthly = (
        dff.group_by(["object", "sold_month"])
        .agg(
            [
                pl.mean("est_budget").alias("avg_budget"),
                pl.mean("price_sqm").alias("avg_price_sqm"),
                pl.len().alias("deals"),
            ]
        )
        .sort(["object", "sold_month"])
    )

    return (
        monthly.group_by("object")
        .agg(
            [
                pl.first("avg_budget").alias("first_budget"),
                pl.last("avg_budget").alias("last_budget"),
                pl.first("avg_price_sqm").alias("first_sqm"),
                pl.last("avg_price_sqm").alias("last_sqm"),
                pl.first("sold_month").alias("first_month"),
                pl.last("sold_month").alias("last_month"),
                pl.sum("deals").alias("deals_total"),
            ]
        )
        .with_columns(
            [
                (pl.col("last_budget") - pl.col("first_budget")).alias("growth_budget_abs"),
                ((pl.col("last_budget") / pl.col("first_budget") - 1) * 100).alias("growth_budget_pct"),
                (pl.col("last_sqm") - pl.col("first_sqm")).alias("growth_sqm_abs"),
                ((pl.col("last_sqm") / pl.col("first_sqm") - 1) * 100).alias("growth_sqm_pct"),
            ]
        )
        .filter(pl.col("first_budget") > 0)
        .filter(pl.col("first_sqm") > 0)
    )


def compute_room_growth(dff: pl.DataFrame) -> pl.DataFrame:
    dff = dff.filter(pl.col("room_group").is_not_null())
    if dff.is_empty():
        return pl.DataFrame()

    room_monthly = (
        dff.group_by(["room_group", "sold_month"])
        .agg(pl.mean("price_sqm").alias("avg_price_sqm"))
        .sort(["room_group", "sold_month"])
    )
    return (
        room_monthly.group_by("room_group")
        .agg(
            [
                pl.first("avg_price_sqm").alias("first_sqm"),
                pl.last("avg_price_sqm").alias("last_sqm"),
            ]
        )
        .filter(pl.col("first_sqm") > 0)
        .with_columns(((pl.col("last_sqm") / pl.col("first_sqm") - 1) * 100).alias("growth_pct"))
        .sort("growth_pct", descending=True)
    )

