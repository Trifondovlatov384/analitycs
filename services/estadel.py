"""Estadel's own sales (bookings and deals) from Supabase, matched to registry projects.

Data lives in Supabase, schema `analytics` (tables estadel_deals, complex_map, load_runs),
read and written through the `analytics_app` role (env ESTADEL_DB_URL). It never goes to
the repository. Only fields needed for the market comparison are stored: no broker
names, commissions, client links or comments.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from datetime import date, datetime
from typing import Any

import polars as pl

CACHE_TTL_S = 300
MAX_UPLOAD_ROWS = 20_000
DEAL_STAGES = {
    "комиссия полностью получена",
    "сделка состоялась",
    "пв забран, ждем рассрочку",
    "пв внесен",
    "оформление ипотеки",
}

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "rows": None, "status": None}


# ───────────────────────── DB ─────────────────────────


def db_url() -> str | None:
    return (os.environ.get("ESTADEL_DB_URL") or "").strip() or None


def configured() -> bool:
    return db_url() is not None


def _connect():
    import psycopg

    # Supabase transaction pooler: no server-side prepared statements.
    return psycopg.connect(db_url(), prepare_threshold=None, connect_timeout=10)


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, rows=None, status=None)


_SCHEMA = {
    "team": pl.Utf8,
    "complex": pl.Utf8,
    "project": pl.Utf8,
    "lot": pl.Utf8,
    "amount": pl.Float64,
    "booking_date": pl.Date,
    "deal_date": pl.Date,
    "stage": pl.Utf8,
    "is_deal": pl.Boolean,
    "payment": pl.Utf8,
}


def _fetch() -> tuple[pl.DataFrame, dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            select d.team, d.complex, m.project, d.lot, d.amount::float8, d.booking_date, d.deal_date,
                   d.stage, d.is_deal, d.payment
            from analytics.estadel_deals d
            left join analytics.complex_map m on m.complex = d.complex
            """
        ).fetchall()
        last = conn.execute(
            "select loaded_at, source, rows, deals from analytics.load_runs order by id desc limit 1"
        ).fetchone()
        unmatched = conn.execute(
            """
            select d.complex, count(*) filter (where d.is_deal) as deals, count(*) as bookings
            from analytics.estadel_deals d
            left join analytics.complex_map m on m.complex = d.complex
            where m.project is null
            group by d.complex order by 2 desc, 3 desc
            """
        ).fetchall()
    df = pl.DataFrame(rows, schema=_SCHEMA, orient="row") if rows else pl.DataFrame(schema=_SCHEMA)
    status = {
        "configured": True,
        "rows": df.height,
        "deals": int(df["is_deal"].sum()) if df.height else 0,
        "matched_share": round(df.filter(pl.col("project").is_not_null()).height / df.height * 100) if df.height else None,
        "last_load": {
            "at": last[0].isoformat() if last else None,
            "source": last[1] if last else None,
            "rows": last[2] if last else None,
            "deals": last[3] if last else None,
        }
        if last
        else None,
        "deal_range": [
            str(df["deal_date"].min()) if df.height else None,
            str(df["deal_date"].max()) if df.height else None,
        ],
        "unmatched": [{"complex": c, "deals": int(n), "bookings": int(b)} for c, n, b in unmatched[:40]],
    }
    return df, status


def rows() -> pl.DataFrame | None:
    if not configured():
        return None
    with _lock:
        if _cache["rows"] is not None and time.time() - _cache["at"] < CACHE_TTL_S:
            return _cache["rows"]
    df, status = _fetch()
    with _lock:
        _cache.update(at=time.time(), rows=df, status=status)
    return df


def status() -> dict:
    if not configured():
        return {"configured": False}
    try:
        rows()
        return _cache["status"] or {"configured": True, "rows": 0}
    except Exception as e:  # noqa: BLE001 — shown to the user as a hint, not a crash
        return {"configured": True, "error": f"Нет связи с базой: {type(e).__name__}"}


# ───────────────────────── Filtering ─────────────────────────


