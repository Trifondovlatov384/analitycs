from __future__ import annotations

from typing import Any

import polars as pl

from aggregations import (
    city_deal_counts,
    complex_comparison_metrics,
    complex_monthly_counts,
    kpis,
    monthly_avg_price,
    monthly_deal_counts,
    yearly_top_complexes,
)
from services.filters import filtered_deals, filter_by_source, multi, parse_date, parse_year, slice_by_period


def fmt_int(n: float | int) -> str:
    return f"{int(n):,}".replace(",", " ")


def _kpi_numbers(frame: pl.DataFrame) -> dict[str, float | None]:
    """Core KPI numbers for a filtered slice of deals."""
    n = frame.height
    priced = frame.filter(pl.col("est_budget").is_not_null() & (pl.col("est_budget") > 0))
    sqm = (
        frame.filter(pl.col("price_sqm").is_not_null() & (pl.col("price_sqm") > 0))
        if "price_sqm" in frame.columns
        else frame.clear()
    )
    mortgage = int(frame.select(pl.col("is_mortgage").cast(pl.Int64).sum()).item() or 0) if n and "is_mortgage" in frame.columns else 0
    return {
        "total_deals": float(n),
        "sum_budget": float(priced.select(pl.col("est_budget").sum()).item() or 0) if priced.height else 0.0,
        "avg_budget": float(priced.select(pl.col("est_budget").mean()).item() or 0) if priced.height else None,
        "median_budget": float(priced.select(pl.col("est_budget").median()).item() or 0) if priced.height else None,
        "avg_sqm": float(sqm.select(pl.col("price_sqm").median()).item() or 0) if sqm.height else None,
        "mortgage_share": (mortgage / n * 100.0) if n else None,
    }


def _shift_year(d: Any, years: int = -1) -> Any:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


def _previous_period(df: pl.DataFrame, a: dict[str, Any], current: pl.DataFrame) -> pl.DataFrame | None:
    """Same period one year earlier (year-to-date aware), with all other filters kept."""
    d0, d1 = a.get("date_from"), a.get("date_to")
    if d0 is not None or d1 is not None:
        prev_args = {**a}
        if d0 is not None:
            prev_args["date_from"] = _shift_year(d0)
        if d1 is not None:
            prev_args["date_to"] = _shift_year(d1)
        return filtered_deals(df, prev_args, use_mortgage=True)
    year = parse_year(a.get("year"))
    if year is None or current.is_empty():
        return None
    prev = filtered_deals(df, {**a, "year": year - 1}, use_mortgage=True)
    # Compare like-for-like: if the current year is partial, cut last year at the same day.
    last_day = current.select(pl.col("sold_date").max()).item()
    if last_day is not None and not prev.is_empty():
        prev = prev.filter(pl.col("sold_date") <= _shift_year(last_day))
    return prev


def _delta_pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / prev * 100.0, 1)


