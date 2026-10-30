from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl
from flask import Request

from aggregations import apply_filters
from data_loader import list_sorted

SOURCE_LABELS = {
    "analitic": "Analitic",
    "crimea": "Крым",
    "kk2026": "Краснодарский край",
    "august2026": "Крым (bnMAP)",
}


def multi(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return [p for p in parts if p]
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


def parse_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_year(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_budget_mln(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        mln = float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None
    if mln < 0:
        return None
    return mln * 1_000_000.0


def period_years(year: object, date_from: object, date_to: object) -> list[int] | None:
    if parse_date(date_from) is not None or parse_date(date_to) is not None:
        return None
    y = parse_year(year)
    return [y] if y is not None else None


def filter_by_source(dff: pl.DataFrame, deals_source: str | None) -> pl.DataFrame:
    if not deals_source or deals_source == "all":
        return dff
    if deals_source == "main":
        return dff.filter(pl.col("source") != "analitic")
    return dff.filter(pl.col("source") == deals_source)


def slice_by_period(dff: pl.DataFrame, year: object, date_from: object, date_to: object) -> pl.DataFrame:
    d0 = parse_date(date_from)
    d1 = parse_date(date_to)
    if d0 is not None:
        dff = dff.filter(pl.col("sold_date") >= d0)
    if d1 is not None:
        dff = dff.filter(pl.col("sold_date") <= d1)
    elif d0 is None and d1 is None:
        y = parse_year(year)
        if y is not None:
            dff = dff.filter(pl.col("year") == y)
    return dff


def _int(value: object, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    """Parse an int query param without ever raising (bad input → default)."""
    try:
        n = int(float(str(value).replace(" ", "").replace(",", ".")))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def args_from_request(req: Request) -> dict[str, Any]:
    g = req.args.get
    return {
        "source": g("source") or "all",
        "agglomeration": g("agglomeration") or "all",
        "year": parse_year(g("year")),
        "date_from": parse_date(g("date_from")),
        "date_to": parse_date(g("date_to")),
        "months": multi(g("months")),
        "city": multi(g("city")),
        "developer": multi(g("developer")),
        "project": multi(g("project")),
        "type_lot": multi(g("type_lot")),
        "mortgage_mode": g("mortgage_mode") or "all",
        "budget_min": parse_budget_mln(g("budget_min")),
        "budget_max": parse_budget_mln(g("budget_max")),
        "object": (g("object") or "").strip() or None,
        "month": (g("month") or "").strip() or None,
        "sold_month": (g("sold_month") or "").strip() or None,
        "district": multi(g("district")),
        "selected": multi(g("selected")),
        "top_n": _int(g("top_n"), 40, lo=5, hi=200),
        "line_shape": g("line_shape") or "linear",
        "data_quality": multi(g("data_quality")),
        "h_source": g("h_source") or "deals",
        "target_budget": _int(g("target_budget"), 8_000_000, lo=0),
        "delta_budget": _int(g("delta_budget"), 3_000_000, lo=0),
        "type_lot_single": (g("type_lot_single") or "").strip() or None,
        "projects": multi(g("projects"))[:3],
        "search": (g("search") or "").strip() or None,
        "region": multi(g("region")),
        "work_type": multi(g("work_type")),
        "access": (g("access") or "").strip() or None,
        "pace_window": _int(g("pace_window"), 3, lo=1, hi=12),
        "gran": "quarter" if g("gran") == "quarter" else "month",
    }


def filtered_deals(df: pl.DataFrame, a: dict[str, Any], *, use_mortgage: bool = True) -> pl.DataFrame:
    dff = filter_by_source(df, a.get("source"))
    years = period_years(a.get("year"), a.get("date_from"), a.get("date_to"))
    sources = None if (not a.get("source") or a["source"] == "all") else [a["source"]]
    return apply_filters(
        dff,
        years=years,
        months=a.get("months") or None,
        agglomeration=a.get("agglomeration"),
        cities=a.get("city") or None,
        mortgage_mode=a.get("mortgage_mode") if use_mortgage else "all",
        sources=sources,
        developers=a.get("developer") or None,
        type_lots=a.get("type_lot") or None,
        date_from=a.get("date_from"),
        date_to=a.get("date_to"),
        budget_min=a.get("budget_min"),
        budget_max=a.get("budget_max"),
        objects=a.get("project") or None,
    )


def build_meta(df: pl.DataFrame, *, matrix: bool) -> dict:
    years = sorted(
        [int(y) for y in df.select("year").unique().drop_nulls().to_series().to_list()]
    ) if not df.is_empty() and "year" in df.columns else []
    sources = sorted(
        {str(s) for s in df.select("source").drop_nulls().to_series().to_list() if str(s).strip()}
    ) if not df.is_empty() and "source" in df.columns else []

    if not sources:
        source_meta = {"options": [], "default": None, "show": False}
    elif len(sources) == 1:
        s = sources[0]
        source_meta = {
            "options": [{"label": SOURCE_LABELS.get(s, s), "value": s}],
            "default": s,
            "show": False,
        }
    else:
        opts = [{"label": "Все", "value": "all"}]
        opts.extend({"label": SOURCE_LABELS.get(s, s), "value": s} for s in sources)
        source_meta = {"options": opts, "default": "all", "show": True}

    bounds = {"min": None, "max": None}
    if not df.is_empty() and "sold_date" in df.columns:
        row = df.select(
            pl.col("sold_date").min().alias("min_d"),
            pl.col("sold_date").max().alias("max_d"),
        ).row(0, named=True)
        min_d, max_d = row.get("min_d"), row.get("max_d")
        bounds = {
            "min": min_d.isoformat() if min_d is not None else None,
            "max": max_d.isoformat() if max_d is not None else None,
        }

    source_bounds = []
    if not df.is_empty() and "source" in df.columns:
        for r in (
            df.group_by("source")
            .agg(pl.col("sold_date").min().alias("mn"), pl.col("sold_date").max().alias("mx"))
            .sort("mx", descending=True)
            .iter_rows(named=True)
        ):
            source_bounds.append(
                {
                    "source": r["source"],
                    "label": SOURCE_LABELS.get(r["source"], r["source"]),
                    "min": r["mn"].isoformat() if r["mn"] else None,
                    "max": r["mx"].isoformat() if r["mx"] else None,
                }
            )

    return {
        "source_bounds": source_bounds,
        "years": years,
        "default_year": years[-1] if years else None,
        "sources": source_meta,
        "date_bounds": bounds,
        "matrix_available": matrix,
    }


def dimension_options(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    dff = filter_by_source(df, a.get("source"))
    dff = slice_by_period(dff, a.get("year"), a.get("date_from"), a.get("date_to"))
    if a.get("agglomeration") and a["agglomeration"] != "all":
        dff = dff.filter(pl.col("agglomeration") == a["agglomeration"])

    cities = list_sorted(dff.select("city").unique().to_series().to_list()) if not dff.is_empty() else []
    developers = list_sorted(dff.select("developer").unique().to_series().to_list()) if not dff.is_empty() else []
    lots = list_sorted(dff.select("type_lot").unique().to_series().to_list()) if not dff.is_empty() else []
    months = list_sorted(dff.select("sold_month").unique().to_series().to_list()) if not dff.is_empty() else []
    districts = (
        list_sorted(dff.select("loc_district").unique().drop_nulls().to_series().to_list())
        if not dff.is_empty() and "loc_district" in dff.columns
        else []
    )

    projects_df = dff
    selected_devs = a.get("developer") or []
    if selected_devs:
        projects_df = projects_df.filter(pl.col("developer").is_in(selected_devs))
    projects = (
        list_sorted(projects_df.select("object").unique().to_series().to_list())
        if not projects_df.is_empty()
        else []
    )

    return {
        "city": [{"label": c, "value": c} for c in cities],
        "developer": [{"label": d, "value": d} for d in developers],
        "project": [{"label": p, "value": p} for p in projects],
        "object": [{"label": p, "value": p} for p in projects],
        "type_lot": [{"label": t, "value": t} for t in lots],
        "months": [{"label": m, "value": m} for m in months],
        "district": [{"label": d, "value": d} for d in districts],
        "year": [{"label": str(y), "value": y} for y in sorted({int(x) for x in (dff.select("year").unique().drop_nulls().to_series().to_list() if not dff.is_empty() else [])})],
    }