def _market_attrs(market: pl.DataFrame) -> pl.DataFrame:
    """One row per registry project: where it is and who builds it (to filter our sales)."""
    cols = [c for c in ("city", "agglomeration", "developer", "loc_district") if c in market.columns]
    return (
        market.filter(pl.col("object").is_not_null())
        .group_by("object")
        .agg([pl.col(c).drop_nulls().mode().first().alias(c) for c in cols])
        .rename({"object": "project"})
    )


def filtered(market: pl.DataFrame, a: dict[str, Any], kind: str) -> pl.DataFrame:
    """Our deals (kind='deals', by deal date) or bookings (kind='bookings', by booking date)
    that match the dashboard filters. Only rows matched to a registry project are kept."""
    df = rows()
    if df is None or df.is_empty():
        return pl.DataFrame()
    date_col = "deal_date" if kind == "deals" else "booking_date"
    f = df.filter(pl.col("project").is_not_null() & pl.col(date_col).is_not_null())
    if kind == "deals":
        f = f.filter(pl.col("is_deal"))
    f = f.join(_market_attrs(market), on="project", how="inner").with_columns(
        pl.col(date_col).alias("sold_date"),
        pl.col(date_col).dt.year().alias("year"),
        pl.col(date_col).dt.strftime("%Y-%m").alias("sold_month"),
    )

    d0, d1 = a.get("date_from"), a.get("date_to")
    if d0 is not None:
        f = f.filter(pl.col("sold_date") >= d0)
    if d1 is not None:
        f = f.filter(pl.col("sold_date") <= d1)
    if d0 is None and d1 is None and a.get("year"):
        f = f.filter(pl.col("year") == int(a["year"]))
    if a.get("months"):
        f = f.filter(pl.col("sold_month").is_in(list(a["months"])))
    src = a.get("source")
    if src and src != "all":
        from services.filters import filter_by_source

        allowed = filter_by_source(market, src).get_column("object").drop_nulls().unique().to_list()
        f = f.filter(pl.col("project").is_in(allowed))
    if a.get("agglomeration") and a["agglomeration"] != "all":
        f = f.filter(pl.col("agglomeration") == a["agglomeration"])
    for key, col in (("city", "city"), ("developer", "developer"), ("project", "project"), ("district", "loc_district")):
        vals = a.get(key) or []
        if vals and col in f.columns:
            f = f.filter(pl.col(col).is_in(list(vals)))
    if a.get("object"):
        f = f.filter(pl.col("project") == a["object"])
    lo, hi = a.get("budget_min"), a.get("budget_max")
    if lo is not None:
        f = f.filter(pl.col("amount") >= lo)
    if hi is not None:
        f = f.filter(pl.col("amount") <= hi)
    mm = a.get("mortgage_mode") or "all"
    if mm != "all":
        is_m = pl.col("payment").fill_null("").str.to_lowercase().str.contains("ипотек")
        f = f.filter(is_m if mm == "mortgage" else ~is_m)
    return f


def kind_of(a: dict[str, Any]) -> str | None:
    k = (a.get("estadel") or "").strip()
    return k if k in ("deals", "bookings") else None


def monthly(market: pl.DataFrame, a: dict[str, Any], labels: list[str]) -> dict | None:
    kind = kind_of(a)
    if not kind:
        return None
    f = filtered(market, a, kind)
    counts = {r["sold_month"]: int(r["len"]) for r in f.group_by("sold_month").len().iter_rows(named=True)} if f.height else {}
    return {"kind": kind, "values": [counts.get(m, 0) for m in labels]}


def by_project_month(market: pl.DataFrame, a: dict[str, Any]) -> dict[tuple[str, str], int]:
    kind = kind_of(a)
    if not kind:
        return {}
    f = filtered(market, a, kind)
    if f.is_empty():
        return {}
    return {(r["project"], r["sold_month"]): int(r["len"]) for r in f.group_by(["project", "sold_month"]).len().iter_rows(named=True)}


