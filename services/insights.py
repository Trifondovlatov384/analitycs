"""Market insight widgets: sales pace, price-per-m² dynamics, mortgage banks & terms."""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from services.filters import filtered_deals

WHOLESALE_COL = "Участие объекта в оптовой сделке"


def _drop_wholesale(frame: pl.DataFrame) -> pl.DataFrame:
    if WHOLESALE_COL not in frame.columns:
        return frame
    return frame.filter(
        ~pl.col(WHOLESALE_COL).cast(pl.Utf8, strict=False).str.to_lowercase().fill_null("").str.contains("да")
    )


def _has(frame: pl.DataFrame, col: str) -> bool:
    return col in frame.columns and frame.select(pl.col(col).is_not_null().any()).item()


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift_months(key: str, n: int) -> str:
    y, m = int(key[:4]), int(key[5:7])
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _r(v: Any, nd: int = 0) -> float | int | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return round(f, nd) if nd else round(f)


def _first_text(col: str) -> pl.Expr:
    return pl.col(col).drop_nulls().first().alias(col)


# ───────────────────────── 1. Sales pace ─────────────────────────


def region_expr() -> pl.Expr:
    """Exports cover different periods: Crimea (bnMAP) and the Kuban files end on different dates."""
    return pl.when(pl.col("source") == "crimea").then(pl.lit("crimea")).otherwise(pl.lit("main")).alias("region")


REGION_LABELS = {"crimea": "Крым", "main": "Краснодарский край"}


def _anchor_month(last_day: date, explicit: bool) -> int:
    """Index (year*12+month-1) of the last month to count. A month with data for
    fewer than 20 days is treated as incomplete and skipped, unless the user set the date."""
    idx = last_day.year * 12 + last_day.month - 1
    if not explicit and last_day.day < 20:
        idx -= 1
    return idx


