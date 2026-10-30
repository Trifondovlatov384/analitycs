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
    # Long-run figures (first deal, pace since start) use every export.
    lifetime = base.group_by("object").agg(
        pl.col("sold_date").min().alias("first_any"),
        pl.len().alias("deals_any"),
    )
    # Recent pace uses only the freshest export of each region: exports differ in
    # coverage (e.g. Analitic 2024–25 vs the 2026 Kuban file), and mixing them in one
    # window would show fake growth or decline at the seam.
    fresh = (
        base.group_by(["region", "source"])
        .agg(pl.col("sold_date").max().alias("last"), pl.len().alias("n"))
        .sort(["region", "last", "n"], descending=[False, True, True])
        .group_by("region", maintain_order=True)
        .first()
        .select("region", "source")
    )
    base = base.join(fresh, on=["region", "source"], how="inner")
    first_idx = {r["region"]: r["f"] for r in base.group_by("region").agg(pl.col("midx").min().alias("f")).iter_rows(named=True)}
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

    g = (
        base.group_by("object")
        .agg(aggs)
        .filter((pl.col("cur") + pl.col("prev")) >= 3)
        .join(lifetime, on="object", how="left")
    )

    def prev_months_available(region: str) -> int:
        aidx = anchors[region][0]
        oldest_prev = aidx - 2 * window + 1
        return max(0, min(window, window - max(0, first_idx[region] - oldest_prev)))

    prev_n = {reg: prev_months_available(reg) for reg in anchors}

    rows = []
    for r in g.iter_rows(named=True):
        aidx = r["aidx"]
        end_day = date(aidx // 12, aidx % 12 + 1, 28)
        start = r.get("sales_start") or r.get("first_any") or r["first_deal"]
        months_live = max(1.0, (end_day - start).days / 30.44) if start and start <= end_day else None
        cur_pace = r["cur"] / window
        pn = prev_n.get(r["region"], window)
        prev_pace = r["prev"] / pn if pn else None
        rows.append(
            {
                "object": r["object"],
                "city": r.get("city"),
                "developer": r.get("developer"),
                "class": r.get("class"),
                "region": REGION_LABELS.get(r["region"], r["region"]),
                "data_to": _idx_to_key(aidx),
                "pace": round(cur_pace, 1),
                "pace_prev": round(prev_pace, 1) if prev_pace is not None else None,
                "pace_delta": round((cur_pace - prev_pace) / prev_pace * 100) if prev_pace else None,
                "start": start.isoformat() if start else None,
                "start_is_real": bool(r.get("sales_start")),
                "months_live": round(months_live) if months_live else None,
                "pace_since_start": round((r.get("deals_any") or r["deals_total"]) / months_live, 1) if months_live else None,
                "deals_total": int(r.get("deals_any") or r["deals_total"]),
                "mortgage_share": round(r["cur_mortgage"] / r["cur"] * 100) if r["cur"] else None,
                "sqm": _r(r.get("cur_sqm")),
                "exposure": _r(r.get("exposure")),
            }
        )
    rows.sort(key=lambda x: (x["pace"], x["pace_prev"] or 0), reverse=True)

    cur_total = base.select(in_cur.sum()).item() / window
    prev_total = 0.0
    for reg, n in prev_n.items():
        if n:
            prev_total += base.filter(pl.col("region") == reg).select(in_prev.sum()).item() / n
    sources_used = fresh["source"].to_list()
    windows = [
        {
            "region": REGION_LABELS.get(reg, reg),
            "cur_months": [_idx_to_key(ai - i) for i in range(window - 1, -1, -1)],
            "prev_months": [
                _idx_to_key(ai - i)
                for i in range(2 * window - 1, window - 1, -1)
                if ai - i >= first_idx[reg]
            ],
            "last_day": last.isoformat(),
        }
        for reg, (ai, last) in sorted(anchors.items())
    ]
    market = {
        "pace": round(cur_total, 1),
        "pace_prev": round(prev_total, 1) if prev_total else None,
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
        "sources_used": sources_used,
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

    # Growth table, per complex: its first 3 months with sales in the period vs its
    # last 3 months. Works for complexes that started selling mid-period, and for
    # long periods where the earliest months are sparse.
    pm = (
        base.group_by(["object", "sold_month"])
        .agg(pl.col("price_sqm").median().alias("p"), pl.len().alias("n"))
        .sort(["object", "sold_month"])
    )
    meta_cols = [_first_text("city"), _first_text("developer")]
    if "class" in base.columns:
        meta_cols.append(_first_text("class"))
    info = {r["object"]: r for r in base.group_by("object").agg(pl.len().alias("deals"), *meta_cols).iter_rows(named=True)}
    n_months = base.select(pl.col("sold_month").n_unique()).item()
    k = 3 if n_months >= 6 else 2  # short periods (e.g. this year so far) use 2-month windows
    rows: list[dict] = []
    for (obj,), grp in pm.group_by(["object"], maintain_order=True):
        if grp.height < 2 * k:  # need two separate windows
            continue
        months_list = grp["sold_month"].to_list()
        first, last = grp.head(k), grp.tail(k)
        n0, n1 = int(first["n"].sum()), int(last["n"].sum())
        if n0 < 3 or n1 < 3:
            continue
        sub = base.filter(pl.col("object") == obj)
        p0 = sub.filter(pl.col("sold_month").is_in(first["sold_month"].to_list())).select(pl.col("price_sqm").median()).item()
        p1 = sub.filter(pl.col("sold_month").is_in(last["sold_month"].to_list())).select(pl.col("price_sqm").median()).item()
        if not p0:
            continue
        y0, m0 = int(months_list[1][:4]), int(months_list[1][5:7])
        y1, m1 = int(months_list[-2][:4]), int(months_list[-2][5:7])
        span = max(1, (y1 - y0) * 12 + (m1 - m0))
        growth = (p1 - p0) / p0 * 100
        meta = info.get(obj, {})
        rows.append(
            {
                "object": obj,
                "city": meta.get("city"),
                "developer": meta.get("developer"),
                "class": meta.get("class"),
                "deals": int(meta.get("deals") or 0),
                "from": months_list[0],
                "to": months_list[-1],
                "span": span,
                "p0": _r(p0),
                "p1": _r(p1),
                "growth": round(growth, 1),
                "growth_month": round(((p1 / p0) ** (1 / span) - 1) * 100, 2) if p0 > 0 and p1 > 0 else None,
            }
        )
    rows.sort(key=lambda x: -x["growth"])

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
        "rows": rows[:400],
        "window": k,
        "message": None if rows else "Нужно минимум 4 месяца продаж у комплекса — выберите период подлиннее (например, «Все годы»)",
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