def share_report(market_filtered: pl.DataFrame, market: pl.DataFrame, a: dict[str, Any]) -> dict:
    """Our volume vs the market under the same filters: totals, by month, by project."""
    kind = kind_of(a) or "deals"
    ours = filtered(market, a, kind)
    m = market_filtered
    if m.is_empty():
        return {"kind": kind, "message": "Нет рыночных сделок под выбранные фильтры"}
    m_total = m.height
    o_total = ours.height
    our_projects = set(ours["project"].unique().to_list()) if o_total else set()
    m_in_ours = m.filter(pl.col("object").is_in(list(our_projects))).height if our_projects else 0

    months = sorted(m["sold_month"].drop_nulls().unique().to_list())
    mm = {r["sold_month"]: int(r["len"]) for r in m.group_by("sold_month").len().iter_rows(named=True)}
    om = {r["sold_month"]: int(r["len"]) for r in ours.group_by("sold_month").len().iter_rows(named=True)} if o_total else {}
    o_sum = {r["sold_month"]: float(r["s"] or 0) for r in ours.group_by("sold_month").agg(pl.col("amount").sum().alias("s")).iter_rows(named=True)} if o_total else {}

    mp = m.group_by("object").agg(pl.len().alias("market"), pl.col("est_budget").sum().alias("market_sum"))
    op = (
        ours.group_by("project").agg(pl.len().alias("ours"), pl.col("amount").sum().alias("ours_sum"))
        if o_total
        else pl.DataFrame(schema={"project": pl.Utf8, "ours": pl.UInt32, "ours_sum": pl.Float64})
    )
    t = mp.join(op.rename({"project": "object"}), on="object", how="full", coalesce=True).fill_null(0)
    attrs = _market_attrs(market).rename({"project": "object"})
    t = t.join(attrs.select([c for c in ("object", "city", "developer") if c in attrs.columns]), on="object", how="left")
    table = []
    for r in t.iter_rows(named=True):
        if not r["ours"] and r["market"] < 20:
            continue
        table.append(
            {
                "object": r["object"],
                "city": r.get("city"),
                "developer": r.get("developer"),
                "market": int(r["market"]),
                "ours": int(r["ours"]),
                "share": round(r["ours"] / r["market"] * 100, 1) if r["market"] else None,
                "ours_sum": round(r["ours_sum"] or 0),
            }
        )
    table.sort(key=lambda x: (-x["ours"], -x["market"]))
    return {
        "kind": kind,
        "market_total": m_total,
        "ours_total": o_total,
        "ours_sum": round(sum(o_sum.values())),
        "share": round(o_total / m_total * 100, 2) if m_total else None,
        "share_in_our_projects": round(o_total / m_in_ours * 100, 1) if m_in_ours else None,
        "our_projects": len(our_projects),
        "months": months,
        "market_by_month": [mm.get(x, 0) for x in months],
        "ours_by_month": [om.get(x, 0) for x in months],
        "share_by_month": [round(om.get(x, 0) / mm[x] * 100, 2) if mm.get(x) else None for x in months],
        "table": table[:300],
    }


# ───────────────────────── Matching ─────────────────────────

_TR = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
    )
)


def _norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"\b(жк|ук|апарт[- ]?отель|апартаменты|resort|residence|клубный дом|комплекс)\b", " ", s)
    return " ".join(re.sub(r"[^a-zа-я0-9]+", " ", s).split())


def _keys(s: str) -> set[str]:
    ks: set[str] = set()
    for part in [s, *s.split("/")]:
        n = _norm(part)
        if n:
            ks |= {n, n.replace(" ", ""), "".join(_TR.get(ch, ch) for ch in n).replace(" ", "")}
    return {k for k in ks if k}


def auto_match(names: list[str], projects: dict[str, int]) -> dict[str, str | None]:
    """Our complex names → registry project (exact on normalised/transliterated keys,
    then prefix match); the busiest project wins on ties."""
    index: dict[str, set[str]] = {}
    for p in projects:
        for k in _keys(p):
            index.setdefault(k, set()).add(p)
    out: dict[str, str | None] = {}
    for c in names:
        cands: set[str] = set()
        for k in _keys(c):
            cands |= index.get(k, set())
        if not cands:
            kc = "".join(_TR.get(ch, ch) for ch in _norm(c)).replace(" ", "")
            if len(kc) >= 5:
                for k, ps in index.items():
                    if len(k) >= 5 and (k.startswith(kc) or kc.startswith(k)):
                        cands |= ps
        out[c] = max(cands, key=lambda p: projects.get(p, 0)) if cands else None
    return out


