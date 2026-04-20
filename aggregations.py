from __future__ import annotations

import polars as pl


def apply_filters(
    df: pl.DataFrame,
    *,
    years: list[int] | None,
    months: list[str] | None,
    agglomeration: str | None,
    cities: list[str] | None,
    mortgage_mode: str | None,  # "all" | "mortgage" | "non_mortgage"
    sources: list[str] | None,  # ["main", "crimea"]
    developers: list[str] | None,
    type_lots: list[str] | None,
) -> pl.DataFrame:
    out = df

    if sources:
        out = out.filter(pl.col("source").is_in(sources))

    if years:
        out = out.filter(pl.col("year").is_in(years))

    if months:
        out = out.filter(pl.col("sold_month").is_in(months))

    if agglomeration and agglomeration != "all":
        out = out.filter(pl.col("agglomeration") == agglomeration)

    if cities:
        out = out.filter(pl.col("city").is_in(cities))

    if mortgage_mode == "mortgage":
        out = out.filter(pl.col("is_mortgage") == True)  # noqa: E712
    elif mortgage_mode == "non_mortgage":
        out = out.filter(pl.col("is_mortgage") == False)  # noqa: E712

    if developers:
        out = out.filter(pl.col("developer").is_in(developers))

    if type_lots:
        out = out.filter(pl.col("type_lot").is_in(type_lots))

    return out


def monthly_deal_counts(df: pl.DataFrame) -> pl.DataFrame:
    base = (
        df.group_by("sold_month")
        .agg(
            [
                pl.len().alias("deals_total"),
                pl.sum("is_mortgage").cast(pl.Int64).alias("deals_mortgage"),
            ]
        )
        .with_columns((pl.col("deals_total") - pl.col("deals_mortgage")).alias("deals_non_mortgage"))
        .sort("sold_month")
    )
    return base


def monthly_avg_price(df: pl.DataFrame) -> pl.DataFrame:
    # Exclude zeros from mean; keep counts for hover.
    clean = df.filter(pl.col("est_budget").is_not_null())
    clean_nonzero = clean.filter(pl.col("est_budget") > 0)

    out = (
        clean_nonzero.group_by("sold_month")
        .agg(
            [
                pl.len().alias("deals_with_price"),
                pl.mean("est_budget").alias("avg_est_budget"),
                pl.sum("est_budget").alias("sum_est_budget"),
            ]
        )
        .sort("sold_month")
    )
    return out


def city_deal_counts(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by("city")
        .agg(pl.len().alias("deals"))
        .sort("deals", descending=True)
    )


def complex_monthly_counts(df: pl.DataFrame, *, complex_name: str) -> pl.DataFrame:
    base = df.filter(pl.col("object") == complex_name)
    return (
        base.group_by("sold_month")
        .agg(pl.len().alias("deals"))
        .sort("sold_month")
    )


def complex_comparison_metrics(df: pl.DataFrame) -> pl.DataFrame:
    """
    Compare complexes by purchasing power proxies:
    - average deal budget
    - average price per sqm
    """
    clean = df.filter(pl.col("est_budget").is_not_null() & (pl.col("est_budget") > 0))
    return (
        clean.group_by("object")
        .agg(
            [
                pl.len().alias("deals"),
                pl.mean("est_budget").alias("avg_budget"),
                pl.mean("price_sqm").alias("avg_price_sqm"),
                pl.first("developer").alias("developer"),
                pl.first("city").alias("city"),
            ]
        )
        .sort("avg_budget", descending=True)
    )


def yearly_top_complexes(df: pl.DataFrame, *, year: int, only_mortgage: bool) -> pl.DataFrame:
    base = df.filter(pl.col("year") == year)
    if only_mortgage:
        base = base.filter(pl.col("is_mortgage") == True)  # noqa: E712

    out = (
        base.group_by("object")
        .agg(pl.len().alias("deals"))
        .sort("deals", descending=True)
    )
    return out


def kpis(df: pl.DataFrame) -> dict[str, float]:
    total_deals = float(df.height)
    sum_budget = float(df.select(pl.col("est_budget").fill_null(0).sum()).item())
    avg_budget = float(
        df.filter(pl.col("est_budget").is_not_null() & (pl.col("est_budget") > 0))
        .select(pl.col("est_budget").mean())
        .item()
        or 0.0
    )
    return {"total_deals": total_deals, "sum_budget": sum_budget, "avg_budget": avg_budget}

