"""Registry exports lag behind: the last month (or two) of an export is only partly
registered. Comparing such a month with a fully registered month a year earlier makes
growth look smaller than it is. This module finds, per region, the last month whose
volume looks complete, so year-on-year comparisons and pace windows can stop there.
"""

from __future__ import annotations

import calendar
from datetime import date

import polars as pl

KUBAN_SOURCES = ("kuban", "analitic", "kk2026", "august2026", "july2026", "june2026", "may2026")
REGION_LABELS = {"crimea": "Крым", "kuban": "Краснодарский край", "adygea": "Адыгея"}
_MONTHS_GEN = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

# A month is «incomplete» when it has less than this share of the average of the 3 months before it.
COMPLETE_SHARE = 0.7

_cache: dict[int, dict[str, date]] = {}


def region_expr() -> pl.Expr:
    return (
        pl.when(pl.col("source").is_in(list(KUBAN_SOURCES)))
        .then(pl.lit("kuban"))
        .otherwise(pl.col("source"))
        .alias("region")
    )


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def complete_until(df: pl.DataFrame) -> dict[str, date]:
    """{region: last date of the last complete month}. Computed on the whole dataset
    (not on a filtered slice, which would be too noisy) and cached per dataset."""
    key = id(df)
    if key in _cache:
        return _cache[key]
    out: dict[str, date] = {}
    if df.is_empty():
        return out
    counts = (
        df.with_columns(region_expr())
        .filter(pl.col("sold_date").is_not_null())
        .group_by(["region", pl.col("sold_date").dt.year().alias("y"), pl.col("sold_date").dt.month().alias("m")])
        .len()
        .sort(["region", "y", "m"])
    )
    for (region,), g in counts.group_by(["region"], maintain_order=True):
        rows = [(r["y"], r["m"], r["len"]) for r in g.iter_rows(named=True)]
        last_day = df.with_columns(region_expr()).filter(pl.col("region") == region).select(pl.col("sold_date").max()).item()
        idx = len(rows) - 1
        # Check at most the last two months.
        for _ in range(2):
            if idx < 3:
                break
            base = sum(r[2] for r in rows[idx - 3 : idx]) / 3
            if base and rows[idx][2] < COMPLETE_SHARE * base:
                idx -= 1
            else:
                break
        y, m, _n = rows[idx]
        out[region] = min(_month_end(y, m), last_day) if idx == len(rows) - 1 else _month_end(y, m)
    _cache[key] = out
    return out


def trim_incomplete(df: pl.DataFrame, frame: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    """Drop the not-yet-complete tail of each region from `frame`.
    Returns the trimmed frame and a list of what was left out (for the UI note)."""
    if frame.is_empty():
        return frame, []
    cut = complete_until(df)
    f = frame.with_columns(region_expr())
    dropped: list[dict] = []
    parts = []
    for (region,), g in f.group_by(["region"], maintain_order=True):
        c = cut.get(region)
        if c is None:
            parts.append(g)
            continue
        kept = g.filter(pl.col("sold_date") <= c)
        if kept.height < g.height:
            dropped.append(
                {
                    "region": REGION_LABELS.get(region, region),
                    "cutoff": c.isoformat(),
                    "deals": g.height - kept.height,
                }
            )
        parts.append(kept)
    out = pl.concat(parts) if parts else f
    return out.drop("region"), dropped


def dropped_note(dropped: list[dict]) -> str | None:
    if not dropped:
        return None
    bits = []
    for d in dropped:
        c = date.fromisoformat(d["cutoff"])
        nxt_m = c.month % 12 + 1
        nxt_y = c.year + (1 if c.month == 12 else 0)
        bits.append(
            f"{d['region'] + ': ' if len(dropped) > 1 else ''}сравнение по {c.day} {_gen(c.month)} {c.year} — "
            f"{_MONTHS_GEN[nxt_m - 1]} {nxt_y} ещё неполный ({d['deals']} сделок не учтены)"
        )
    return "; ".join(bits) + ". Сделки регистрируются с задержкой, поэтому последний месяц выгрузки сравнивать рано."


def _gen(m: int) -> str:
    return ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"][m - 1]