def dashboard_kpi(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    current = filtered_deals(df, a, use_mortgage=True)
    k = _kpi_numbers(current)
    prev_frame = _previous_period(df, a, current)
    p = _kpi_numbers(prev_frame) if prev_frame is not None and not prev_frame.is_empty() else None

    out: dict[str, Any] = {
        # legacy formatted fields (kept for compatibility)
        "total_deals": fmt_int(k["total_deals"]),
        "sum_budget": fmt_int(k["sum_budget"]),
        "avg_budget": fmt_int(k["avg_budget"] or 0),
    }
    for key, val in k.items():
        out[f"{key}_raw"] = round(val, 1) if val is not None else None
        prev_val = p.get(key) if p else None
        out[f"{key}_prev"] = round(prev_val, 1) if prev_val is not None else None
        if key == "mortgage_share":
            out[f"{key}_delta"] = round(val - prev_val, 1) if val is not None and prev_val is not None else None
        else:
            out[f"{key}_delta"] = _delta_pct(val, prev_val)
    out["has_prev"] = p is not None
    return out


def dashboard_budget_buckets(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    """How many deals fall into each budget band — shows where demand sits."""
    base = filtered_deals(df, a, use_mortgage=True)
    edges = [0, 5, 8, 10, 12, 15, 20, 30, 50]
    labels = [f"{lo}–{hi}" for lo, hi in zip(edges, edges[1:])] + [f"{edges[-1]}+"]
    priced = base.filter(pl.col("est_budget").is_not_null() & (pl.col("est_budget") > 0))
    if priced.is_empty():
        return {"labels": labels, "values": [0] * len(labels), "shares": [0.0] * len(labels)}
    mln = priced.select((pl.col("est_budget") / 1_000_000).alias("m")).to_series().to_list()
    counts = [0] * len(labels)
    for v in mln:
        idx = len(edges) - 1
        for i in range(1, len(edges)):
            if v < edges[i]:
                idx = i - 1
                break
        counts[idx] += 1
    total = sum(counts) or 1
    return {
        "labels": labels,
        "values": counts,
        "shares": [round(c / total * 100, 1) for c in counts],
    }


def dashboard_monthly_sqm(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    base = filtered_deals(df, a, use_mortgage=True)
    if base.is_empty() or "price_sqm" not in base.columns:
        return {"labels": [], "median": []}
    m = (
        base.filter(pl.col("price_sqm").is_not_null() & (pl.col("price_sqm") > 0))
        .group_by("sold_month")
        .agg(pl.col("price_sqm").median().alias("median"))
        .sort("sold_month")
    )
    return {
        "labels": m["sold_month"].to_list(),
        "median": [round(float(x)) if x is not None else None for x in m["median"].to_list()],
    }


def dashboard_monthly_counts(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    base = filtered_deals(df, a, use_mortgage=False)
    m = monthly_deal_counts(base)
    if m.is_empty():
        return {"labels": [], "total": [], "mortgage": [], "non_mortgage": []}
    return {
        "labels": m["sold_month"].to_list(),
        "total": m["deals_total"].to_list(),
        "mortgage": m["deals_mortgage"].to_list(),
        "non_mortgage": m["deals_non_mortgage"].to_list(),
    }


def dashboard_monthly_avg(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    filtered = filtered_deals(df, a, use_mortgage=True)
    m = monthly_avg_price(filtered)
    if m.is_empty():
        return {"labels": [], "avg": []}
    return {
        "labels": m["sold_month"].to_list(),
        "avg": [round(float(x), 0) if x is not None else None for x in m["avg_est_budget"].to_list()],
    }


def dashboard_top_complexes(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    base = filtered_deals(df, a, use_mortgage=False)
    year = a.get("year")
    d0, d1 = a.get("date_from"), a.get("date_to")
    top_year = parse_year(year) if d0 is None and d1 is None else None
    if top_year is None and d0 is None and d1 is None:
        return {"total": [], "mortgage": [], "message": "Выберите год или период"}

    def pack(frame: pl.DataFrame) -> list[dict]:
        if frame.is_empty():
            return []
        return [
            {"name": str(r["object"]), "deals": int(r["deals"])}
            for r in frame.head(25).iter_rows(named=True)
        ]

    if top_year is not None:
        total = yearly_top_complexes(base, year=int(top_year), only_mortgage=False)
        mort = yearly_top_complexes(base, year=int(top_year), only_mortgage=True)
    else:  # explicit date range: rank within the range
        total = base.group_by("object").agg(pl.len().alias("deals")).sort("deals", descending=True)
        mort = (
            base.filter(pl.col("is_mortgage") == True)  # noqa: E712
            .group_by("object")
            .agg(pl.len().alias("deals"))
            .sort("deals", descending=True)
        )
    return {"total": pack(total), "mortgage": pack(mort), "year": top_year}


def complexes_city_counts(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    base = filtered_deals(df, a, use_mortgage=True)
    c = city_deal_counts(base)
    if c.is_empty():
        return {"labels": [], "values": []}
    head = c.head(40)
    return {"labels": head["city"].to_list(), "values": [int(x) for x in head["deals"].to_list()]}


def complexes_monthly(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    base = filtered_deals(df, a, use_mortgage=True)
    name = a.get("object")
    if not name:
        return {"labels": [], "values": [], "name": None}
    m = complex_monthly_counts(base, complex_name=name)
    if m.is_empty():
        return {"labels": [], "values": [], "name": name}
    return {
        "labels": m["sold_month"].to_list(),
        "values": [int(x) for x in m["deals"].to_list()],
        "name": name,
    }


def compare_data(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    base = filtered_deals(df, a, use_mortgage=True)
    cmp_df = complex_comparison_metrics(base).filter(
        pl.col("avg_price_sqm").is_not_null() & (pl.col("avg_price_sqm") > 0)
    )
    selected = set(a.get("selected") or [])
    rows = []
    points = []
    for r in cmp_df.head(300).iter_rows(named=True):
        name = str(r["object"])
        row = {
            "object": name,
            "city": r.get("city"),
            "developer": r.get("developer"),
            "deals": int(r["deals"]),
            "avg_budget": round(float(r["avg_budget"] or 0)),
            "avg_price_sqm": round(float(r["avg_price_sqm"] or 0)),
            "selected": name in selected,
        }
        rows.append(row)
        points.append(
            {
                "x": row["avg_price_sqm"],
                "y": row["avg_budget"],
                "name": name,
                "deals": row["deals"],
                "selected": row["selected"],
            }
        )
    if selected:
        filtered_rows = [r for r in rows if r["object"] in selected]
        if filtered_rows:
            rows = filtered_rows
    return {"points": points, "rows": rows}


def _heatmap_from_deals(filtered: pl.DataFrame, top_n: int) -> dict:
    from data_loader import list_sorted
    from heatmap_loader import sold_month_to_label

    if filtered.is_empty():
        return {"objects": [], "display": [], "months": [], "z": []}
    period_months = list_sorted(filtered.select("sold_month").unique().to_series().to_list())
    grouped = filtered.group_by(["object", "sold_month"]).agg(pl.len().alias("deals"))
    top_objects = (
        grouped.group_by("object")
        .agg(pl.sum("deals").alias("total"))
        .sort("total", descending=True)
        .head(int(top_n))
        .select("object")
        .to_series()
        .to_list()
    )
    pivot = (
        grouped.filter(pl.col("object").is_in(top_objects))
        .pivot(on="sold_month", index="object", values="deals", aggregate_function="sum")
        .fill_null(0)
    )
    for mcol in period_months:
        if mcol not in pivot.columns:
            pivot = pivot.with_columns(pl.lit(0).alias(mcol))
    pivot = pivot.select(["object"] + period_months)
    pivot = pivot.join(pl.DataFrame({"object": top_objects}), on="object", how="right").fill_null(0)
    pivot = pivot.select(["object"] + period_months)
    z = [
        [int(v) if v is not None else 0 for v in pivot.select(period_months).row(i)]
        for i in range(pivot.height)
    ]
    totals = [sum(row) for row in z]
    display = [f"{name} ({total})" for name, total in zip(top_objects, totals)]
    months = [sold_month_to_label(m) for m in period_months]
    return {
        "objects": top_objects,
        "display": display,
        "months": months,
        "month_keys": period_months,
        "z": z,
    }


def _heatmap_filtered(df: pl.DataFrame, a: dict[str, Any]) -> pl.DataFrame:
    from aggregations import apply_filters

    flags = set(a.get("data_quality") or [])
    dff = filter_by_source(df, a.get("source"))
    d0, d1 = a.get("date_from"), a.get("date_to")
    if d0 is not None:
        dff = dff.filter(pl.col("sold_date") >= d0)
    if d1 is not None:
        dff = dff.filter(pl.col("sold_date") <= d1)
    if d0 is None and d1 is None:
        y = parse_year(a.get("year"))
        if y is not None:
            dff = dff.filter(pl.col("year") == y)
    if a.get("agglomeration") and a["agglomeration"] != "all":
        dff = dff.filter(pl.col("agglomeration") == a["agglomeration"])
    districts = a.get("district") or []
    if districts:
        dff = dff.filter(pl.col("loc_district").is_in(districts))
    filtered = apply_filters(
        dff,
        years=None,
        months=a.get("months") or None,
        agglomeration=None,
        cities=a.get("city") or None,
        mortgage_mode=a.get("mortgage_mode") or "all",
        sources=None,
        developers=None,
        type_lots=a.get("type_lot") or None,
        date_from=d0,
        date_to=d1,
        budget_min=a.get("budget_min"),
        budget_max=a.get("budget_max"),
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


def heatmap_data(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    filtered = _heatmap_filtered(df, a)
    return _heatmap_from_deals(filtered, a.get("top_n") or 40)


def heatmap_cell_details(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    from heatmap_loader import month_label_to_sold_month

    obj = (a.get("object") or "").strip()
    month_raw = (a.get("month") or a.get("sold_month") or "").strip()
    if not obj or not month_raw:
        return {
            "title": "Кликните по ячейке, чтобы увидеть сделки.",
            "rows": [],
            "total": 0,
        }

    month = month_label_to_sold_month(month_raw) or month_raw
    if len(month) >= 7 and month[4] == "-":
        month = month[:7]

    filtered = _heatmap_filtered(df, a)
    dff = filtered.filter((pl.col("object") == obj) & (pl.col("sold_month") == month))
    if dff.is_empty():
        return {
            "title": f"{obj} — {month}: 0 сделок",
            "rows": [],
            "total": 0,
            "message": "Сделок не найдено (после фильтров).",
        }

    cols = [
        ("sold_date", "date"),
        ("est_budget", "budget"),
        ("deal_status", "status"),
        ("type_lot", "type_lot"),
        ("source", "source"),
        ("city", "city"),
        ("loc_district", "district"),
        ("developer", "developer"),
    ]
    available = [src for src, _ in cols if src in dff.columns]
    view = dff.select(available).sort("sold_date" if "sold_date" in available else available[0])
    rows = []
    for r in view.head(300).iter_rows(named=True):
        rows.append(
            {
                "date": str(r.get("sold_date") or "")[:10],
                "budget": round(float(r["est_budget"])) if r.get("est_budget") is not None else None,
                "status": r.get("deal_status"),
                "type_lot": r.get("type_lot"),
                "source": r.get("source"),
                "city": r.get("city"),
                "district": r.get("loc_district"),
                "developer": r.get("developer"),
            }
        )
    return {
        "title": f"{obj} — {month}: {dff.height} сделок (показано до 300)",
        "rows": rows,
        "total": int(dff.height),
        "object": obj,
        "month": month,
    }


def euler_data(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    projects = (a.get("projects") or [])[:3]
    target = int(a.get("target_budget") or 8_000_000)
    delta = int(a.get("delta_budget") or 3_000_000)
    lo, hi = target - delta, target + delta

    dff = filter_by_source(df, a.get("source"))
    dff = slice_by_period(dff, a.get("year"), a.get("date_from"), a.get("date_to"))
    cities = a.get("city") or []
    if cities:
        dff = dff.filter(pl.col("city").is_in(cities))
    if a.get("type_lot_single"):
        dff = dff.filter(pl.col("type_lot") == a["type_lot_single"])
    dff = dff.filter(
        pl.col("est_budget").is_not_null()
        & (pl.col("est_budget") >= lo)
        & (pl.col("est_budget") <= hi)
    )

    if len(projects) < 2:
        return {
            "projects": projects,
            "sizes": {},
            "pairs": {},
            "triple": 0,
            "message": "Выберите 2–3 проекта для пересечения аудиторий",
            "band": {"lo": lo, "hi": hi, "target": target},
        }

    sets: dict[str, set[float]] = {}
    for p in projects:
        budgets = (
            dff.filter(pl.col("object") == p)
            .select("est_budget")
            .drop_nulls()
            .to_series()
            .to_list()
        )
        # bucket by 50k to approximate audience overlap by budget corridor
        sets[p] = {round(float(b) / 50_000) * 50_000 for b in budgets}

    sizes = {p: len(sets[p]) for p in projects}
    pairs: dict[str, int] = {}
    for i, a_name in enumerate(projects):
        for b_name in projects[i + 1 :]:
            pairs[f"{a_name}||{b_name}"] = len(sets[a_name] & sets[b_name])
    triple = 0
    if len(projects) == 3:
        triple = len(sets[projects[0]] & sets[projects[1]] & sets[projects[2]])

    return {
        "projects": projects,
        "sizes": sizes,
        "pairs": pairs,
        "triple": triple,
        "band": {"lo": lo, "hi": hi, "target": target},
        "message": None,
    }


def project_growth_data(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    from project_growth_logic import compute_project_growth, filter_project_growth_deals

    filtered = filter_project_growth_deals(
        df,
        deals_source=a.get("source") or "all",
        year=a.get("year"),
        agglomeration=a.get("agglomeration") or "all",
        cities_sel=a.get("city"),
        districts_sel=a.get("district"),
        type_lot_sel=a.get("type_lot"),
        mortgage_mode=a.get("mortgage_mode") or "all",
        data_quality_flags=a.get("data_quality"),
        date_from=a.get("date_from"),
        date_to=a.get("date_to"),
        budget_min=a.get("budget_min"),
        budget_max=a.get("budget_max"),
    )
    growth = compute_project_growth(filtered)
    if growth.is_empty():
        return {"budget_pct": [], "sqm_pct": [], "rows": []}

    cities = (
        filtered.group_by("object")
        .agg(pl.first("city").alias("city"))
        if "city" in filtered.columns
        else pl.DataFrame({"object": [], "city": []})
    )
    if not cities.is_empty():
        growth = growth.join(cities, on="object", how="left")

    def top_pct(col: str) -> list[dict]:
        g = growth.filter(pl.col(col).is_not_null()).sort(col, descending=True).head(20)
        return [
            {"name": str(r["object"]), "value": round(float(r[col]), 1)}
            for r in g.iter_rows(named=True)
        ]

    rows = []
    for r in growth.sort("growth_budget_pct", descending=True, nulls_last=True).head(100).iter_rows(named=True):
        rows.append(
            {
                "object": r.get("object"),
                "city": r.get("city"),
                "deals": int(r.get("deals_total") or 0),
                "budget_growth_pct": round(float(r["growth_budget_pct"]), 1)
                if r.get("growth_budget_pct") is not None
                else None,
                "sqm_growth_pct": round(float(r["growth_sqm_pct"]), 1)
                if r.get("growth_sqm_pct") is not None
                else None,
            }
        )
    return {
        "budget_pct": top_pct("growth_budget_pct"),
        "sqm_pct": top_pct("growth_sqm_pct"),
        "rows": rows,
    }


def lot_growth_data(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    """Simplified lot growth: avg budget and sqm by rooms over months for filtered deals."""
    base = filtered_deals(df, a, use_mortgage=True)
    if base.is_empty() or "rooms_count" not in base.columns:
        return {"series": [], "rows": []}

    clean = base.filter(
        pl.col("est_budget").is_not_null()
        & (pl.col("est_budget") > 0)
        & pl.col("sold_month").is_not_null()
    )
    if clean.is_empty():
        return {"series": [], "rows": []}

    monthly = (
        clean.group_by("sold_month")
        .agg(
            [
                pl.len().alias("deals"),
                pl.mean("est_budget").alias("avg_budget"),
                pl.mean("price_sqm").alias("avg_sqm"),
            ]
        )
        .sort("sold_month")
    )
    return {
        "series": {
            "labels": monthly["sold_month"].to_list(),
            "avg_budget": [round(float(x or 0)) for x in monthly["avg_budget"].to_list()],
            "avg_sqm": [round(float(x or 0)) for x in monthly["avg_sqm"].to_list()],
            "deals": [int(x) for x in monthly["deals"].to_list()],
        },
        "rows": [
            {
                "month": r["sold_month"],
                "deals": int(r["deals"]),
                "avg_budget": round(float(r["avg_budget"] or 0)),
                "avg_sqm": round(float(r["avg_sqm"] or 0)),
            }
            for r in monthly.iter_rows(named=True)
        ],
    }


def egrz_data(a: dict[str, Any]) -> dict:
    import csv
    import re
    from pathlib import Path

    out_dir = Path(__file__).resolve().parent.parent / "output"
    path = next(
        (
            out_dir / name
            for name in (
                "dnr_permits_egrz_filtered.csv",
                "dnr_permits_egrz.csv",
                "filtered_latest.csv",
                "new_matches_latest.csv",
            )
            if (out_dir / name).exists()
        ),
        out_dir / "missing.csv",
    )
    if not path.exists():
        return {"rows": [], "regions": [], "work_types": [], "message": "Файл ЕГРЗ не найден"}

    def extract_city(text: str) -> str:
        for pattern in [
            r"\bг\.\s*([А-Яа-яЁёA-Za-z\- ]{2,60})",
            r"\bгород\s+([А-Яа-яЁёA-Za-z\- ]{2,60})",
        ]:
            m = re.search(pattern, text or "")
            if m:
                city = re.split(r"[,;:()]", m.group(1))[0].strip(" ,.;:()\"'")
                if city:
                    return city
        return ""

    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            object_name = row.get(
                "Наименование и адрес (местоположение) объекта капитального строительства, применительно к которому подготовлена проектная документация",
                "",
            ) or ""
            rows.append(
                {
                    "rns": row.get("Номер заключения экспертизы", "") or "",
                    "date": row.get("Дата включения сведений в реестр", "") or "",
                    "object": object_name,
                    "developer": row.get(
                        "Сведения о застройщике, обеспечившем подготовку проектной документации",
                        "",
                    )
                    or "",
                    "keys": row.get("MatchedKeywords", "") or "",
                    "city": extract_city(object_name),
                    "region": row.get("Субъект РФ", "") or "",
                    "work_type": row.get("Вид работ", "") or "",
                }
            )

    regions = sorted({r["region"] for r in rows if r["region"]})
    work_types = sorted({r["work_type"] for r in rows if r["work_type"]})
    region_set = set(a.get("region") or [])
    work_set = set(a.get("work_type") or [])
    search = (a.get("search") or "").strip().lower().replace("ё", "е")

    filtered = []
    for r in rows:
        if region_set and r["region"] not in region_set:
            continue
        if work_set and r["work_type"] not in work_set:
            continue
        if search:
            hay = f"{r['object']} {r['developer']} {r['rns']} {r['keys']} {r['city']}".lower().replace(
                "ё", "е"
            )
            if search not in hay:
                continue
        filtered.append(r)

    return {
        "rows": filtered[:500],
        "total": len(filtered),
        "regions": [{"label": x, "value": x} for x in regions],
        "work_types": [{"label": x, "value": x} for x in work_types],
        "message": None,
    }