def _idx_to_key(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def sales_pace(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    """
    How fast each complex sells right now: average deals per month in the last
    N complete months vs the N months before, plus pace since start of sales.
    Period filters are ignored on purpose — the window ends at the latest data of
    each region (or at «По дату», when it is set).
    """
    window = max(1, min(12, int(a.get("pace_window") or 3)))
    explicit = a.get("date_to") is not None
    base = filtered_deals(
        df,
        {**a, "year": None, "date_from": None, "months": [], "date_to": a.get("date_to")},
        use_mortgage=True,
    )
    base = _drop_wholesale(base).filter(
        pl.col("object").is_not_null() & pl.col("sold_date").is_not_null()
    )
    if base.is_empty():
        return {"rows": [], "top": [], "market": None, "message": "Нет сделок под выбранные фильтры"}

    base = base.with_columns(
        region_expr(),
        (pl.col("sold_date").dt.year() * 12 + pl.col("sold_date").dt.month() - 1).alias("midx"),
    )
    anchors = {
        r["region"]: (_anchor_month(r["last"], explicit), r["last"])
        for r in base.group_by("region").agg(pl.col("sold_date").max().alias("last")).iter_rows(named=True)
    }
    anchor_df = pl.DataFrame(
        {"region": list(anchors), "aidx": [v[0] for v in anchors.values()]},
        schema={"region": pl.Utf8, "aidx": pl.Int64},
    )
    base = base.join(anchor_df, on="region", how="left").with_columns(
        (pl.col("aidx") - pl.col("midx")).alias("lag")
    )
    in_cur = (pl.col("lag") >= 0) & (pl.col("lag") < window)
    in_prev = (pl.col("lag") >= window) & (pl.col("lag") < 2 * window)
    upto_anchor = pl.col("lag") >= 0

    has_start = _has(base, "sales_start")
    has_exposure = _has(base, "exposure_days")
    aggs = [
        upto_anchor.sum().alias("deals_total"),
        in_cur.sum().alias("cur"),
        in_prev.sum().alias("prev"),
        pl.col("sold_date").min().alias("first_deal"),
        (pl.col("is_mortgage") & in_cur).sum().alias("cur_mortgage"),
        pl.col("price_sqm").filter(in_cur).median().alias("cur_sqm"),
        pl.col("region").first().alias("region"),
        pl.col("aidx").first().alias("aidx"),
        _first_text("city"),
        _first_text("developer"),
    ]
    if "class" in base.columns:
        aggs.append(_first_text("class"))
    if has_start:
        aggs.append(pl.col("sales_start").min().alias("sales_start"))
    if has_exposure:
        aggs.append(pl.col("exposure_days").filter(in_cur).median().alias("exposure"))

    g = base.group_by("object").agg(aggs).filter((pl.col("cur") + pl.col("prev")) >= 3)

    rows = []
    for r in g.iter_rows(named=True):
        aidx = r["aidx"]
        end_day = date(aidx // 12, aidx % 12 + 1, 28)
        start = r.get("sales_start") or r["first_deal"]
        months_live = max(1.0, (end_day - start).days / 30.44) if start and start <= end_day else None
        cur_pace = r["cur"] / window
        prev_pace = r["prev"] / window
        rows.append(
            {
                "object": r["object"],
                "city": r.get("city"),
                "developer": r.get("developer"),
                "class": r.get("class"),
                "region": REGION_LABELS.get(r["region"], r["region"]),
                "data_to": _idx_to_key(aidx),
                "pace": round(cur_pace, 1),
                "pace_prev": round(prev_pace, 1),
                "pace_delta": round((cur_pace - prev_pace) / prev_pace * 100) if prev_pace else None,
                "start": start.isoformat() if start else None,
                "start_is_real": bool(r.get("sales_start")),
                "months_live": round(months_live) if months_live else None,
                "pace_since_start": round(r["deals_total"] / months_live, 1) if months_live else None,
                "deals_total": int(r["deals_total"]),
                "mortgage_share": round(r["cur_mortgage"] / r["cur"] * 100) if r["cur"] else None,
                "sqm": _r(r.get("cur_sqm")),
                "exposure": _r(r.get("exposure")),
            }
        )
    rows.sort(key=lambda x: (x["pace"], x["pace_prev"]), reverse=True)

    totals = base.select(in_cur.sum().alias("c"), in_prev.sum().alias("p")).row(0, named=True)
    cur_total, prev_total = totals["c"], totals["p"]
    windows = [
        {
            "region": REGION_LABELS.get(reg, reg),
            "cur_months": [_idx_to_key(ai - i) for i in range(window - 1, -1, -1)],
            "prev_months": [_idx_to_key(ai - i) for i in range(2 * window - 1, window - 1, -1)],
            "last_day": last.isoformat(),
        }
        for reg, (ai, last) in sorted(anchors.items())
    ]
    market = {
        "pace": round(cur_total / window, 1),
        "pace_prev": round(prev_total / window, 1),
        "pace_delta": round((cur_total - prev_total) / prev_total * 100, 1) if prev_total else None,
        "active": sum(1 for r in rows if r["pace"] > 0),
        "growing": sum(1 for r in rows if (r["pace_delta"] or 0) >= 20),
        "slowing": sum(1 for r in rows if r["pace_delta"] is not None and r["pace_delta"] <= -20),
    }
    return {
        "window": window,
        "windows": windows,
        "cur_months": windows[0]["cur_months"] if len(windows) == 1 else None,
        "prev_months": windows[0]["prev_months"] if len(windows) == 1 else None,
        "has_start": has_start,
        "has_exposure": has_exposure,
        "market": market,
        "top": [{"name": r["object"], "value": r["pace"]} for r in rows[:20]],
        "rows": rows[:400],
        "message": None,
    }


# ───────────────────────── 2. Price per m² dynamics ─────────────────────────


def _period_key(gran: str) -> pl.Expr:
    if gran == "quarter":
        return (
            pl.col("year").cast(pl.Utf8)
            + pl.lit("-Q")
            + ((pl.col("sold_date").dt.month() - 1) // 3 + 1).cast(pl.Utf8)
        ).alias("period")
    return pl.col("sold_month").alias("period")


def price_dynamics(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    gran = "quarter" if a.get("gran") == "quarter" else "month"
    base = _drop_wholesale(filtered_deals(df, a, use_mortgage=True))
    base = base.filter(pl.col("price_sqm").is_not_null() & (pl.col("price_sqm") > 0) & pl.col("object").is_not_null())
    if base.is_empty():
        return {"labels": [], "series": [], "rows": [], "message": "Нет сделок с ценой за м² под выбранные фильтры"}

    base = base.with_columns(_period_key(gran))
    periods = sorted(base.select("period").unique().drop_nulls().to_series().to_list())

    # Growth table: first 3 months of the period vs last 3 months.
    months = sorted(base.select("sold_month").unique().drop_nulls().to_series().to_list())
    first_w, last_w = months[:3], months[-3:]
    rows: list[dict] = []
    if len(months) >= 4:
        g = (
            base.group_by("object")
            .agg(
                pl.len().alias("deals"),
                pl.col("price_sqm").filter(pl.col("sold_month").is_in(first_w)).median().alias("p0"),
                pl.col("price_sqm").filter(pl.col("sold_month").is_in(first_w)).len().alias("n0"),
                pl.col("price_sqm").filter(pl.col("sold_month").is_in(last_w)).median().alias("p1"),
                pl.col("price_sqm").filter(pl.col("sold_month").is_in(last_w)).len().alias("n1"),
                pl.col("price_sqm").median().alias("median"),
                _first_text("city"),
                _first_text("developer"),
                *([_first_text("class")] if "class" in base.columns else []),
            )
            .filter((pl.col("n0") >= 3) & (pl.col("n1") >= 3))
        )
        for r in g.iter_rows(named=True):
            growth = (r["p1"] - r["p0"]) / r["p0"] * 100 if r["p0"] else None
            rows.append(
                {
                    "object": r["object"],
                    "city": r.get("city"),
                    "developer": r.get("developer"),
                    "class": r.get("class"),
                    "deals": int(r["deals"]),
                    "p0": _r(r["p0"]),
                    "p1": _r(r["p1"]),
                    "growth": round(growth, 1) if growth is not None else None,
                    "median": _r(r["median"]),
                }
            )
        rows.sort(key=lambda x: (x["growth"] is None, -(x["growth"] or 0)))

    # Lines: chosen complexes (or the 5 biggest) + the whole market for reference.
    chosen = [x for x in (a.get("selected") or []) if x][:6]
    if not chosen:
        chosen = (
            base.group_by("object").len().sort("len", descending=True).head(5).select("object").to_series().to_list()
        )
    per = (
        base.filter(pl.col("object").is_in(chosen))
        .group_by(["object", "period"])
        .agg(pl.col("price_sqm").median().alias("p"), pl.len().alias("n"))
    )
    lookup = {(r["object"], r["period"]): (r["p"], r["n"]) for r in per.iter_rows(named=True)}
    series = []
    for name in chosen:
        vals = []
        for p in periods:
            v = lookup.get((name, p))
            vals.append(_r(v[0]) if v and v[1] >= 2 else None)
        series.append({"name": name, "values": vals})
    market = base.group_by("period").agg(pl.col("price_sqm").median().alias("p")).sort("period")
    mk = {r["period"]: _r(r["p"]) for r in market.iter_rows(named=True)}

    return {
        "gran": gran,
        "labels": periods,
        "series": series,
        "market": [mk.get(p) for p in periods],
        "chosen": chosen,
        "first_window": first_w,
        "last_window": last_w,
        "rows": rows[:400],
        "message": None if len(months) >= 4 else "Для расчёта роста нужно минимум 4 месяца — выберите период подлиннее",
    }


# ───────────────────────── 3. Mortgage: banks & terms ─────────────────────────

TERM_BUCKETS = [(0, 120, "до 10 лет"), (120, 180, "10–15 лет"), (180, 240, "15–20 лет"), (240, 300, "20–25 лет"), (300, 10_000, "25–30 лет")]


def mortgage_breakdown(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    base = _drop_wholesale(filtered_deals(df, {**a, "mortgage_mode": "all"}, use_mortgage=True))
    if base.is_empty():
        return {"message": "Нет сделок под выбранные фильтры"}
    mort = base.filter(pl.col("is_mortgage") == True)  # noqa: E712
    total, n_mort = base.height, mort.height
    has_bank = "bank" in mort.columns
    has_term = "mortgage_months" in mort.columns

    banks: list[dict] = []
    bank_known = 0
    if has_bank and n_mort:
        known = mort.filter(pl.col("bank").is_not_null())
        bank_known = known.height
        if bank_known:
            counts = known.group_by("bank").len().sort("len", descending=True)
            top = counts.head(10)
            other = bank_known - int(top["len"].sum())
            banks = [
                {"name": r["bank"], "value": int(r["len"]), "share": round(r["len"] / bank_known * 100, 1)}
                for r in top.iter_rows(named=True)
            ]
            if other > 0:
                banks.append({"name": "Другие банки", "value": other, "share": round(other / bank_known * 100, 1)})

    terms: list[dict] = []
    median_term = None
    term_known = 0
    if has_term and n_mort:
        t = mort.filter(pl.col("mortgage_months").is_not_null() & (pl.col("mortgage_months") > 0))
        term_known = t.height
        if term_known:
            median_term = round(float(t.select(pl.col("mortgage_months").median()).item()) / 12, 1)
            vals = t.select("mortgage_months").to_series().to_list()
            for lo, hi, label in TERM_BUCKETS:
                c = sum(1 for v in vals if lo < v <= hi) if lo else sum(1 for v in vals if v <= hi)
                terms.append({"label": label, "value": c, "share": round(c / term_known * 100, 1)})

    monthly = (
        base.group_by("sold_month")
        .agg(
            pl.len().alias("n"),
            pl.col("is_mortgage").sum().alias("m"),
            *(
                [pl.col("mortgage_months").filter(pl.col("is_mortgage") & (pl.col("mortgage_months") > 0)).median().alias("term")]
                if has_term
                else []
            ),
        )
        .sort("sold_month")
    )
    series = {
        "labels": monthly["sold_month"].to_list(),
        "share": [round(m / n * 100, 1) if n else None for m, n in zip(monthly["m"].to_list(), monthly["n"].to_list())],
        "term": [round(x / 12, 1) if x else None for x in monthly["term"].to_list()] if has_term else [],
    }

    rows = []
    if n_mort:
        per = base.group_by("object").agg(
            pl.len().alias("deals"),
            pl.col("is_mortgage").sum().alias("m"),
            _first_text("city"),
            *(
                [pl.col("mortgage_months").filter(pl.col("is_mortgage") & (pl.col("mortgage_months") > 0)).median().alias("term")]
                if has_term
                else []
            ),
        ).filter(pl.col("deals") >= 5)
        top_bank: dict[str, tuple[str, float]] = {}
        if has_bank and bank_known:
            bb = (
                mort.filter(pl.col("bank").is_not_null())
                .group_by(["object", "bank"])
                .len()
                .sort(["object", "len"], descending=[False, True])
            )
            tot = {r["object"]: r["len"] for r in bb.group_by("object").agg(pl.col("len").sum()).iter_rows(named=True)}
            for r in bb.group_by("object", maintain_order=True).first().iter_rows(named=True):
                top_bank[r["object"]] = (r["bank"], round(r["len"] / tot[r["object"]] * 100))
        for r in per.iter_rows(named=True):
            tb = top_bank.get(r["object"])
            rows.append(
                {
                    "object": r["object"],
                    "city": r.get("city"),
                    "deals": int(r["deals"]),
                    "mortgage_share": round(r["m"] / r["deals"] * 100),
                    "top_bank": tb[0] if tb else None,
                    "top_bank_share": tb[1] if tb else None,
                    "term": round(r["term"] / 12, 1) if r.get("term") else None,
                }
            )
        rows.sort(key=lambda x: x["deals"], reverse=True)

    return {
        "total": total,
        "mortgage": n_mort,
        "mortgage_share": round(n_mort / total * 100, 1) if total else None,
        "bank_coverage": round(bank_known / n_mort * 100) if n_mort else None,
        "term_coverage": round(term_known / n_mort * 100) if n_mort else None,
        "median_term": median_term,
        "top_bank": banks[0] if banks and banks[0]["name"] != "Другие банки" else None,
        "banks": banks,
        "terms": terms,
        "series": series,
        "rows": rows[:400],
        "message": None,
    }