# ───────────────────────── Upload ─────────────────────────


def _d(v: Any) -> date | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _clean_row(r: dict) -> dict | None:
    team = str(r.get("team") or "").strip()[:60]
    cx = str(r.get("complex") or "").strip()[:200]
    if not team or not cx:
        return None
    stage = " ".join(str(r.get("stage") or "").replace("🗹", "").split())[:120] or None
    is_deal = (stage or "").lower() in DEAL_STAGES
    try:
        amount = float(r["amount"]) if r.get("amount") not in (None, "") else None
    except (TypeError, ValueError):
        amount = None
    bd, dd = _d(r.get("booking_date")), _d(r.get("deal_date"))
    lot = (str(r.get("lot") or "").strip()[:80]) or None
    key = f"{team}|{cx}|{lot or ''}|{bd}|{amount}"
    return {
        "id": hashlib.md5(key.encode()).hexdigest(),
        "team": team,
        "complex": cx,
        "lot": lot,
        "amount": amount,
        "booking_date": bd,
        "deal_date": dd if is_deal else None,
        "stage": stage,
        "is_deal": is_deal,
        "payment": (str(r.get("payment") or "").strip()[:80]) or None,
        "lead_source": (str(r.get("lead_source") or "").strip()[:80]) or None,
    }


def replace_all(raw_rows: list[dict], source: str, market: pl.DataFrame) -> dict:
    """Replace our sales with a fresh export (one transaction), auto-match new complex names."""
    if not configured():
        raise RuntimeError("База не настроена (ESTADEL_DB_URL)")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Пустой файл: не найдено ни одной брони")
    if len(raw_rows) > MAX_UPLOAD_ROWS:
        raise ValueError(f"Слишком много строк: {len(raw_rows)}")
    clean: dict[str, dict] = {}
    for r in raw_rows:
        c = _clean_row(r) if isinstance(r, dict) else None
        if c and c["id"] not in clean:  # same booking listed twice → keep the first
            clean[c["id"]] = c
    data = list(clean.values())
    if not data:
        raise ValueError("Не удалось прочитать ни одной строки")

    cols = ["id", "team", "complex", "lot", "amount", "booking_date", "deal_date", "stage", "is_deal", "payment", "lead_source"]
    with _connect() as conn:
        with conn.transaction():
            known = {r[0] for r in conn.execute("select complex from analytics.complex_map").fetchall()}
            new_names = sorted({x["complex"] for x in data} - known)
            matched = {}
            if new_names:
                projects = {
                    r["object"]: int(r["len"])
                    for r in market.filter(pl.col("object").is_not_null()).group_by("object").len().iter_rows(named=True)
                }
                matched = auto_match(new_names, projects)
                with conn.cursor() as cur:
                    cur.executemany(
                        "insert into analytics.complex_map (complex, project, note) values (%s, %s, %s) on conflict (complex) do nothing",
                        [(n, matched[n], "auto" if matched[n] else "нет в реестре") for n in new_names],
                    )
            conn.execute("delete from analytics.estadel_deals")
            with conn.cursor() as cur:
                cur.executemany(
                    f"insert into analytics.estadel_deals ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})",
                    [tuple(x[c] for c in cols) for x in data],
                )
            deals = sum(1 for x in data if x["is_deal"])
            conn.execute(
                "insert into analytics.load_runs (source, rows, deals) values (%s, %s, %s)",
                (source[:200], len(data), deals),
            )
    invalidate()
    st = status()
    return {
        "rows": len(data),
        "deals": deals,
        "new_complexes": [{"complex": n, "project": matched.get(n)} for n in new_names],
        "status": st,
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }
