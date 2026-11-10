"""«Факторы»: why sales changed between a period and the same period a year earlier.

Everything here is computed from the deal registry alone (bnMAP / Росреестр):
who added the deals (projects, developers, new launches), bulk purchases, the mortgage
mix (banks, terms) and list-price moves. Channel (agency vs direct) and real contract
prices are not in the registry, so the module only flags candidates for checking.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from services.filters import filtered_deals
from services.widgets import _previous_period

WHOLESALE_COL = "Участие объекта в оптовой сделке"
MIN_PROJECT_DEALS = 10  # project needs this many deals in one of the periods to be listed
LONG_TERM_MONTHS = 348  # ≈ 30-year mortgage


def _with_flags(frame: pl.DataFrame) -> pl.DataFrame:
    cols = frame.columns

    def txt(col: str) -> pl.Expr:
        return pl.col(col).cast(pl.Utf8, strict=False).str.to_lowercase().fill_null("") if col in cols else pl.lit("")

    return frame.with_columns(
        txt(WHOLESALE_COL).str.contains("да").alias("_bulk"),
        (txt("buyer_type") == "юл").alias("_legal"),
        txt("contract_type").str.contains("уступ").alias("_resale"),
        pl.col("is_mortgage").fill_null(False).alias("_mort"),
        (
            (pl.col("mortgage_months").fill_null(0) >= LONG_TERM_MONTHS) & pl.col("is_mortgage").fill_null(False)
            if "mortgage_months" in cols
            else pl.lit(False)
        ).alias("_long"),
        (pl.col("bank") if "bank" in cols else pl.lit(None).cast(pl.Utf8)).alias("_bank"),
    )


def _share(part: int | float, total: int | float) -> float | None:
    return round(part / total * 100, 1) if total else None


def _pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / prev * 100, 1)


def _summary_stats(f: pl.DataFrame) -> dict[str, Any]:
    n = f.height
    if not n:
        return {"deals": 0}
    r = f.select(
        pl.col("_bulk").sum().alias("bulk"),
        pl.col("_legal").sum().alias("legal"),
        pl.col("_resale").sum().alias("resale"),
        pl.col("_mort").sum().alias("mort"),
        pl.col("_long").sum().alias("long"),
        pl.col("price_sqm").filter(pl.col("price_sqm") > 0).median().alias("sqm"),
    ).row(0, named=True)
    return {
        "deals": n,
        "deals_no_bulk": n - int(r["bulk"]),
        "bulk_share": _share(r["bulk"], n),
        "legal_share": _share(r["legal"], n),
        "resale_share": _share(r["resale"], n),
        "mortgage_share": _share(r["mort"], n),
        "long_share": _share(r["long"], r["mort"]),
        "sqm": round(r["sqm"]) if r["sqm"] else None,
    }


def _bank_counts(f: pl.DataFrame) -> dict[str, int]:
    m = f.filter(pl.col("_mort") & pl.col("_bank").is_not_null())
    return {r["_bank"]: int(r["len"]) for r in m.group_by("_bank").len().iter_rows(named=True)}


def _project_table(cur: pl.DataFrame, prev: pl.DataFrame) -> list[dict]:
    def agg(f: pl.DataFrame, suffix: str) -> pl.DataFrame:
        return f.group_by("object").agg(
            pl.len().alias(f"n{suffix}"),
            pl.col("_bulk").sum().alias(f"bulk{suffix}"),
            pl.col("_mort").sum().alias(f"mort{suffix}"),
            pl.col("_long").sum().alias(f"long{suffix}"),
            pl.col("price_sqm").filter(pl.col("price_sqm") > 0).median().alias(f"sqm{suffix}"),
            pl.col("developer").drop_nulls().first().alias(f"dev{suffix}"),
            pl.col("city").drop_nulls().first().alias(f"city{suffix}"),
            pl.col("sold_date").min().alias(f"first{suffix}"),
        )

    a, b = agg(cur, "1"), agg(prev, "0")
    t = a.join(b, on="object", how="full", coalesce=True)

    # Top bank per project and its share, in both periods.
    def top_bank(f: pl.DataFrame) -> dict[str, tuple[str, float]]:
        m = f.filter(pl.col("_mort") & pl.col("_bank").is_not_null())
        if m.is_empty():
            return {}
        c = m.group_by(["object", "_bank"]).len()
        tot = c.group_by("object").agg(pl.col("len").sum().alias("tot"))
        c = c.join(tot, on="object").with_columns((pl.col("len") / pl.col("tot") * 100).alias("share"))
        return {
            r["object"]: (r["_bank"], r["share"], r["tot"])
            for r in c.sort("len", descending=True).group_by("object", maintain_order=True).first().iter_rows(named=True)
        }

    def bank_share(f: pl.DataFrame) -> dict[tuple[str, str], float]:
        m = f.filter(pl.col("_mort") & pl.col("_bank").is_not_null())
        if m.is_empty():
            return {}
        c = m.group_by(["object", "_bank"]).len()
        tot = c.group_by("object").agg(pl.col("len").sum().alias("tot"))
        c = c.join(tot, on="object").with_columns((pl.col("len") / pl.col("tot") * 100).alias("share"))
        return {(r["object"], r["_bank"]): r["share"] for r in c.iter_rows(named=True)}

    tb1 = top_bank(cur)  # (bank, share %, mortgage deals)
    bs0 = bank_share(prev)

    rows = []
    for r in t.iter_rows(named=True):
        n1, n0 = int(r.get("n1") or 0), int(r.get("n0") or 0)
        if max(n1, n0) < MIN_PROJECT_DEALS:
            continue
        bank = tb1.get(r["object"])
        bank_name, bank_sh = (bank[0], round(bank[1])) if bank else (None, None)
        bank_prev = round(bs0.get((r["object"], bank_name), 0.0)) if bank_name and n0 else None
        long1 = _share(r.get("long1") or 0, r.get("mort1") or 0)
        long0 = _share(r.get("long0") or 0, r.get("mort0") or 0)
        rows.append(
            {
                "object": r["object"],
                "developer": r.get("dev1") or r.get("dev0"),
                "city": r.get("city1") or r.get("city0"),
                "prev": n0,
                "cur": n1,
                "delta": n1 - n0,
                "delta_pct": _pct(n1, n0),
                "is_new": n0 == 0 and n1 > 0,
                "bulk": int(r.get("bulk1") or 0),
                "mortgage_share": _share(r.get("mort1") or 0, n1),
                "mortgage_share_prev": _share(r.get("mort0") or 0, n0),
                "long_share": long1,
                "long_share_prev": long0,
                "top_bank": bank_name,
                "top_bank_share": bank_sh,
                "top_bank_share_prev": bank_prev,
                "sqm": round(r["sqm1"]) if r.get("sqm1") else None,
                "sqm_prev": round(r["sqm0"]) if r.get("sqm0") else None,
                "sqm_pct": _pct(r.get("sqm1"), r.get("sqm0")),
            }
        )
    rows.sort(key=lambda x: x["delta"], reverse=True)
    return rows


def _bulk_events(cur: pl.DataFrame) -> list[dict]:
    b = cur.filter(pl.col("_bulk"))
    if b.is_empty():
        return []
    ev = (
        b.group_by(["object", "sold_month"])
        .agg(pl.len().alias("n"), pl.col("developer").drop_nulls().first().alias("developer"))
        .filter(pl.col("n") >= 10)
        .sort("n", descending=True)
    )
    month_total = {
        (r["object"], r["sold_month"]): r["len"]
        for r in cur.group_by(["object", "sold_month"]).len().iter_rows(named=True)
    }
    return [
        {
            "object": r["object"],
            "developer": r["developer"],
            "month": r["sold_month"],
            "n": int(r["n"]),
            "month_total": int(month_total.get((r["object"], r["sold_month"]), r["n"])),
        }
        for r in ev.head(15).iter_rows(named=True)
    ]


def _bank_programs(cur: pl.DataFrame) -> list[dict]:
    """A bank that suddenly takes a big share of a project's mortgages for a few months
    usually means a developer + bank programme (subsidised rate, low or zero down payment)."""
    m = cur.filter(pl.col("_mort") & pl.col("_bank").is_not_null() & pl.col("object").is_not_null())
    if m.is_empty():
        return []
    pm = m.group_by(["object", "sold_month", "_bank"]).len()
    tot = pm.group_by(["object", "sold_month"]).agg(pl.col("len").sum().alias("tot"))
    pm = pm.join(tot, on=["object", "sold_month"]).with_columns((pl.col("len") / pl.col("tot")).alias("share"))
    out = []
    for (obj, bank), g in pm.group_by(["object", "_bank"]):
        g = g.sort("sold_month")
        hot = g.filter((pl.col("share") >= 0.2) & (pl.col("tot") >= 8))
        if hot.height < 2:
            continue
        months = hot["sold_month"].to_list()
        hot_share = hot["len"].sum() / hot["tot"].sum()
        # Outside the hot months the bank must be much weaker — otherwise it is just the usual bank.
        tot_obj = tot.filter(pl.col("object") == obj)
        other = tot_obj.filter(~pl.col("sold_month").is_in(months))
        other_bank = g.filter(~pl.col("sold_month").is_in(months))["len"].sum()
        other_share = other_bank / other["tot"].sum() if other.height and other["tot"].sum() else None
        if other_share is None or other_share > hot_share / 2.5:
            continue
        out.append(
            {
                "object": obj,
                "bank": bank,
                "months": months,
                "from": months[0],
                "to": months[-1],
                "hot_share": round(hot_share * 100),
                "other_share": round(other_share * 100),
                "deals": int(hot["len"].sum()),
            }
        )
    out.sort(key=lambda x: x["deals"], reverse=True)
    return out[:12]


def _price_premiums(cur: pl.DataFrame) -> list[dict]:
    """Mortgage deals priced well above cash deals in the same project and quarter.
    Zero-down-payment schemes often inflate the contract price; bnMAP mostly prices
    lots from price lists, so this is only a hint to check, not proof."""
    f = cur.filter(~pl.col("_bulk") & (pl.col("price_sqm") > 0) & pl.col("object").is_not_null())
    if f.is_empty():
        return []
    f = f.with_columns(
        (pl.col("sold_date").dt.year().cast(pl.Utf8) + "-Q" + ((pl.col("sold_date").dt.month() - 1) // 3 + 1).cast(pl.Utf8)).alias("q")
    )
    g = f.group_by(["object", "q", "_mort"]).agg(pl.col("price_sqm").median().alias("p"), pl.len().alias("n"))
    m = g.filter(pl.col("_mort")).drop("_mort").rename({"p": "pm", "n": "nm"})
    c = g.filter(~pl.col("_mort")).drop("_mort").rename({"p": "pc", "n": "nc"})
    j = m.join(c, on=["object", "q"]).filter((pl.col("nm") >= 8) & (pl.col("nc") >= 8))
    j = j.with_columns(((pl.col("pm") / pl.col("pc") - 1) * 100).alias("prem")).filter(pl.col("prem") >= 12)
    return [
        {
            "object": r["object"],
            "quarter": r["q"],
            "premium": round(r["prem"], 1),
            "mortgage_sqm": round(r["pm"]),
            "cash_sqm": round(r["pc"]),
            "n_mortgage": int(r["nm"]),
            "n_cash": int(r["nc"]),
        }
        for r in j.sort("prem", descending=True).head(10).iter_rows(named=True)
    ]


def _fmt_n(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", " ")


_MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _mon(key: str) -> str:
    """'2026-08' → 'авг 2026', '2026-Q1' → '1 кв. 2026'."""
    k = str(key)
    if "-Q" in k:
        y, q = k.split("-Q")
        return f"{q} кв. {y}"
    if len(k) >= 7 and k[4] == "-":
        return f"{_MONTHS[int(k[5:7]) - 1]} {k[:4]}"
    return k


def _signed_pct(v: float) -> str:
    return f"+{v:.0f}%" if v > 0 else f"−{abs(v):.0f}%" if v < 0 else "0%"


def _sign(n: float) -> str:
    return f"+{_fmt_n(n)}" if n > 0 else f"−{_fmt_n(abs(n))}" if n < 0 else "0"


def _narrative(s1: dict, s0: dict, projects: list[dict], devs: list[dict], bulk: list[dict], programs: list[dict], premiums: list[dict], banks: list[dict]) -> list[str]:
    lines: list[str] = []
    d = s1["deals"] - s0["deals"]
    pct = _pct(s1["deals"], s0["deals"])
    lines.append(
        f"Сделок {_fmt_n(s1['deals'])} против {_fmt_n(s0['deals'])} годом раньше"
        + (f" ({_signed_pct(pct)})." if pct is not None else ".")
    )

    if s0["deals"] and (s1.get("bulk_share") or 0) - (s0.get("bulk_share") or 0) >= 2:
        pct_nb = _pct(s1["deals_no_bulk"], s0["deals_no_bulk"])
        lines.append(
            f"Оптовые покупки выросли: {s0['bulk_share']:.0f}% → {s1['bulk_share']:.0f}% сделок. "
            f"Без опта изменение {_signed_pct(pct_nb)}." if pct_nb is not None else
            f"Оптовые покупки выросли: {s0['bulk_share']:.0f}% → {s1['bulk_share']:.0f}% сделок."
        )

    if projects and d:
        movers = [p for p in projects if (p["delta"] > 0) == (d > 0)]
        movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
        top = movers[:3]
        top_sum = sum(p["delta"] for p in top)
        if top and abs(d) > 0:
            share = top_sum / d * 100
            names = ", ".join(f"{p['object']} ({_sign(p['delta'])})" for p in top)
            if share > 100:
                lines.append(
                    f"Изменение дали несколько проектов: {names} — вместе {_sign(top_sum)} при общем {_sign(d)}, "
                    "остальной рынок в сумме двигался в обратную сторону."
                )
            elif share >= 60:
                lines.append(f"Изменение сосредоточено в нескольких проектах: {names} — это {share:.0f}% от общего {_sign(d)}.")
            else:
                lines.append(f"Больше всего изменились: {names}.")
        new = [p for p in projects if p["is_new"]]
        if new:
            new_sum = sum(p["cur"] for p in new)
            lines.append(
                f"Новые проекты (не было продаж годом раньше) дали {_fmt_n(new_sum)} сделок: "
                + ", ".join(p["object"] for p in sorted(new, key=lambda x: -x["cur"])[:4]) + "."
            )
        against = [p for p in projects if (p["delta"] < 0) == (d > 0) and abs(p["delta"]) >= 20]
        if against:
            against.sort(key=lambda x: abs(x["delta"]), reverse=True)
            lines.append(
                ("При этом просели: " if d > 0 else "При этом выросли: ")
                + ", ".join(f"{p['object']} ({_sign(p['delta'])})" for p in against[:3]) + "."
            )

    if devs and d:
        top_dev = devs[0] if d > 0 else devs[-1]
        if abs(top_dev["delta"]) >= max(10, abs(d) * 0.4):
            lines.append(f"Главный вклад — застройщик {top_dev['name']}: {_sign(top_dev['delta'])} сделок.")

    for ev in bulk[:2]:
        lines.append(
            f"Оптовая покупка: {ev['object']}, {_mon(ev['month'])} — {_fmt_n(ev['n'])} лотов из {_fmt_n(ev['month_total'])} сделок месяца."
        )

    if s1.get("mortgage_share") is not None and s0.get("mortgage_share") is not None:
        dm = s1["mortgage_share"] - s0["mortgage_share"]
        if abs(dm) >= 3:
            lines.append(f"Доля ипотеки {'выросла' if dm > 0 else 'снизилась'}: {s0['mortgage_share']:.0f}% → {s1['mortgage_share']:.0f}%.")
    if s1.get("long_share") is not None and s0.get("long_share") is not None and s1["long_share"] - s0["long_share"] >= 5:
        lines.append(f"Ипотек на 30 лет стало больше: {s0['long_share']:.0f}% → {s1['long_share']:.0f}% ипотечных сделок.")

    surging = [b for b in banks if b["prev"] >= 5 and b["cur"] >= 3 * b["prev"] and b["cur"] >= 30]
    surging += [b for b in banks if b["prev"] < 5 and b["cur"] >= 30]
    for b in surging[:2]:
        lines.append(f"{b['name']}: {_fmt_n(b['prev'])} → {_fmt_n(b['cur'])} ипотек — резкий рост одного банка.")
    for p in programs[:3]:
        period = _mon(p["from"]) if p["from"] == p["to"] else f"{_mon(p['from'])} — {_mon(p['to'])}"
        lines.append(
            f"Похоже на программу с банком: {p['object']} × {p['bank']}, {period} — {p['hot_share']}% ипотек проекта "
            f"(в остальные месяцы {p['other_share']}%)."
        )
    for p in premiums[:2]:
        lines.append(
            f"Проверить ипотеку без ПВ: {p['object']}, {_mon(p['quarter'])} — ипотечные лоты в среднем на {p['premium']:.0f}% дороже "
            f"за м², чем купленные без ипотеки."
        )

    price_up = [p for p in projects if (p["sqm_pct"] or 0) >= 10 and (p["delta_pct"] or 0) <= -20 and p["prev"] >= 30]
    price_dn = [p for p in projects if (p["sqm_pct"] or 0) <= -7 and (p["delta_pct"] or 0) >= 20 and p["cur"] >= 30]
    for p in price_up[:2]:
        lines.append(f"{p['object']}: цена м² {_signed_pct(p['sqm_pct'])}, продажи {_signed_pct(p['delta_pct'])} — похоже, подорожание затормозило спрос.")
    for p in price_dn[:2]:
        lines.append(f"{p['object']}: цена м² {_signed_pct(p['sqm_pct'])}, продажи {_signed_pct(p['delta_pct'])} — снижение цены разогнало продажи.")
    return lines


def sales_drivers(df: pl.DataFrame, a: dict[str, Any]) -> dict:
    args = {**a, "mortgage_mode": "all"}
    cur = filtered_deals(df, args, use_mortgage=False)
    prev = _previous_period(df, args, cur)
    if prev is None:
        return {"message": "Выберите год или период — сравнение идёт с тем же периодом годом раньше"}
    if cur.is_empty():
        return {"message": "Нет сделок под выбранные фильтры"}
    cur, prev = _with_flags(cur), _with_flags(prev)

    s1, s0 = _summary_stats(cur), _summary_stats(prev)
    projects = _project_table(cur, prev)

    dev = (
        cur.group_by("developer").len().select("developer", pl.col("len").cast(pl.Int64).alias("cur"))
        .join(
            prev.group_by("developer").len().select("developer", pl.col("len").cast(pl.Int64).alias("prev")),
            on="developer",
            how="full",
            coalesce=True,
        )
        .fill_null(0)
        .with_columns((pl.col("cur") - pl.col("prev")).alias("delta"))
        .filter(pl.col("developer").is_not_null() & ((pl.col("cur") >= MIN_PROJECT_DEALS) | (pl.col("prev") >= MIN_PROJECT_DEALS)))
        .sort("delta", descending=True)
    )
    devs = [{"name": r["developer"], "cur": int(r["cur"]), "prev": int(r["prev"]), "delta": int(r["delta"])} for r in dev.iter_rows(named=True)]

    b1, b0 = _bank_counts(cur), _bank_counts(prev)
    banks = sorted(
        ({"name": k, "cur": b1.get(k, 0), "prev": b0.get(k, 0), "delta": b1.get(k, 0) - b0.get(k, 0)} for k in set(b1) | set(b0)),
        key=lambda x: -x["cur"],
    )[:12]

    bulk = _bulk_events(cur)
    programs = _bank_programs(cur)
    premiums = _price_premiums(cur)

    # Contribution chart: biggest movers either way.
    movers = sorted(projects, key=lambda x: abs(x["delta"]), reverse=True)[:14]
    movers.sort(key=lambda x: x["delta"], reverse=True)
    cur_days = cur.select(pl.col("sold_date").min().alias("a"), pl.col("sold_date").max().alias("b")).row(0, named=True)
    prev_days = prev.select(pl.col("sold_date").min().alias("a"), pl.col("sold_date").max().alias("b")).row(0, named=True) if not prev.is_empty() else {"a": None, "b": None}

    return {
        "message": None,
        "period": {"from": str(cur_days["a"]), "to": str(cur_days["b"])},
        "prev_period": {"from": str(prev_days["a"]) if prev_days["a"] else None, "to": str(prev_days["b"]) if prev_days["b"] else None},
        "summary": s1,
        "summary_prev": s0,
        "narrative": _narrative(s1, s0, projects, devs, bulk, programs, premiums, banks),
        "contributions": [{"name": p["object"], "value": p["delta"]} for p in movers],
        "developers": devs[:8] + [x for x in devs[-5:] if x not in devs[:8]],
        "projects": projects[:300],
        "bulk_events": bulk,
        "bank_programs": programs,
        "price_premiums": premiums,
        "banks": banks,
    }
