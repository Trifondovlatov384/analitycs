from __future__ import annotations

import csv
import io
import math
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from dash import Dash, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from dash import dash_table
import plotly.graph_objects as go
import polars as pl

from aggregations import (
    apply_filters,
    city_deal_counts,
    complex_comparison_metrics,
    complex_monthly_counts,
    kpis,
    monthly_avg_price,
    monthly_deal_counts,
    yearly_top_complexes,
)
from data_loader import list_sorted, load_crimea_deals, load_deals, resolve_data_path
from heatmap_loader import load_matrix_csv
from project_growth_logic import (
    compute_project_growth,
    compute_room_growth,
    filter_project_growth_deals,
    project_growth_dimension_options,
)
from ui import layout


# ---- Helpers (declared before callbacks) ----

def pl_from_dicts(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def pl_col(name: str) -> pl.Expr:
    return pl.col(name)


def _dash_int(value: object, default: int) -> int:
    """dcc.Slider may pass None before the client has applied the value."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_multi_str(value: object) -> list[str]:
    """
    dcc.Dropdown(multi=True) usually returns a list, but some clients/edge cases
    may pass a single string. Polars `is_in(str)` then treats the string as a
    column name and raises.
    """
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


def _normalize_ru(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace("ё", "е")


def _to_float_loose(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace("\u00A0", "")
    s = s.replace(",", ".")
    s = s.replace("'", "")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_city_from_object(text: str) -> str:
    value = text or ""
    patterns = [
        r"\bг\.\s*([А-Яа-яЁёA-Za-z\- ]{2,60})",
        r"\bгород\s+([А-Яа-яЁёA-Za-z\- ]{2,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        city = match.group(1).strip(" ,.;:()\"'")
        # Stop at common separators.
        city = re.split(r"[,;:()]", city)[0].strip()
        if city:
            return city
    return ""


def _load_egrz_filtered_rows(filtered_path: Path) -> list[dict[str, str]]:
    if not filtered_path.exists():
        return []
    rows: list[dict[str, str]] = []
    with filtered_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=";")
        for row in reader:
            object_name = row.get(
                "Наименование и адрес (местоположение) объекта капитального строительства, применительно к которому подготовлена проектная документация",
                "",
            ) or ""
            prepared = dict(row)
            prepared["РНС"] = row.get("Номер заключения экспертизы", "") or ""
            prepared["Дата в реестре"] = row.get("Дата включения сведений в реестр", "") or ""
            prepared["Объект"] = object_name
            prepared["Застройщик"] = row.get(
                "Сведения о застройщике, обеспечившем подготовку проектной документации",
                "",
            ) or ""
            prepared["Ключи"] = row.get("MatchedKeywords", "") or ""
            prepared["Город"] = _extract_city_from_object(object_name)
            rows.append(prepared)
    return rows


def _apply_egrz_filters(
    rows: list[dict[str, str]],
    region_values: list[str] | None,
    work_type_values: list[str] | None,
    search_text: str | None,
) -> list[dict[str, str]]:
    region_set = set(_normalize_multi_str(region_values))
    work_set = set(_normalize_multi_str(work_type_values))
    search_norm = _normalize_ru(search_text)
    filtered_rows: list[dict[str, str]] = []

    for row in rows:
        if region_set and row["Субъект РФ"] not in region_set:
            continue
        if work_set and row["Вид работ"] not in work_set:
            continue
        if search_norm:
            haystack = _normalize_ru(
                f"{row.get('Объект', '')} {row.get('Застройщик', '')} {row.get('РНС', '')} {row.get('Ключи', '')} {row.get('Город', '')}"
            )
            if search_norm not in haystack:
                continue
        filtered_rows.append(row)
    return filtered_rows


def _filter_heatmap_deals(
    dff: pl.DataFrame,
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
    if deals_source and deals_source != "all":
        dff = dff.filter(pl_col("source") == deals_source)
    y = _dash_year(year)
    if y is not None:
        dff = dff.filter(pl_col("year") == y)
    if agglomeration and agglomeration != "all":
        dff = dff.filter(pl_col("agglomeration") == agglomeration)

    districts = _normalize_multi_str(districts_sel)
    if districts:
        dff = dff.filter(pl_col("loc_district").is_in(districts))

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


def make_monthly_counts_figure(df: pl.DataFrame) -> go.Figure:
    m = monthly_deal_counts(df)
    if m.is_empty():
        fig = go.Figure()
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320)
        return fig

    x = m["sold_month"].to_list()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=m["deals_total"].to_list(),
            mode="lines+markers",
            name="Всего",
            hovertemplate="Месяц=%{x}<br>Сделок=%{y}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=m["deals_mortgage"].to_list(),
            mode="lines+markers",
            name="Ипотека",
            hovertemplate="Месяц=%{x}<br>Сделок (ипотека)=%{y}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=m["deals_non_mortgage"].to_list(),
            mode="lines+markers",
            name="Не ипотека",
            hovertemplate="Месяц=%{x}<br>Сделок (не ипотека)=%{y}<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=320,
        xaxis_title="",
        yaxis_title="Сделки",
        hovermode="x unified",
    )
    return fig


def make_monthly_avg_figure(df: pl.DataFrame) -> go.Figure:
    m = monthly_avg_price(df)
    fig = go.Figure()
    if m.is_empty():
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320)
        return fig

    fig.add_trace(
        go.Scatter(
            x=m["sold_month"].to_list(),
            y=m["avg_est_budget"].to_list(),
            mode="lines+markers",
            name="Средняя цена",
            customdata=m.select(["deals_with_price", "sum_est_budget"]).to_numpy(),
            hovertemplate=(
                "Месяц=%{x}"
                "<br>Средняя цена=%{y:,.0f} ₽"
                "<br>Сделок с ценой=%{customdata[0]}"
                "<br>Объём=%{customdata[1]:,.0f} ₽"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=320,
        xaxis_title="",
        yaxis_title="₽",
        hovermode="x unified",
    )
    return fig


def make_top_complexes_figure(df_top: pl.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df_top.is_empty():
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=360)
        return fig

    fig.add_trace(
        go.Bar(
            x=df_top["deals"].to_list(),
            y=df_top["object"].to_list(),
            orientation="h",
            hovertemplate="Комплекс=%{y}<br>Сделок=%{x}<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=360,
        xaxis_title="Сделки",
        yaxis_title="",
        yaxis=dict(autorange="reversed"),
    )
    return fig


def make_city_counts_figure(df_city: pl.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df_city.is_empty():
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=420)
        return fig

    top = df_city.head(25)
    fig.add_trace(
        go.Bar(
            x=top["deals"].to_list(),
            y=top["city"].to_list(),
            orientation="h",
            hovertemplate="Город=%{y}<br>Сделок=%{x}<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=420,
        xaxis_title="Сделки",
        yaxis_title="",
        yaxis=dict(autorange="reversed"),
    )
    return fig


def make_complex_monthly_figure(df_monthly: pl.DataFrame, *, complex_name: str | None) -> go.Figure:
    fig = go.Figure()
    if df_monthly.is_empty() or not complex_name:
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320)
        return fig

    fig.add_trace(
        go.Bar(
            x=df_monthly["sold_month"].to_list(),
            y=df_monthly["deals"].to_list(),
            hovertemplate="Месяц=%{x}<br>Продано лотов=%{y}<extra></extra>",
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=320,
        xaxis_title="",
        yaxis_title="Продано лотов",
    )
    return fig


def make_complex_compare_figure(
    df_cmp: pl.DataFrame,
    *,
    selected_objects: list[str] | None = None,
) -> go.Figure:
    fig = go.Figure()
    if df_cmp.is_empty():
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=360)
        return fig

    top = df_cmp.head(80)
    selected_set = {x for x in (selected_objects or []) if isinstance(x, str) and x.strip()}
    objects = top["object"].to_list()
    selected_points = [i for i, obj in enumerate(objects) if obj in selected_set]
    fig.add_trace(
        go.Scatter(
            x=top["avg_price_sqm"].to_list(),
            y=top["avg_budget"].to_list(),
            mode="markers",
            marker=dict(
                size=[max(8, min(30, int(v / 5))) for v in top["deals"].to_list()],
                opacity=0.7,
            ),
            text=top["object"].to_list(),
            customdata=top.select(["city", "developer", "deals"]).to_numpy(),
            selectedpoints=selected_points,
            selected=dict(marker=dict(opacity=1.0, line=dict(color="#111827", width=2))),
            unselected=dict(marker=dict(opacity=0.25)),
            hovertemplate=(
                "Комплекс=%{text}"
                "<br>Город=%{customdata[0]}"
                "<br>Девелопер=%{customdata[1]}"
                "<br>Сделок=%{customdata[2]}"
                "<br>Средняя цена м²=%{x:,.0f} ₽"
                "<br>Средний бюджет=%{y:,.0f} ₽"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=360,
        clickmode="event+select",
        xaxis_title="Средняя цена м², ₽",
        yaxis_title="Средний бюджет сделки, ₽",
    )
    return fig


def make_heatmap_figure(
    *,
    objects: list[str],
    display_objects: list[str] | None,
    months: list[str],
    z: list[list[int]],
) -> go.Figure:
    fig = go.Figure()
    if not objects or not months:
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=650)
        return fig

    # Convert zeros to "missing" for color so they stay white/empty,
    # but keep true values for hover via customdata.
    z_color: list[list[int | None]] = []
    text: list[list[str]] = []
    for row in z:
        zr: list[int | None] = []
        tr: list[str] = []
        for v in row:
            vv = int(v) if v is not None else 0
            if vv == 0:
                zr.append(None)
                tr.append("")
            else:
                zr.append(vv)
                tr.append(str(vv))
        z_color.append(zr)
        text.append(tr)

    flat = [int(v) for row in z for v in row if v is not None]
    # Clip extremes for colorscale so mid-range is readable.
    # Keep true values in text/hover.
    nonzero = [v for v in flat if v > 0]
    base = nonzero if nonzero else flat
    zmin = float(pl.Series(base).quantile(0.05)) if base else 0.0
    zmax = float(pl.Series(base).quantile(0.95)) if base else 1.0
    if zmax <= zmin:
        zmin = min(base) if base else 0.0
        zmax = max(base) if base else 1.0

    colorscale = [
        [0.0, "#d73027"],  # red
        [0.5, "#fee08b"],  # yellow
        [1.0, "#1a9850"],  # green
    ]

    fig.add_trace(
        go.Heatmap(
            z=z_color,
            x=months,
            y=(display_objects or objects),
            colorscale=colorscale,
            zmin=zmin,
            zmax=zmax,
            xgap=2,
            ygap=2,
            text=text,
            texttemplate="%{text}",
            textfont=dict(size=10, color="black"),
            customdata=[
                [[obj, int(val)] for val in row]
                for obj, row in zip(objects, z)
            ],
            hovertemplate="Комплекс=%{customdata[0]}<br>Месяц=%{x}<br>Сделок=%{customdata[1]}<extra></extra>",
            colorbar=dict(title="Сделки"),
        )
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=max(650, 18 * len(objects) + 180),
        xaxis=dict(side="top"),
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return fig


def _euler_short_label(name: str, *, max_len: int = 36) -> str:
    s = (name or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def make_euler_figure(devs: list[str], sizes: dict[str, int], pair: dict[tuple[str, str], int], triple: int) -> go.Figure:
    fig = go.Figure()
    if len(devs) < 2:
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=420,
            annotations=[dict(text="Выберите 2-3 проекта (ЖК)", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")],
        )
        return fig

    positions = [(0.42, 0.56), (0.58, 0.56), (0.50, 0.42)]
    radii = [0.20, 0.20, 0.20]
    colors = ["rgba(54, 162, 235, 0.35)", "rgba(255, 99, 132, 0.35)", "rgba(75, 192, 92, 0.35)"]

    for i, d in enumerate(devs):
        x, y = positions[i]
        r = radii[i]
        fig.add_shape(
            type="circle",
            xref="paper",
            yref="paper",
            x0=x - r,
            x1=x + r,
            y0=y - r,
            y1=y + r,
            line=dict(color=colors[i].replace("0.35", "1"), width=2),
            fillcolor=colors[i],
        )
        fig.add_annotation(
            x=x, y=y + r + 0.05, xref="paper", yref="paper",
            text=f"{_euler_short_label(d)}<br>Сделок: {sizes.get(d, 0)}",
            showarrow=False, align="center",
        )

    if len(devs) >= 2:
        p12 = pair.get((devs[0], devs[1]), pair.get((devs[1], devs[0]), 0))
        fig.add_annotation(x=0.50, y=0.58, xref="paper", yref="paper", text=f"{p12}", showarrow=False)
    if len(devs) == 3:
        p13 = pair.get((devs[0], devs[2]), pair.get((devs[2], devs[0]), 0))
        p23 = pair.get((devs[1], devs[2]), pair.get((devs[2], devs[1]), 0))
        fig.add_annotation(x=0.46, y=0.47, xref="paper", yref="paper", text=f"{p13}", showarrow=False)
        fig.add_annotation(x=0.54, y=0.47, xref="paper", yref="paper", text=f"{p23}", showarrow=False)
        fig.add_annotation(x=0.50, y=0.51, xref="paper", yref="paper", text=f"{triple}", showarrow=False, font=dict(size=14))

    fig.update_xaxes(visible=False, range=[0, 1])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=420)
    return fig


def create_app() -> Dash:
    df_main = load_deals().with_columns(pl.lit("main").alias("source"))
    try:
        df_crimea = load_crimea_deals().with_columns(pl.lit("crimea").alias("source"))
    except Exception:
        df_crimea = pl.DataFrame({"source": []})

    df = pl.concat([df_main, df_crimea], how="diagonal")
    if "deal_status" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("deal_status"))
    df = df.with_columns(
        [
            pl.when(pl.col("source") == "main")
            .then(pl.col("ipoteka"))
            .otherwise(pl.col("deal_status"))
            .cast(pl.Utf8)
            .alias("deal_status"),
        ]
    )

    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.FLATLY],
        title="Сделки недвижимости — дашборд",
        suppress_callback_exceptions=True,
    )

    years = sorted([int(y) for y in df.select("year").unique().drop_nulls().to_series().to_list()])
    default_year = years[-1] if years else None

    # IMPORTANT: do NOT send full dataset to the browser (it is huge).
    # Keep data server-side and only send small UI state.
    app.layout = html.Div(
        [
            dcc.Store(id="meta_years", data=years),
            dcc.Store(id="meta_default_year", data=default_year),
            layout(),
        ]
    )

    @app.callback(
        Output("year", "options"),
        Output("year", "value"),
        Input("meta_years", "data"),
        Input("meta_default_year", "data"),
    )
    def _init_years(meta_years: list[int], meta_default_year: int | None):
        opts = [{"label": str(y), "value": int(y)} for y in (meta_years or [])]
        return opts, meta_default_year

    @app.callback(
        Output("c_year", "options"),
        Output("c_year", "value"),
        Input("meta_years", "data"),
        Input("meta_default_year", "data"),
    )
    def _init_years_complexes(meta_years: list[int], meta_default_year: int | None):
        opts = [{"label": str(y), "value": int(y)} for y in (meta_years or [])]
        return opts, meta_default_year

    @app.callback(
        Output("cmp_year", "options"),
        Output("cmp_year", "value"),
        Input("meta_years", "data"),
        Input("meta_default_year", "data"),
    )
    def _init_years_compare(meta_years: list[int], meta_default_year: int | None):
        opts = [{"label": str(y), "value": int(y)} for y in (meta_years or [])]
        return opts, meta_default_year

    @app.callback(
        Output("e_year", "options"),
        Output("e_year", "value"),
        Input("meta_years", "data"),
        Input("meta_default_year", "data"),
    )
    def _init_years_euler(meta_years: list[int], meta_default_year: int | None):
        opts = [{"label": str(y), "value": int(y)} for y in (meta_years or [])]
        return opts, meta_default_year

    @app.callback(
        Output("h_year", "options"),
        Output("h_year", "value"),
        Output("nh_year", "options"),
        Output("nh_year", "value"),
        Input("meta_years", "data"),
        Input("meta_default_year", "data"),
    )
    def _init_years_heatmap(meta_years: list[int], meta_default_year: int | None):
        opts = [{"label": str(y), "value": int(y)} for y in (meta_years or [])]
        return opts, meta_default_year, opts, meta_default_year

    @app.callback(
        Output("pg_year", "options"),
        Output("pg_year", "value"),
        Input("meta_years", "data"),
        Input("meta_default_year", "data"),
    )
    def _init_years_project_growth(meta_years: list[int], meta_default_year: int | None):
        opts = [{"label": str(y), "value": int(y)} for y in (meta_years or [])]
        return opts, meta_default_year

    @app.callback(
        Output("city", "options"),
        Output("city", "value"),
        Output("developer", "options"),
        Output("developer", "value"),
        Output("type_lot", "options"),
        Output("type_lot", "value"),
        Output("months", "options"),
        Output("months", "value"),
        Input("source", "value"),
        Input("agglomeration", "value"),
        Input("year", "value"),
        State("city", "value"),
        State("developer", "value"),
        State("type_lot", "value"),
        State("months", "value"),
    )
    def _refresh_dimension_options(
        source: str,
        agglomeration: str,
        year: int | None,
        city_selected: list[str],
        developer_selected: list[str],
        type_lot_selected: list[str],
        months_selected: list[str],
    ):
        dff = df
        if source and source != "all":
            dff = dff.filter(pl_col("source") == source)
        if year is not None:
            dff = dff.filter(pl_col("year") == year)
        if agglomeration and agglomeration != "all":
            dff = dff.filter(pl_col("agglomeration") == agglomeration)

        cities = list_sorted(dff.select("city").unique().to_series().to_list())
        devs = list_sorted(dff.select("developer").unique().to_series().to_list())
        lots = list_sorted(dff.select("type_lot").unique().to_series().to_list())
        months = list_sorted(dff.select("sold_month").unique().to_series().to_list())

        cities_set = set(cities)
        devs_set = set(devs)
        lots_set = set(lots)
        months_set = set(months)

        city_selected = [c for c in (city_selected or []) if c in cities_set]
        developer_selected = [d for d in (developer_selected or []) if d in devs_set]
        type_lot_selected = [t for t in (type_lot_selected or []) if t in lots_set]
        months_selected = [m for m in (months_selected or []) if m in months_set]

        return (
            [{"label": c, "value": c} for c in cities],
            city_selected,
            [{"label": d, "value": d} for d in devs],
            developer_selected,
            [{"label": t, "value": t} for t in lots],
            type_lot_selected,
            [{"label": m, "value": m} for m in months],
            months_selected,
        )

    @app.callback(
        Output("kpi_total_deals", "children"),
        Output("kpi_sum_budget", "children"),
        Output("kpi_avg_budget", "children"),
        Output("fig_monthly_counts", "figure"),
        Output("fig_monthly_avg", "figure"),
        Output("fig_top_complexes_total", "figure"),
        Output("fig_top_complexes_mortgage", "figure"),
        Input("year", "value"),
        Input("months", "value"),
        Input("source", "value"),
        Input("agglomeration", "value"),
        Input("city", "value"),
        Input("mortgage_mode", "value"),
        Input("developer", "value"),
        Input("type_lot", "value"),
    )
    def _update_dashboard(
        year: int | None,
        months: list[str],
        source: str,
        agglomeration: str,
        cities: list[str],
        mortgage_mode: str,
        developers: list[str],
        type_lots: list[str],
    ):
        dff = df

        years = [int(year)] if year is not None else None
        months_sel = months or None
        cities_sel = cities or None
        dev_sel = developers or None
        lot_sel = type_lots or None
        sources = None if (not source or source == "all") else [source]

        # Base filter for the dataset (without mortgage filter),
        # so breakdown charts remain informative even when mortgage_mode is set.
        base_filtered = apply_filters(
            dff,
            years=years,
            months=months_sel,
            agglomeration=agglomeration,
            cities=cities_sel,
            mortgage_mode="all",
            sources=sources,
            developers=dev_sel,
            type_lots=lot_sel,
        )

        filtered_for_kpi = apply_filters(
            base_filtered,
            years=None,
            months=None,
            agglomeration=None,
            cities=None,
            mortgage_mode=mortgage_mode,
            sources=None,
            developers=None,
            type_lots=None,
        )

        k = kpis(filtered_for_kpi)

        fig_counts = make_monthly_counts_figure(base_filtered)
        fig_avg = make_monthly_avg_figure(filtered_for_kpi)

        fig_top_total = go.Figure()
        fig_top_mortgage = go.Figure()
        if year is not None:
            top_total = yearly_top_complexes(base_filtered, year=int(year), only_mortgage=False).head(25)
            top_mort = yearly_top_complexes(base_filtered, year=int(year), only_mortgage=True).head(25)
            fig_top_total = make_top_complexes_figure(top_total)
            fig_top_mortgage = make_top_complexes_figure(top_mort)

        return (
            f"{int(k['total_deals']):,}".replace(",", " "),
            f"{int(k['sum_budget']):,}".replace(",", " "),
            f"{int(k['avg_budget']):,}".replace(",", " "),
            fig_counts,
            fig_avg,
            fig_top_total,
            fig_top_mortgage,
        )

    @app.callback(
        Output("c_city", "options"),
        Output("c_city", "value"),
        Output("c_type_lot", "options"),
        Output("c_type_lot", "value"),
        Output("c_months", "options"),
        Output("c_months", "value"),
        Output("c_object", "options"),
        Output("c_object", "value"),
        Input("c_source", "value"),
        Input("c_agglomeration", "value"),
        Input("c_year", "value"),
        State("c_city", "value"),
        State("c_type_lot", "value"),
        State("c_months", "value"),
        State("c_object", "value"),
    )
    def _refresh_complexes_dimensions(
        source: str,
        agglomeration: str,
        year: int | None,
        city_selected: list[str],
        type_lot_selected: list[str],
        months_selected: list[str],
        object_selected: str | None,
    ):
        dff = df
        if source and source != "all":
            dff = dff.filter(pl_col("source") == source)
        if year is not None:
            dff = dff.filter(pl_col("year") == year)
        if agglomeration and agglomeration != "all":
            dff = dff.filter(pl_col("agglomeration") == agglomeration)

        cities = list_sorted(dff.select("city").unique().to_series().to_list())
        lots = list_sorted(dff.select("type_lot").unique().to_series().to_list())
        months = list_sorted(dff.select("sold_month").unique().to_series().to_list())
        objects = list_sorted(dff.select("object").unique().to_series().to_list())

        cities_set = set(cities)
        lots_set = set(lots)
        months_set = set(months)
        objects_set = set(objects)

        city_selected = [c for c in (city_selected or []) if c in cities_set]
        type_lot_selected = [t for t in (type_lot_selected or []) if t in lots_set]
        months_selected = [m for m in (months_selected or []) if m in months_set]
        object_selected = object_selected if object_selected in objects_set else None

        return (
            [{"label": c, "value": c} for c in cities],
            city_selected,
            [{"label": t, "value": t} for t in lots],
            type_lot_selected,
            [{"label": m, "value": m} for m in months],
            months_selected,
            [{"label": o, "value": o} for o in objects],
            object_selected,
        )

    @app.callback(
        Output("c_fig_city_counts", "figure"),
        Output("c_fig_complex_monthly", "figure"),
        Input("c_year", "value"),
        Input("c_months", "value"),
        Input("c_source", "value"),
        Input("c_agglomeration", "value"),
        Input("c_city", "value"),
        Input("c_mortgage_mode", "value"),
        Input("c_type_lot", "value"),
        Input("c_object", "value"),
    )
    def _update_complexes_tab(
        year: int | None,
        months: list[str],
        source: str,
        agglomeration: str,
        cities: list[str],
        mortgage_mode: str,
        type_lots: list[str],
        complex_name: str | None,
    ):
        dff = df
        years = [int(year)] if year is not None else None
        months_sel = months or None
        cities_sel = cities or None
        sources = None if (not source or source == "all") else [source]
        type_lots_sel = type_lots or None

        base = apply_filters(
            dff,
            years=years,
            months=months_sel,
            agglomeration=agglomeration,
            cities=cities_sel,
            mortgage_mode=mortgage_mode,
            sources=sources,
            developers=None,
            type_lots=type_lots_sel,
        )

        city_counts = city_deal_counts(base)
        fig_city = make_city_counts_figure(city_counts)

        if complex_name:
            monthly = complex_monthly_counts(base, complex_name=complex_name)
        else:
            monthly = pl.DataFrame({"sold_month": [], "deals": []})
        fig_complex = make_complex_monthly_figure(monthly, complex_name=complex_name)

        return fig_city, fig_complex

    @app.callback(
        Output("cmp_city", "options"),
        Output("cmp_city", "value"),
        Output("cmp_type_lot", "options"),
        Output("cmp_type_lot", "value"),
        Output("cmp_months", "options"),
        Output("cmp_months", "value"),
        Input("cmp_source", "value"),
        Input("cmp_agglomeration", "value"),
        Input("cmp_year", "value"),
        State("cmp_city", "value"),
        State("cmp_type_lot", "value"),
        State("cmp_months", "value"),
    )
    def _refresh_compare_dimensions(
        source: str,
        agglomeration: str,
        year: int | None,
        city_selected: list[str],
        type_lot_selected: list[str],
        months_selected: list[str],
    ):
        dff = df
        if source and source != "all":
            dff = dff.filter(pl_col("source") == source)
        if year is not None:
            dff = dff.filter(pl_col("year") == year)
        if agglomeration and agglomeration != "all":
            dff = dff.filter(pl_col("agglomeration") == agglomeration)

        cities = list_sorted(dff.select("city").unique().to_series().to_list())
        lots = list_sorted(dff.select("type_lot").unique().to_series().to_list())
        months = list_sorted(dff.select("sold_month").unique().to_series().to_list())

        cities_set = set(cities)
        lots_set = set(lots)
        months_set = set(months)
        city_selected = [c for c in (city_selected or []) if c in cities_set]
        type_lot_selected = [t for t in (type_lot_selected or []) if t in lots_set]
        months_selected = [m for m in (months_selected or []) if m in months_set]

        return (
            [{"label": c, "value": c} for c in cities],
            city_selected,
            [{"label": t, "value": t} for t in lots],
            type_lot_selected,
            [{"label": m, "value": m} for m in months],
            months_selected,
        )

    @app.callback(
        Output("cmp_fig_complex_compare", "figure"),
        Output("cmp_tbl_complex_compare", "children"),
        Input("cmp_year", "value"),
        Input("cmp_months", "value"),
        Input("cmp_source", "value"),
        Input("cmp_agglomeration", "value"),
        Input("cmp_city", "value"),
        Input("cmp_mortgage_mode", "value"),
        Input("cmp_type_lot", "value"),
        Input("cmp_selected_complexes", "data"),
    )
    def _update_compare_tab(
        year: int | None,
        months: list[str],
        source: str,
        agglomeration: str,
        cities: list[str],
        mortgage_mode: str,
        type_lots: list[str],
        selected_complexes: list[str] | None,
    ):
        years = [int(year)] if year is not None else None
        months_sel = months or None
        cities_sel = cities or None
        sources = None if (not source or source == "all") else [source]
        type_lots_sel = type_lots or None

        base = apply_filters(
            df,
            years=years,
            months=months_sel,
            agglomeration=agglomeration,
            cities=cities_sel,
            mortgage_mode=mortgage_mode,
            sources=sources,
            developers=None,
            type_lots=type_lots_sel,
        )

        cmp_df = complex_comparison_metrics(base).filter(
            pl.col("avg_price_sqm").is_not_null() & (pl.col("avg_price_sqm") > 0)
        )
        fig_cmp = make_complex_compare_figure(cmp_df, selected_objects=selected_complexes)

        cmp_view = (
            cmp_df.select(
                [
                    pl.col("object").alias("Комплекс"),
                    pl.col("city").alias("Город"),
                    pl.col("developer").alias("Девелопер"),
                    pl.col("deals").alias("Сделок"),
                    pl.col("avg_budget").round(0).alias("Средний бюджет, ₽"),
                    pl.col("avg_price_sqm").round(0).alias("Средняя цена м², ₽"),
                ]
            )
            .sort("Средний бюджет, ₽", descending=True)
            .head(300)
        )
        selected_set = {x for x in (selected_complexes or []) if isinstance(x, str) and x.strip()}
        if selected_set:
            cmp_selected = (
                cmp_view.filter(pl.col("Комплекс").is_in(list(selected_set)))
                .sort("Средний бюджет, ₽", descending=True)
            )
            if not cmp_selected.is_empty():
                cmp_view = cmp_selected
        tbl = dash_table.DataTable(
            data=cmp_view.to_dicts(),
            columns=[{"name": c, "id": c} for c in cmp_view.columns],
            page_size=12,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12},
            style_header={"fontWeight": "600"},
        )
        return fig_cmp, tbl

    @app.callback(
        Output("cmp_selected_complexes", "data"),
        Input("cmp_fig_complex_compare", "clickData"),
        Input("cmp_clear_selected", "n_clicks"),
        State("cmp_selected_complexes", "data"),
        prevent_initial_call=True,
    )
    def _toggle_compare_selected(
        click_data: dict | None,
        clear_clicks: int | None,
        selected_complexes: list[str] | None,
    ):
        selected = [x for x in (selected_complexes or []) if isinstance(x, str) and x.strip()]
        trigger = getattr(callback_context, "triggered", [])
        trigger_id = ""
        if trigger:
            trigger_id = str(trigger[0].get("prop_id", "")).split(".")[0]

        if trigger_id == "cmp_clear_selected":
            return []

        if not click_data or "points" not in click_data or not click_data["points"]:
            raise PreventUpdate

        point = click_data["points"][0]
        object_name = point.get("text")
        if not object_name:
            raise PreventUpdate

        if object_name in selected:
            selected = [x for x in selected if x != object_name]
        else:
            selected.append(object_name)
        return selected

    @app.callback(
        Output("e_city", "options"),
        Output("e_city", "value"),
        Output("e_projects", "options"),
        Output("e_projects", "value"),
        Input("e_source", "value"),
        Input("e_year", "value"),
        Input("e_type_lot", "value"),
        State("e_city", "value"),
        State("e_projects", "value"),
    )
    def _refresh_euler_dimensions(
        source: str,
        year: int | None,
        type_lot: str,
        city_selected: list[str],
        projects_selected: list[str],
    ):
        dff = df
        if source and source != "all":
            dff = dff.filter(pl.col("source") == source)
        y = _dash_year(year)
        if y is not None:
            dff = dff.filter(pl.col("year") == y)
        if type_lot:
            dff = dff.filter(pl.col("type_lot") == type_lot)
        cities = list_sorted(dff.select("city").unique().to_series().to_list())
        objs = (
            dff.with_columns(pl.col("object").str.strip_chars().alias("object"))
            .filter(pl.col("object").is_not_null() & (pl.col("object") != ""))
            .select("object")
            .unique()
            .to_series()
            .to_list()
        )
        projects = list_sorted(objs)
        cities_set = set(cities)
        projects_set = set(projects)
        city_selected = [c for c in _normalize_multi_str(city_selected) if c in cities_set]
        projects_selected = [p for p in _normalize_multi_str(projects_selected) if p in projects_set][:3]
        return (
            [{"label": c, "value": c} for c in cities],
            city_selected,
            [{"label": p, "value": p} for p in projects],
            projects_selected,
        )

    @app.callback(
        Output("e_fig_euler", "figure"),
        Output("e_tbl_overlaps", "children"),
        Output("e_fig_weighted_overlap", "figure"),
        Output("e_tbl_weighted", "children"),
        Input("e_source", "value"),
        Input("e_year", "value"),
        Input("e_city", "value"),
        Input("e_projects", "value"),
        Input("e_type_lot", "value"),
        Input("e_target_budget", "value"),
        Input("e_delta_budget", "value"),
        Input("e_corridor_step", "value"),
    )
    def _update_euler_tab(
        source: str,
        year: int | None,
        cities: list[str],
        projects: list[str],
        type_lot: str,
        target_budget: int,
        delta_budget: int,
        corridor_step: int,
    ):
        target_budget = _dash_int(target_budget, 8_000_000)
        delta_budget = _dash_int(delta_budget, 3_000_000)
        corridor_step = _dash_int(corridor_step, 1_000_000)

        projects = _normalize_multi_str(projects)[:3]

        try:
            cities = _normalize_multi_str(cities)
            dff = df
            if source and source != "all":
                dff = dff.filter(pl.col("source") == source)
            y = _dash_year(year)
            if y is not None:
                dff = dff.filter(pl.col("year") == y)
            if cities:
                dff = dff.filter(pl.col("city").is_in(cities))
            if type_lot:
                dff = dff.filter(pl.col("type_lot") == type_lot)

            # Полоса бюджета; сравниваем выбранные ЖК по общим коридорам (разные проекты → ключ = коридор).
            low = float(target_budget - delta_budget)
            high = float(target_budget + delta_budget)
            dff = (
                dff.filter(pl.col("est_budget").is_not_null())
                .filter((pl.col("est_budget") >= low) & (pl.col("est_budget") <= high))
                .with_columns(pl.col("object").str.strip_chars().alias("object"))
                .filter(pl.col("object").is_not_null() & (pl.col("object") != ""))
            )

            if len(projects) < 2:
                fig = make_euler_figure(projects, {}, {}, 0)
                empty = go.Figure().update_layout(
                    margin=dict(l=10, r=10, t=10, b=10),
                    height=260,
                    annotations=[dict(text="Выберите 2-3 проекта (ЖК)", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")],
                )
                return fig, dbc.Alert("Выберите 2–3 проекта (ЖК) для сравнения.", color="light"), empty, html.Div()

            dff = dff.filter(pl.col("object").is_in(projects))

            step = max(1, int(corridor_step or 1_000_000))
            bucket_expr = (pl.col("est_budget") / step).floor().cast(pl.Int64).alias("budget_bucket")
            dd = dff.with_columns([bucket_expr])

            agg = dd.group_by(["object", "budget_bucket"]).agg(pl.len().alias("cnt"))
            counts: dict[str, dict[int, int]] = {p: {} for p in projects}
            for row in agg.iter_rows(named=True):
                proj = str(row["object"])
                if proj not in counts:
                    continue
                try:
                    b = int(row["budget_bucket"])
                    cnt = int(row["cnt"])
                except (TypeError, ValueError, KeyError):
                    continue
                counts[proj][b] = cnt

            sizes = {p: sum(counts[p].values()) for p in projects}
            keys = {p: set(counts[p].keys()) for p in projects}

            def _pair_overlap(a: str, b: str) -> int:
                shared = keys[a] & keys[b]
                return sum(min(counts[a][k], counts[b][k]) for k in shared)

            pair: dict[tuple[str, str], int] = {}
            for i in range(len(projects)):
                for j in range(i + 1, len(projects)):
                    a, b = projects[i], projects[j]
                    pair[(a, b)] = _pair_overlap(a, b)

            triple = 0
            if len(projects) == 3:
                a, b, c = projects[0], projects[1], projects[2]
                shared = keys[a] & keys[b] & keys[c]
                triple = sum(min(counts[a][k], counts[b][k], counts[c][k]) for k in shared)

            fig = make_euler_figure(projects, sizes, pair, triple)

            rows = []
            for p in projects:
                rows.append(
                    {
                        "Показатель": f"Сделок в полосе «{p}» (прокси клиентов)",
                        "Значение": int(sizes[p]),
                    }
                )
            for p in projects:
                rows.append(
                    {
                        "Показатель": f"Уникальных коридоров бюджета «{p}»",
                        "Значение": int(len(keys[p])),
                    }
                )
            for (a, b), v in pair.items():
                rows.append(
                    {
                        "Показатель": f"Пересечение сделок «{a}» ∩ «{b}» (общий коридор бюджета)",
                        "Значение": int(v),
                    }
                )
            if len(projects) == 3:
                rows.append(
                    {
                        "Показатель": f"Тройное пересечение «{projects[0]}» ∩ «{projects[1]}» ∩ «{projects[2]}»",
                        "Значение": int(triple),
                    }
                )

            tbl = dash_table.DataTable(
                data=rows,
                columns=[{"name": "Показатель", "id": "Показатель"}, {"name": "Значение", "id": "Значение"}],
                style_table={"overflowX": "auto"},
                style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12},
                style_header={"fontWeight": "600"},
            )

            # Weighted overlap by distribution similarity over corridors (per project).
            dist_rows = (
                dff.with_columns([bucket_expr])
                .group_by(["object", "budget_bucket"])
                .agg(pl.len().alias("cnt"))
                .filter(pl.col("object").is_in(projects))
            )
            buckets = sorted(dist_rows.select("budget_bucket").unique().to_series().to_list())
            vectors: dict[str, list[float]] = {}
            for p in projects:
                dsub = dist_rows.filter(pl.col("object") == p)
                mp = {int(r[0]): int(r[1]) for r in dsub.select(["budget_bucket", "cnt"]).iter_rows()}
                vec = [float(mp.get(int(b), 0)) for b in buckets]
                s = sum(vec)
                vectors[p] = [v / s if s > 0 else 0.0 for v in vec]

            def sim(a: str, b: str) -> float:
                va, vb = vectors[a], vectors[b]
                tvd = 0.5 * sum(abs(x - y) for x, y in zip(va, vb))
                return max(0.0, 1.0 - tvd)

            pair_scores: list[tuple[str, str, float]] = []
            for i in range(len(projects)):
                for j in range(i + 1, len(projects)):
                    a, b = projects[i], projects[j]
                    pair_scores.append((f"{a} vs {b}", _euler_short_label(f"{a} vs {b}", max_len=40), sim(a, b)))

            wfig = go.Figure()
            if pair_scores:
                ys = []
                for p in pair_scores:
                    val = round(p[2] * 100, 2)
                    if isinstance(val, float) and not math.isfinite(val):
                        val = 0.0
                    ys.append(val)
                wfig.add_trace(
                    go.Bar(
                        x=[p[1] for p in pair_scores],
                        y=ys,
                        hovertext=[p[0] for p in pair_scores],
                        hovertemplate="%{hovertext}<br>Сходство=%{y:.2f}%<extra></extra>",
                    )
                )
            wfig.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
                yaxis_title="Сходство, %",
            )

            wrows = []
            for p in pair_scores:
                pct = round(p[2] * 100, 2)
                if isinstance(pct, float) and not math.isfinite(pct):
                    pct = 0.0
                wrows.append({"Пара": p[0], "Сходство, %": pct})
            wtbl = dash_table.DataTable(
                data=wrows,
                columns=[{"name": "Пара", "id": "Пара"}, {"name": "Сходство, %", "id": "Сходство, %"}],
                style_table={"overflowX": "auto"},
                style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12},
                style_header={"fontWeight": "600"},
            )

            return fig, tbl, wfig, wtbl
        except Exception as e:
            traceback.print_exc()
            fig_err = go.Figure().update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
                annotations=[
                    dict(
                        text="Ошибка расчёта (см. консоль сервера)",
                        showarrow=False,
                        x=0.5,
                        y=0.5,
                        xref="paper",
                        yref="paper",
                    )
                ],
            )
            alert = dbc.Alert(
                f"Ошибка вкладки «Эйлер»: {type(e).__name__}: {e}",
                color="danger",
            )
            return fig_err, alert, fig_err, alert

    @app.callback(
        Output("cmp_fullscreen_modal", "is_open"),
        Input("cmp_open_fullscreen", "n_clicks"),
        Input("cmp_close_fullscreen", "n_clicks"),
        State("cmp_fullscreen_modal", "is_open"),
        prevent_initial_call=True,
    )
    def _toggle_compare_fullscreen(open_clicks: int, close_clicks: int, is_open: bool):
        return not is_open

    @app.callback(
        Output("cmp_fig_complex_compare_full", "figure"),
        Input("cmp_fig_complex_compare", "figure"),
    )
    def _sync_compare_figure_to_modal(fig: dict):
        if not fig:
            raise PreventUpdate
        return fig

    @app.callback(
        Output("h_city", "options"),
        Output("h_district", "options"),
        Output("h_type_lot", "options"),
        Input("h_deals_source", "value"),
        Input("h_agglomeration", "value"),
        Input("h_year", "value"),
    )
    def _heatmap_dimension_options(deals_source: str, agglomeration: str, year: int | None):
        dff = df
        if deals_source and deals_source != "all":
            dff = dff.filter(pl_col("source") == deals_source)
        y = _dash_year(year)
        if y is not None:
            dff = dff.filter(pl_col("year") == y)
        if agglomeration and agglomeration != "all":
            dff = dff.filter(pl_col("agglomeration") == agglomeration)
        cities = list_sorted(dff.select("city").unique().to_series().to_list())
        districts = list_sorted(dff.select("loc_district").unique().to_series().to_list())
        types = list_sorted(dff.select("type_lot").unique().to_series().to_list())
        return (
            [{"label": c, "value": c} for c in cities],
            [{"label": d, "value": d} for d in districts],
            [{"label": t, "value": t} for t in types],
        )

    @app.callback(
        Output("h_fig_heatmap", "figure"),
        Input("h_source", "value"),
        Input("h_year", "value"),
        Input("h_deals_source", "value"),
        Input("h_agglomeration", "value"),
        Input("h_city", "value"),
        Input("h_district", "value"),
        Input("h_type_lot", "value"),
        Input("h_mortgage_mode", "value"),
        Input("h_data_quality_flags", "value"),
        Input("h_top_n", "value"),
    )
    def _update_heatmap(
        source: str,
        year: int | None,
        deals_source: str,
        agglomeration: str,
        cities_sel: list[str],
        districts_sel: list[str],
        type_lot_sel: list[str],
        mortgage_mode: str,
        data_quality_flags: list[str],
        top_n: int,
    ):
        if source == "matrix_crimea":
            # By requirement: only two files. We try common locations.
            candidates = [
                os.environ.get("CRIMEA_MATRIX_PATH", ""),
                str(Path.cwd() / "Аналитика сделок по Крыму - По кол-ву.csv"),
                "/Users/nikitavisicki/Downloads/Аналитика сделок по Крыму - По кол-ву.csv",
            ]
            matrix_path = next((p for p in candidates if p and Path(p).exists()), "")
            if not matrix_path:
                return make_heatmap_figure(objects=[], display_objects=None, months=[], z=[])

            m = load_matrix_csv(matrix_path)
            if not m or m.df.is_empty():
                return make_heatmap_figure(objects=[], display_objects=None, months=[], z=[])

            # Sort by total descending, take top_n
            cols = m.columns
            dfm = m.df
            if cols:
                dfm = dfm.with_columns(pl.sum_horizontal([pl.col(c) for c in cols]).alias("_total"))
                dfm = dfm.sort("_total", descending=True).drop("_total").head(int(top_n))

            objects = dfm[m.row_label].to_list()
            months = cols
            z = [dfm.select(cols).row(i) for i in range(dfm.height)]
            z = [[int(v) if v is not None else 0 for v in row] for row in z]
            totals = [sum(row) for row in z]
            display_objects = [f"{name} ({total})" for name, total in zip(objects, totals)]
            return make_heatmap_figure(objects=objects, display_objects=display_objects, months=months, z=z)

        # Default: build from deals with the same filters used across the heatmap tab.
        filtered = _filter_heatmap_deals(
            df,
            deals_source=deals_source,
            year=year,
            agglomeration=agglomeration,
            cities_sel=cities_sel,
            districts_sel=districts_sel,
            type_lot_sel=type_lot_sel,
            mortgage_mode=mortgage_mode,
            data_quality_flags=data_quality_flags,
        )

        if filtered.is_empty():
            return make_heatmap_figure(objects=[], display_objects=None, months=[], z=[])

        # count deals per complex per month
        grouped = (
            filtered.group_by(["object", "sold_month"])
            .agg(pl.len().alias("deals"))
        )

        # total by complex -> top_n
        top_objects = (
            grouped.group_by("object")
            .agg(pl.sum("deals").alias("total"))
            .sort("total", descending=True)
            .head(int(top_n))
            .select("object")
            .to_series()
            .to_list()
        )

        grouped = grouped.filter(pl.col("object").is_in(top_objects))

        months = list_sorted(grouped.select("sold_month").unique().to_series().to_list())
        objects = top_objects

        # Build dense matrix
        pivot = (
            grouped.pivot(
                index="object",
                columns="sold_month",
                values="deals",
                aggregate_function="sum",
            )
            .fill_null(0)
        )

        # Ensure column order for months and row order for objects
        for mcol in months:
            if mcol not in pivot.columns:
                pivot = pivot.with_columns(pl.lit(0).alias(mcol))
        pivot = pivot.select(["object"] + months)

        # Align rows
        pivot = pivot.join(pl.DataFrame({"object": objects}), on="object", how="right").fill_null(0)
        pivot = pivot.select(["object"] + months)

        z = [pivot.select(months).row(i) for i in range(pivot.height)]
        z = [[int(v) if v is not None else 0 for v in row] for row in z]

        totals = [sum(row) for row in z]
        display_objects = [f"{name} ({total})" for name, total in zip(objects, totals)]
        return make_heatmap_figure(objects=objects, display_objects=display_objects, months=months, z=z)

    @app.callback(
        Output("nh_city", "options"),
        Output("nh_district", "options"),
        Output("nh_type_lot", "options"),
        Input("nh_year", "value"),
    )
    def _nh_dimension_options(year: int | None):
        dff = df
        y = _dash_year(year)
        if y is not None:
            dff = dff.filter(pl_col("year") == y)
        cities = list_sorted(dff.select("city").unique().to_series().to_list())
        districts = list_sorted(dff.select("loc_district").unique().to_series().to_list())
        types = list_sorted(dff.select("type_lot").unique().to_series().to_list())
        return (
            [{"label": c, "value": c} for c in cities],
            [{"label": d, "value": d} for d in districts],
            [{"label": t, "value": t} for t in types],
        )

    @app.callback(
        Output("nh_fig_heatmap", "figure"),
        Input("nh_year", "value"),
        Input("nh_city", "value"),
        Input("nh_district", "value"),
        Input("nh_type_lot", "value"),
        Input("nh_mortgage_mode", "value"),
        Input("nh_data_quality_flags", "value"),
        Input("nh_top_n", "value"),
    )
    def _nh_update_heatmap(
        year: int | None,
        city_sel: str | None,
        districts_sel: list[str],
        type_lot_sel: list[str],
        mortgage_mode: str,
        data_quality_flags: list[str],
        top_n: int,
    ):
        filtered = _filter_heatmap_deals(
            df,
            deals_source="all",
            year=year,
            agglomeration="all",
            cities_sel=city_sel,
            districts_sel=districts_sel,
            type_lot_sel=type_lot_sel,
            mortgage_mode=mortgage_mode,
            data_quality_flags=data_quality_flags,
        )

        if filtered.is_empty():
            return make_heatmap_figure(objects=[], display_objects=None, months=[], z=[])

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

        grouped = grouped.filter(pl.col("object").is_in(top_objects))

        months = list_sorted(grouped.select("sold_month").unique().to_series().to_list())
        objects = top_objects

        pivot = (
            grouped.pivot(
                index="object",
                columns="sold_month",
                values="deals",
                aggregate_function="sum",
            )
            .fill_null(0)
        )

        for mcol in months:
            if mcol not in pivot.columns:
                pivot = pivot.with_columns(pl.lit(0).alias(mcol))
        pivot = pivot.select(["object"] + months)

        pivot = pivot.join(pl.DataFrame({"object": objects}), on="object", how="right").fill_null(0)
        pivot = pivot.select(["object"] + months)

        z = [pivot.select(months).row(i) for i in range(pivot.height)]
        z = [[int(v) if v is not None else 0 for v in row] for row in z]

        totals = [sum(row) for row in z]
        display_objects = [f"{name} ({total})" for name, total in zip(objects, totals)]
        return make_heatmap_figure(objects=objects, display_objects=display_objects, months=months, z=z)

    @app.callback(
        Output("h_fig_dev_spikes", "figure"),
        Output("h_tbl_dev_spikes", "children"),
        Input("h_source", "value"),
        Input("h_year", "value"),
        Input("h_deals_source", "value"),
        Input("h_agglomeration", "value"),
        Input("h_city", "value"),
        Input("h_district", "value"),
        Input("h_type_lot", "value"),
        Input("h_mortgage_mode", "value"),
        Input("h_data_quality_flags", "value"),
        Input("h_spike_window", "value"),
        Input("h_spike_baseline_type", "value"),
    )
    def _update_developer_spikes(
        h_source: str,
        year: int | None,
        deals_source: str,
        agglomeration: str,
        cities_sel: list[str],
        districts_sel: list[str],
        type_lot_sel: list[str],
        mortgage_mode: str,
        data_quality_flags: list[str],
        spike_window: int,
        baseline_type: str,
    ):
        window = _dash_int(spike_window, 3)
        if window not in (3, 6, 12):
            window = 3
        baseline_type = baseline_type if baseline_type in ("mean", "median") else "mean"
        fig_empty = go.Figure().update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=340,
            annotations=[dict(text="Нет данных для анализа всплесков", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")],
        )
        if h_source == "matrix_crimea":
            return fig_empty, dbc.Alert("Для матрицы Крыма по застройщикам нет поштучных сделок. Переключите источник на «Основные сделки».", color="light")

        dff = _filter_heatmap_deals(
            df,
            deals_source=deals_source,
            year=year,
            agglomeration=agglomeration,
            cities_sel=cities_sel,
            districts_sel=districts_sel,
            type_lot_sel=type_lot_sel,
            mortgage_mode=mortgage_mode,
            data_quality_flags=data_quality_flags,
        )
        dff = dff.filter(pl.col("developer").is_not_null() & (pl.col("developer") != "") & pl.col("sold_month").is_not_null())
        if dff.is_empty():
            return fig_empty, dbc.Alert("После фильтров нет сделок по застройщикам.", color="light")

        shifts = [pl.col("deals").shift(i).over("developer").alias(f"d_l{i}") for i in range(1, window + 1)]
        baseline_expr = (
            pl.concat_list([pl.col(f"d_l{i}") for i in range(1, window + 1)]).list.drop_nulls().list.mean()
            if baseline_type == "mean"
            else pl.concat_list([pl.col(f"d_l{i}") for i in range(1, window + 1)]).list.drop_nulls().list.median()
        ).alias("baseline_win")

        monthly = (
            dff.group_by(["developer", "sold_month"])
            .agg(pl.len().alias("deals"))
            .sort(["developer", "sold_month"])
            .with_columns(pl.col("sold_month").str.slice(0, 4).cast(pl.Int32, strict=False).alias("sold_year"))
            .with_columns(shifts)
            .with_columns(baseline_expr)
            .with_columns(
                pl.when(pl.col("baseline_win").is_not_null() & (pl.col("baseline_win") > 0))
                .then(pl.col("deals") / pl.col("baseline_win"))
                .otherwise(None)
                .alias("spike_ratio")
            )
            .filter(pl.col("spike_ratio").is_not_null())
            .filter(pl.col("deals") >= 3)
            .sort("spike_ratio", descending=True)
        )
        yearly = monthly.group_by(["developer", "sold_year"]).agg(pl.sum("deals").alias("year_total"))
        monthly = (
            monthly.join(yearly, on=["developer", "sold_year"], how="left")
            .with_columns(
                pl.when(pl.col("year_total") > 0)
                .then(pl.col("deals") * 100.0 / pl.col("year_total"))
                .otherwise(None)
                .alias("year_share_pct")
            )
        )

        if monthly.is_empty():
            return fig_empty, dbc.Alert(f"Недостаточно истории (нужно минимум {window + 1} месяцев на застройщика).", color="light")

        top = monthly.head(25)
        labels = [f"{r['sold_month']} | {_euler_short_label(str(r['developer']), max_len=28)}" for r in top.iter_rows(named=True)]
        ratios = [round(float(r["spike_ratio"]), 2) for r in top.iter_rows(named=True)]
        hover = [
            f"{r['developer']}<br>{r['sold_month']}<br>Сделок={int(r['deals'])}<br>База {window}м ({'среднее' if baseline_type == 'mean' else 'медиана'})={float(r['baseline_win']):.2f}"
            for r in top.iter_rows(named=True)
        ]

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=labels,
                y=ratios,
                hovertext=hover,
                hovertemplate="%{hovertext}<extra></extra>",
            )
        )
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=340,
            yaxis_title="Коэффициент всплеска (к базе 3м)",
        )

        view = top.select(
            [
                pl.col("developer").alias("Застройщик"),
                pl.col("sold_month").alias("Месяц"),
                pl.col("deals").cast(pl.Int64).alias("Сделок"),
                pl.col("baseline_win").round(2).alias(
                    f"База {window}м ({'среднее' if baseline_type == 'mean' else 'медиана'})"
                ),
                pl.col("spike_ratio").round(2).alias("Всплеск, x"),
                pl.col("year_share_pct").round(2).alias("Доля в году, %"),
                pl.when(pl.col("spike_ratio") >= 2.0)
                .then(pl.lit("Сильный рост"))
                .when(pl.col("spike_ratio") >= 1.5)
                .then(pl.lit("Рост"))
                .when(pl.col("spike_ratio") < 0.8)
                .then(pl.lit("Падение"))
                .otherwise(pl.lit("Норма"))
                .alias("Сигнал"),
                pl.when(
                    (pl.col("spike_ratio") >= 1.8)
                    & (pl.col("deals") >= 5)
                    & (pl.col("year_share_pct") >= 10)
                )
                .then(pl.lit("Да"))
                .otherwise(pl.lit("Нет"))
                .alias("Аномалия"),
            ]
        )
        tbl = dash_table.DataTable(
            data=view.to_dicts(),
            columns=[{"name": c, "id": c} for c in view.columns],
            page_size=10,
            sort_action="native",
            sort_mode="single",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12},
            style_header={"fontWeight": "600"},
            style_data_conditional=[
                {"if": {"filter_query": "{Всплеск, x} >= 2.0", "column_id": "Всплеск, x"}, "backgroundColor": "#d4edda"},
                {"if": {"filter_query": "{Всплеск, x} >= 1.5 && {Всплеск, x} < 2.0", "column_id": "Всплеск, x"}, "backgroundColor": "#eaf7ea"},
                {"if": {"filter_query": "{Всплеск, x} < 0.8", "column_id": "Всплеск, x"}, "backgroundColor": "#f8d7da"},
                {"if": {"filter_query": "{Доля в году, %} >= 20", "column_id": "Доля в году, %"}, "fontWeight": "700"},
                {"if": {"filter_query": "{Сигнал} = \"Сильный рост\"", "column_id": "Сигнал"}, "backgroundColor": "#c3e6cb", "fontWeight": "700"},
                {"if": {"filter_query": "{Сигнал} = \"Рост\"", "column_id": "Сигнал"}, "backgroundColor": "#eaf7ea"},
                {"if": {"filter_query": "{Сигнал} = \"Падение\"", "column_id": "Сигнал"}, "backgroundColor": "#f8d7da"},
                {"if": {"filter_query": "{Аномалия} = \"Да\"", "column_id": "Аномалия"}, "backgroundColor": "#ffe8a1", "fontWeight": "700"},
            ],
        )
        return fig, tbl

    @app.callback(
        Output("h_fig_object_spikes", "figure"),
        Output("h_tbl_object_spikes", "children"),
        Input("h_source", "value"),
        Input("h_year", "value"),
        Input("h_deals_source", "value"),
        Input("h_agglomeration", "value"),
        Input("h_city", "value"),
        Input("h_district", "value"),
        Input("h_type_lot", "value"),
        Input("h_mortgage_mode", "value"),
        Input("h_data_quality_flags", "value"),
        Input("h_spike_window", "value"),
        Input("h_spike_baseline_type", "value"),
        Input("h_object_exclude", "value"),
    )
    def _update_object_spikes(
        h_source: str,
        year: int | None,
        deals_source: str,
        agglomeration: str,
        cities_sel: list[str],
        districts_sel: list[str],
        type_lot_sel: list[str],
        mortgage_mode: str,
        data_quality_flags: list[str],
        spike_window: int,
        baseline_type: str,
        object_exclude: list[str],
    ):
        window = _dash_int(spike_window, 3)
        if window not in (3, 6, 12):
            window = 3
        baseline_type = baseline_type if baseline_type in ("mean", "median") else "mean"
        fig_empty = go.Figure().update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=340,
            annotations=[dict(text="Нет данных для анализа всплесков", showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")],
        )
        if h_source == "matrix_crimea":
            return fig_empty, dbc.Alert("Для матрицы Крыма нет поштучных сделок по комплексам. Переключите источник на «Основные сделки».", color="light")

        dff = _filter_heatmap_deals(
            df,
            deals_source=deals_source,
            year=year,
            agglomeration=agglomeration,
            cities_sel=cities_sel,
            districts_sel=districts_sel,
            type_lot_sel=type_lot_sel,
            mortgage_mode=mortgage_mode,
            data_quality_flags=data_quality_flags,
        )
        dff = dff.filter(pl.col("object").is_not_null() & (pl.col("object") != "") & pl.col("sold_month").is_not_null())
        excluded = set(_normalize_multi_str(object_exclude))
        if excluded:
            dff = dff.filter(~pl.col("object").is_in(list(excluded)))
        if dff.is_empty():
            return fig_empty, dbc.Alert("После фильтров нет сделок по комплексам.", color="light")

        shifts = [pl.col("deals").shift(i).over("object").alias(f"d_l{i}") for i in range(1, window + 1)]
        baseline_expr = (
            pl.concat_list([pl.col(f"d_l{i}") for i in range(1, window + 1)]).list.drop_nulls().list.mean()
            if baseline_type == "mean"
            else pl.concat_list([pl.col(f"d_l{i}") for i in range(1, window + 1)]).list.drop_nulls().list.median()
        ).alias("baseline_win")

        monthly = (
            dff.group_by(["object", "sold_month"])
            .agg(pl.len().alias("deals"))
            .sort(["object", "sold_month"])
            .with_columns(pl.col("sold_month").str.slice(0, 4).cast(pl.Int32, strict=False).alias("sold_year"))
            .with_columns(shifts)
            .with_columns(baseline_expr)
            .with_columns(
                pl.when(pl.col("baseline_win").is_not_null() & (pl.col("baseline_win") > 0))
                .then(pl.col("deals") / pl.col("baseline_win"))
                .otherwise(None)
                .alias("spike_ratio")
            )
            .filter(pl.col("spike_ratio").is_not_null())
            .filter(pl.col("deals") >= 3)
            .sort("spike_ratio", descending=True)
        )
        yearly = monthly.group_by(["object", "sold_year"]).agg(pl.sum("deals").alias("year_total"))
        monthly = (
            monthly.join(yearly, on=["object", "sold_year"], how="left")
            .with_columns(
                pl.when(pl.col("year_total") > 0)
                .then(pl.col("deals") * 100.0 / pl.col("year_total"))
                .otherwise(None)
                .alias("year_share_pct")
            )
        )

        if monthly.is_empty():
            return fig_empty, dbc.Alert(f"Недостаточно истории (нужно минимум {window + 1} месяцев на комплекс).", color="light")

        top = monthly.head(25)
        labels = [f"{r['sold_month']} | {_euler_short_label(str(r['object']), max_len=28)}" for r in top.iter_rows(named=True)]
        ratios = [round(float(r["spike_ratio"]), 2) for r in top.iter_rows(named=True)]
        hover = [
            f"{r['object']}<br>{r['sold_month']}<br>Сделок={int(r['deals'])}<br>База {window}м ({'среднее' if baseline_type == 'mean' else 'медиана'})={float(r['baseline_win']):.2f}"
            for r in top.iter_rows(named=True)
        ]

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=labels,
                y=ratios,
                hovertext=hover,
                hovertemplate="%{hovertext}<extra></extra>",
            )
        )
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=340,
            yaxis_title="Коэффициент всплеска (к базе 3м)",
        )

        view = top.select(
            [
                pl.col("object").alias("Комплекс"),
                pl.col("sold_month").alias("Месяц"),
                pl.col("deals").cast(pl.Int64).alias("Сделок"),
                pl.col("baseline_win").round(2).alias(
                    f"База {window}м ({'среднее' if baseline_type == 'mean' else 'медиана'})"
                ),
                pl.col("spike_ratio").round(2).alias("Всплеск, x"),
                pl.col("year_share_pct").round(2).alias("Доля в году, %"),
                pl.when(pl.col("spike_ratio") >= 2.0)
                .then(pl.lit("Сильный рост"))
                .when(pl.col("spike_ratio") >= 1.5)
                .then(pl.lit("Рост"))
                .when(pl.col("spike_ratio") < 0.8)
                .then(pl.lit("Падение"))
                .otherwise(pl.lit("Норма"))
                .alias("Сигнал"),
                pl.when(
                    (pl.col("spike_ratio") >= 1.8)
                    & (pl.col("deals") >= 5)
                    & (pl.col("year_share_pct") >= 10)
                )
                .then(pl.lit("Да"))
                .otherwise(pl.lit("Нет"))
                .alias("Аномалия"),
            ]
        )
        tbl = dash_table.DataTable(
            data=view.to_dicts(),
            columns=[{"name": c, "id": c} for c in view.columns],
            page_size=10,
            sort_action="native",
            sort_mode="single",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12},
            style_header={"fontWeight": "600"},
            style_data_conditional=[
                {"if": {"filter_query": "{Всплеск, x} >= 2.0", "column_id": "Всплеск, x"}, "backgroundColor": "#d4edda"},
                {"if": {"filter_query": "{Всплеск, x} >= 1.5 && {Всплеск, x} < 2.0", "column_id": "Всплеск, x"}, "backgroundColor": "#eaf7ea"},
                {"if": {"filter_query": "{Всплеск, x} < 0.8", "column_id": "Всплеск, x"}, "backgroundColor": "#f8d7da"},
                {"if": {"filter_query": "{Доля в году, %} >= 20", "column_id": "Доля в году, %"}, "fontWeight": "700"},
                {"if": {"filter_query": "{Сигнал} = \"Сильный рост\"", "column_id": "Сигнал"}, "backgroundColor": "#c3e6cb", "fontWeight": "700"},
                {"if": {"filter_query": "{Сигнал} = \"Рост\"", "column_id": "Сигнал"}, "backgroundColor": "#eaf7ea"},
                {"if": {"filter_query": "{Сигнал} = \"Падение\"", "column_id": "Сигнал"}, "backgroundColor": "#f8d7da"},
                {"if": {"filter_query": "{Аномалия} = \"Да\"", "column_id": "Аномалия"}, "backgroundColor": "#ffe8a1", "fontWeight": "700"},
            ],
        )
        return fig, tbl

    @app.callback(
        Output("h_object_exclude", "options"),
        Output("h_object_exclude", "value"),
        Input("h_source", "value"),
        Input("h_year", "value"),
        Input("h_deals_source", "value"),
        Input("h_agglomeration", "value"),
        Input("h_city", "value"),
        Input("h_district", "value"),
        Input("h_type_lot", "value"),
        Input("h_mortgage_mode", "value"),
        Input("h_data_quality_flags", "value"),
        State("h_object_exclude", "value"),
    )
    def _update_object_exclude_options(
        h_source: str,
        year: int | None,
        deals_source: str,
        agglomeration: str,
        cities_sel: list[str],
        districts_sel: list[str],
        type_lot_sel: list[str],
        mortgage_mode: str,
        data_quality_flags: list[str],
        selected: list[str],
    ):
        if h_source == "matrix_crimea":
            return [], []
        dff = _filter_heatmap_deals(
            df,
            deals_source=deals_source,
            year=year,
            agglomeration=agglomeration,
            cities_sel=cities_sel,
            districts_sel=districts_sel,
            type_lot_sel=type_lot_sel,
            mortgage_mode=mortgage_mode,
            data_quality_flags=data_quality_flags,
        )
        objs = (
            dff.filter(pl.col("object").is_not_null() & (pl.col("object") != ""))
            .group_by("object")
            .agg(pl.len().alias("cnt"))
            .sort("cnt", descending=True)
            .head(300)
        )
        object_values = objs.select("object").to_series().to_list() if not objs.is_empty() else []
        options = [{"label": f"{o} ({c})", "value": o} for o, c in objs.select(["object", "cnt"]).iter_rows()] if not objs.is_empty() else []
        selected_norm = [x for x in _normalize_multi_str(selected) if x in set(object_values)]
        return options, selected_norm

    @app.callback(
        Output("h_click_details_title", "children"),
        Output("h_click_details_table", "children"),
        Input("h_fig_heatmap", "clickData"),
        Input("h_source", "value"),
        Input("h_year", "value"),
        Input("h_deals_source", "value"),
        Input("h_agglomeration", "value"),
        Input("h_city", "value"),
        Input("h_district", "value"),
        Input("h_type_lot", "value"),
        Input("h_mortgage_mode", "value"),
        Input("h_data_quality_flags", "value"),
    )
    def _heatmap_cell_details(
        click_data: dict | None,
        h_source: str,
        year: int | None,
        deals_source: str,
        agglomeration: str,
        cities_sel: list[str],
        districts_sel: list[str],
        type_lot_sel: list[str],
        mortgage_mode: str,
        data_quality_flags: list[str],
    ):
        if h_source == "matrix_crimea":
            return "Детализация недоступна для матрицы.", dbc.Alert(
                "В режиме «Крым (матрица)» у нас нет списка сделок поштучно. Переключите «Источник» на «Основные сделки», чтобы видеть детализацию.",
                color="light",
            )

        if not click_data or "points" not in click_data or not click_data["points"]:
            return "Кликните по ячейке, чтобы увидеть сделки.", ""

        p = click_data["points"][0]
        month_raw = p.get("x")
        month = None
        if month_raw is not None:
            month_s = str(month_raw)
            # Plotly may send either "YYYY-MM" or full date like "YYYY-MM-01".
            month = month_s[:7] if len(month_s) >= 7 else month_s
        obj = None

        # Preferred source: customdata (original object name).
        cd = p.get("customdata")
        if isinstance(cd, (list, tuple)) and len(cd) >= 1:
            obj = str(cd[0]) if cd[0] is not None else None

        # Fallback: parse from y label "Name (123)".
        if not obj:
            y_val = p.get("y")
            if y_val is not None:
                obj = re.sub(r"\s\(\d+\)$", "", str(y_val)).strip()

        if not obj or not month:
            return "Кликните по ячейке, чтобы увидеть сделки.", dbc.Alert(
                f"Не удалось распознать выбранную ячейку. clickData={click_data}",
                color="warning",
            )

        dff = _filter_heatmap_deals(
            df,
            deals_source=deals_source,
            year=year,
            agglomeration=agglomeration,
            cities_sel=cities_sel,
            districts_sel=districts_sel,
            type_lot_sel=type_lot_sel,
            mortgage_mode=mortgage_mode,
            data_quality_flags=data_quality_flags,
        )

        dff = dff.filter((pl_col("object") == obj) & (pl_col("sold_month") == month))

        if dff.is_empty():
            return f"{obj} — {month}: 0 сделок", dbc.Alert("Сделок не найдено (после фильтров).", color="light")

        # Columns for display
        view = dff.select(
            [
                pl.col("sold_date").alias("Дата"),
                pl.col("est_budget").alias("Стоимость"),
                pl.col("deal_status").alias("Статус"),
                pl.col("type_lot").alias("Тип объекта"),
                pl.col("source").alias("Регион"),
                pl.col("city").alias("Город"),
                pl.col("loc_district").alias("Район"),
                pl.col("developer").alias("Девелопер"),
            ]
        ).sort("Дата")

        rows = view.head(300).to_dicts()
        title = f"{obj} — {month}: {dff.height} сделок (показано до 300)"

        table = dash_table.DataTable(
            data=rows,
            columns=[{"name": c, "id": c} for c in view.columns],
            page_size=15,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12, "whiteSpace": "normal"},
            style_header={"fontWeight": "600"},
            style_data_conditional=[
                {"if": {"column_id": "Стоимость"}, "textAlign": "right"},
            ],
        )

        return title, table

    @app.callback(
        Output("tabs", "value"),
        Input("open_egrz_tab_button", "n_clicks"),
        prevent_initial_call=True,
    )
    def _open_egrz_tab(n_clicks: int):
        if not n_clicks:
            raise PreventUpdate
        return "tab_egrz"

    @app.callback(
        Output("egrz_log_preview", "children"),
        Output("egrz_last_outputs", "children"),
        Input("egrz_refresh_log", "n_clicks"),
        Input("egrz_run_button", "n_clicks"),
    )
    def _refresh_egrz_log_and_outputs(refresh_clicks: int | None, run_clicks: int | None):
        _ = (refresh_clicks, run_clicks)
        project_root = Path(__file__).resolve().parent
        log_path = project_root / "output" / "egrz_manual_run.log"
        filtered_path = project_root / "output" / "filtered_latest.csv"
        mind_map_path = project_root / "output" / "mind_map.json"

        if log_path.exists():
            log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            preview = "\n".join(log_lines[-80:]) if log_lines else "(лог пуст)"
        else:
            preview = "Лог пока не создан. Нажмите «Запустить EGRZ парсер (1 цикл)»."

        matched_count = 0
        if filtered_path.exists():
            with filtered_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
                reader = csv.DictReader(csv_file, delimiter=";")
                matched_count = sum(1 for _ in reader)

        filtered_mtime = (
            datetime.fromtimestamp(filtered_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            if filtered_path.exists()
            else "не создан"
        )
        map_mtime = (
            datetime.fromtimestamp(mind_map_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            if mind_map_path.exists()
            else "не создан"
        )

        outputs = dbc.ListGroup(
            [
                dbc.ListGroupItem(f"Отфильтрованных записей: {matched_count}"),
                dbc.ListGroupItem(f"filtered_latest.csv обновлён: {filtered_mtime}"),
                dbc.ListGroupItem(f"mind_map.json обновлён: {map_mtime}"),
            ],
            flush=True,
        )
        return preview, outputs

    @app.callback(
        Output("egrz_filter_region", "options"),
        Output("egrz_filter_work_type", "options"),
        Output("egrz_table_status", "children"),
        Output("egrz_table_container", "children"),
        Output("egrz_city_table_status", "children"),
        Output("egrz_city_table_container", "children"),
        Input("tabs", "value"),
        Input("egrz_filter_region", "value"),
        Input("egrz_filter_work_type", "value"),
        Input("egrz_filter_text", "value"),
        Input("egrz_page_size", "value"),
        Input("egrz_show_all_fields", "value"),
    )
    def _update_egrz_table(
        current_tab: str,
        region_values: list[str],
        work_type_values: list[str],
        search_text: str,
        page_size_value: str,
        show_all_fields: list[str],
    ):
        if current_tab != "tab_egrz":
            raise PreventUpdate

        project_root = Path(__file__).resolve().parent
        filtered_path = project_root / "output" / "filtered_latest.csv"
        rows = _load_egrz_filtered_rows(filtered_path)
        if not rows:
            alert = dbc.Alert(
                "Файл output/filtered_latest.csv пока не найден. Сначала запустите EGRZ парсер.",
                color="warning",
                className="mb-0",
            )
            return [], [], "Нет данных для отображения.", alert, "Нет данных по городам.", alert

        all_regions = sorted({r["Субъект РФ"] for r in rows if r.get("Субъект РФ")})
        all_work_types = sorted({r["Вид работ"] for r in rows if r.get("Вид работ")})
        region_options = [{"label": x, "value": x} for x in all_regions]
        work_options = [{"label": x, "value": x} for x in all_work_types]

        filtered_rows = _apply_egrz_filters(rows, region_values, work_type_values, search_text)
        page_size = len(filtered_rows) if page_size_value == "all" else int(page_size_value or "30")
        page_size = max(page_size, 1) if filtered_rows else 10

        primary_columns = ["Субъект РФ", "Город", "РНС", "Дата в реестре", "Вид работ", "Объект", "Застройщик", "Ключи"]
        if "all_fields" in set(_normalize_multi_str(show_all_fields)):
            extra_columns = sorted([c for c in filtered_rows[0].keys() if c not in primary_columns]) if filtered_rows else []
            column_order = primary_columns + extra_columns
        else:
            column_order = primary_columns

        search_raw = (search_text or "").strip()
        style_data_conditional = []
        if search_raw:
            for col in ["Объект", "Застройщик", "РНС", "Ключи", "Город"]:
                style_data_conditional.append(
                    {
                        "if": {"filter_query": f"{{{col}}} contains \"{search_raw}\"", "column_id": col},
                        "backgroundColor": "#fff3cd",
                    }
                )

        status = f"Показано записей: {len(filtered_rows)} из {len(rows)}"
        table = dash_table.DataTable(
            data=filtered_rows,
            columns=[{"name": c, "id": c} for c in column_order],
            page_size=page_size,
            sort_action="native",
            filter_action="native",
            page_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12, "whiteSpace": "normal"},
            style_header={"fontWeight": "600"},
            style_data_conditional=style_data_conditional,
        )

        city_counter: dict[tuple[str, str], int] = {}
        for row in filtered_rows:
            city = (row.get("Город") or "").strip() or "Не определен"
            region = (row.get("Субъект РФ") or "").strip()
            key = (city, region)
            city_counter[key] = city_counter.get(key, 0) + 1
        city_rows = [
            {"Город": city, "Субъект РФ": region, "Количество РНС": count}
            for (city, region), count in city_counter.items()
        ]
        city_rows.sort(key=lambda x: x["Количество РНС"], reverse=True)
        city_status = f"Городов в выборке: {len(city_rows)}"
        city_table = dash_table.DataTable(
            data=city_rows,
            columns=[{"name": c, "id": c} for c in ["Город", "Субъект РФ", "Количество РНС"]],
            page_size=20,
            sort_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12},
            style_header={"fontWeight": "600"},
        )
        return region_options, work_options, status, table, city_status, city_table

    @app.callback(
        Output("egrz_download", "data"),
        Input("egrz_download_button", "n_clicks"),
        State("egrz_filter_region", "value"),
        State("egrz_filter_work_type", "value"),
        State("egrz_filter_text", "value"),
        prevent_initial_call=True,
    )
    def _download_egrz_filtered_csv(
        n_clicks: int,
        region_values: list[str] | None,
        work_type_values: list[str] | None,
        search_text: str | None,
    ):
        if not n_clicks:
            raise PreventUpdate

        project_root = Path(__file__).resolve().parent
        filtered_path = project_root / "output" / "filtered_latest.csv"
        rows = _load_egrz_filtered_rows(filtered_path)
        filtered_rows = _apply_egrz_filters(rows, region_values, work_type_values, search_text)

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["Субъект РФ", "Город", "РНС", "Дата в реестре", "Вид работ", "Объект", "Застройщик", "Ключи"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(filtered_rows)
        csv_content = output.getvalue()

        return dcc.send_string(csv_content, "egrz_filtered_selection.csv")

    @app.callback(
        Output("egrz_run_status", "children"),
        Input("egrz_run_button", "n_clicks"),
        prevent_initial_call=True,
    )
    def _run_egrz_parser_once(n_clicks: int):
        if not n_clicks:
            raise PreventUpdate

        project_root = Path(__file__).resolve().parent
        script_path = project_root / "scripts" / "egrz_monitor.py"
        if not script_path.exists():
            return dbc.Alert("Скрипт scripts/egrz_monitor.py не найден.", color="danger", className="py-2 mb-0")

        log_path = project_root / "output" / "egrz_manual_run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        python_bin = sys.executable or "python3"
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        command = [python_bin, str(script_path), "--once"]

        try:
            with log_path.open("a", encoding="utf-8") as marker_file:
                marker_file.write(f"\n\n=== Manual run started at {started_at} ===\n")
                marker_file.write(f"Command: {' '.join(command)}\n")
            with log_path.open("ab") as log_file:
                subprocess.Popen(
                    command,
                    cwd=str(project_root),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except Exception as exc:
            return dbc.Alert(
                f"Не удалось запустить парсер: {type(exc).__name__}: {exc}",
                color="danger",
                className="py-2 mb-0",
            )

        return dbc.Alert(
            f"Парсер запущен в фоне ({started_at}). Лог: {log_path}",
            color="success",
            className="py-2 mb-0",
        )

    @app.callback(
        Output("lg_project", "options"),
        Input("tabs", "value"),
    )
    def _lot_growth_project_options(current_tab: str):
        if current_tab != "tab_lot_growth":
            raise PreventUpdate
        projects = (
            df.filter(pl.col("source") == "crimea")
            .filter(pl.col("object").is_not_null() & (pl.col("object") != ""))
            .select("object")
            .unique()
            .to_series()
            .to_list()
        )
        return [{"label": p, "value": p} for p in sorted(projects)]

    @app.callback(
        Output("lg_kpi_count", "children"),
        Output("lg_kpi_current_price", "children"),
        Output("lg_kpi_growth_abs", "children"),
        Output("lg_kpi_growth_pct", "children"),
        Output("lg_kpi_roi_pct", "children"),
        Output("lg_kpi_roi_annual_pct", "children"),
        Output("lg_price_trend", "figure"),
        Output("lg_table_status", "children"),
        Output("lg_table_container", "children"),
        Input("lg_project", "value"),
        Input("lg_purchase_date", "date"),
        Input("lg_purchase_price", "value"),
        Input("lg_purchase_area", "value"),
        Input("lg_purchase_floor", "value"),
        Input("lg_sell_cost_pct", "value"),
        Input("lg_area_tolerance_pct", "value"),
        Input("lg_floor_tolerance", "value"),
        Input("lg_page_size", "value"),
    )
    def _lot_growth_analysis(
        project: str | None,
        purchase_date: str | None,
        purchase_price: object,
        purchase_area: object,
        purchase_floor: object,
        sell_cost_pct: object,
        area_tol_pct: int | None,
        floor_tol: int | None,
        page_size: int | None,
    ):
        empty_fig = go.Figure()
        empty_fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320)
        if not project:
            return "0", "—", "—", "—", "—", "—", empty_fig, "Выберите проект и заполните параметры покупки.", html.Div()

        price_value = _to_float_loose(purchase_price)
        area_value = _to_float_loose(purchase_area)
        floor_value = _to_float_loose(purchase_floor)
        sell_cost_value = _to_float_loose(sell_cost_pct)

        dff = df.filter(pl.col("source") == "crimea").filter(pl.col("object") == project)
        dff = dff.filter(pl.col("sold_date").is_not_null())
        if area_value is not None and area_value > 0:
            tol = float(area_tol_pct or 10) / 100.0
            low = float(area_value) * (1 - tol)
            high = float(area_value) * (1 + tol)
            dff = dff.filter(pl.col("area_sqm").is_not_null() & (pl.col("area_sqm") >= low) & (pl.col("area_sqm") <= high))
        if floor_value is not None and floor_value >= 0:
            ft = int(floor_tol or 2)
            dff = dff.filter(
                pl.col("floor_num").is_not_null()
                & (pl.col("floor_num") >= float(floor_value) - ft)
                & (pl.col("floor_num") <= float(floor_value) + ft)
            )
        if purchase_date:
            dff = dff.filter(pl.col("sold_date") >= pl.lit(purchase_date).str.strptime(pl.Date, format="%Y-%m-%d", strict=False))

        dff = dff.filter(pl.col("est_budget").is_not_null() & (pl.col("est_budget") > 0))
        count = dff.height
        if count == 0:
            return "0", "—", "—", "—", "—", "—", empty_fig, "По заданным параметрам аналогов не найдено.", html.Div()

        # Market estimate for ROI: adaptive recent window, not full-period average.
        assessment_date = dff.select(pl.col("sold_date").max()).item()
        if assessment_date is None:
            return "0", "—", "—", "—", "—", "—", empty_fig, "Нет актуальной даты оценки по выбранным аналогам.", html.Div()

        assessment_dt = assessment_date

        def _slice_by_days(end_date, days_back: int, include_last_month: bool = False) -> pl.DataFrame:
            if include_last_month:
                start_date = end_date - timedelta(days=days_back)
                return dff.filter((pl.col("sold_date") >= start_date) & (pl.col("sold_date") <= end_date))
            safe_end = end_date - timedelta(days=30)
            start_date = safe_end - timedelta(days=days_back)
            return dff.filter((pl.col("sold_date") >= start_date) & (pl.col("sold_date") <= safe_end))

        # Stability check over last 6 months (including last month):
        # if price_sqm essentially flat, use last 2 months (but not 1 month only).
        stable_window = _slice_by_days(assessment_dt, 180, include_last_month=True)
        stable_monthly = (
            stable_window.group_by("sold_month")
            .agg(pl.mean("price_sqm").alias("avg_sqm"))
            .sort("sold_month")
        )
        market_stable = False
        if stable_monthly.height >= 4:
            sqm_vals = stable_monthly["avg_sqm"].to_list()
            avg_sqm = sum(sqm_vals) / len(sqm_vals) if sqm_vals else 0.0
            if avg_sqm > 0:
                spread = (max(sqm_vals) - min(sqm_vals)) / avg_sqm
                market_stable = spread <= 0.02

        if market_stable:
            valuation_df = _slice_by_days(assessment_dt, 60, include_last_month=True)
            valuation_rule = "Стабильный рынок: последние 2 месяца"
        else:
            win_3m = _slice_by_days(assessment_dt, 90, include_last_month=False)
            if win_3m.height >= 30:
                valuation_df = win_3m
                valuation_rule = "Высокая активность: 3 месяца (без последнего)"
            elif win_3m.height < 10:
                win_6m = _slice_by_days(assessment_dt, 180, include_last_month=False)
                if win_6m.height < 10:
                    valuation_df = _slice_by_days(assessment_dt, 270, include_last_month=False)
                    valuation_rule = "Низкая активность: 9 месяцев (без последнего)"
                else:
                    valuation_df = win_6m
                    valuation_rule = "Низкая активность: 6 месяцев (без последнего)"
            else:
                valuation_df = _slice_by_days(assessment_dt, 180, include_last_month=False)
                valuation_rule = "Базовое окно: 6 месяцев (без последнего)"

        # Fallback if filtered window became too small.
        if valuation_df.height == 0:
            valuation_df = dff
            valuation_rule = "Fallback: вся доступная выборка аналогов"

        current_avg = float(valuation_df.select(pl.col("est_budget").mean()).item() or 0)
        roi_text = "—"
        roi_annual_text = "—"
        if price_value is not None and price_value > 0:
            growth_abs = current_avg - float(price_value)
            growth_pct = (growth_abs / float(price_value)) * 100.0
            growth_abs_text = f"{growth_abs:,.0f}".replace(",", " ")
            growth_pct_text = f"{growth_pct:,.2f}%"

            sell_cost = max(float(sell_cost_value or 0.0), 0.0) / 100.0
            net_sale = current_avg * (1.0 - sell_cost)
            roi = ((net_sale - float(price_value)) / float(price_value)) * 100.0
            roi_text = f"{roi:,.2f}%"

            if purchase_date:
                try:
                    purchase_dt = datetime.strptime(purchase_date, "%Y-%m-%d").date()
                    today = datetime.now().date()
                    days = max((today - purchase_dt).days, 1)
                    years = days / 365.25
                    annualized = ((max(net_sale, 1.0) / float(price_value)) ** (1 / years) - 1) * 100.0
                    roi_annual_text = f"{annualized:,.2f}%"
                except ValueError:
                    roi_annual_text = "—"
        else:
            growth_abs_text = "—"
            growth_pct_text = "—"

        monthly = (
            dff.group_by("sold_month")
            .agg([pl.mean("est_budget").alias("avg_budget"), pl.len().alias("deals")])
            .sort("sold_month")
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=monthly["sold_month"].to_list(),
                y=monthly["avg_budget"].to_list(),
                mode="lines+markers",
                customdata=monthly["deals"].to_list(),
                hovertemplate="Месяц=%{x}<br>Средняя цена=%{y:,.0f} ₽<br>Сделок=%{customdata}<extra></extra>",
            )
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320, yaxis_title="₽")

        view = dff.select(
            [
                pl.col("sold_date").cast(pl.Utf8).alias("Дата сделки"),
                pl.col("est_budget").round(0).alias("Цена сделки, ₽"),
                pl.col("area_sqm").round(2).alias("Площадь, м²"),
                pl.col("floor_num").round(0).alias("Этаж"),
                pl.col("price_sqm").round(0).alias("Цена за м², ₽"),
                pl.col("type_lot").alias("Тип объекта"),
                pl.col("city").alias("Город"),
            ]
        ).sort("Дата сделки", descending=True)

        tbl = dash_table.DataTable(
            data=view.to_dicts(),
            columns=[{"name": c, "id": c} for c in view.columns],
            page_size=int(page_size or 30),
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12, "whiteSpace": "normal"},
            style_header={"fontWeight": "600"},
        )

        return (
            f"{count}",
            f"{current_avg:,.0f}".replace(",", " "),
            growth_abs_text,
            growth_pct_text,
            roi_text,
            roi_annual_text,
            fig,
            f"Аналоги: {count} записей по проекту «{project}». Оценочное окно: {valuation_rule} (сделок: {valuation_df.height}).",
            tbl,
        )

    @app.callback(
        Output("pg_city", "options"),
        Output("pg_district", "options"),
        Output("pg_type_lot", "options"),
        Input("pg_deals_source", "value"),
        Input("pg_agglomeration", "value"),
        Input("pg_year", "value"),
    )
    def _project_growth_dimension_options(deals_source: str, agglomeration: str, year: int | None):
        cities, districts, types = project_growth_dimension_options(
            df,
            deals_source=deals_source,
            agglomeration=agglomeration,
            year=year,
        )
        return (
            [{"label": c, "value": c} for c in cities],
            [{"label": d, "value": d} for d in districts],
            [{"label": t, "value": t} for t in types],
        )

    @app.callback(
        Output("pg_fig_growth_budget_pct", "figure"),
        Output("pg_fig_growth_sqm_pct", "figure"),
        Output("pg_fig_room_growth", "figure"),
        Output("pg_table_status", "children"),
        Output("pg_table_container", "children"),
        Input("pg_deals_source", "value"),
        Input("pg_year", "value"),
        Input("pg_agglomeration", "value"),
        Input("pg_city", "value"),
        Input("pg_district", "value"),
        Input("pg_type_lot", "value"),
        Input("pg_mortgage_mode", "value"),
        Input("pg_data_quality_flags", "value"),
    )
    def _update_project_growth_tab(
        deals_source: str,
        year: int | None,
        agglomeration: str,
        cities_sel: list[str],
        districts_sel: list[str],
        type_lot_sel: list[str],
        mortgage_mode: str,
        data_quality_flags: list[str],
    ):
        dff = filter_project_growth_deals(
            df,
            deals_source=deals_source,
            year=year,
            agglomeration=agglomeration,
            cities_sel=cities_sel,
            districts_sel=districts_sel,
            type_lot_sel=type_lot_sel,
            mortgage_mode=mortgage_mode,
            data_quality_flags=data_quality_flags,
        )

        empty = go.Figure()
        empty.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320)
        if dff.is_empty():
            return empty, empty, empty, "Нет данных после фильтров.", dbc.Alert("Нет данных для расчета роста.", color="light")

        project_growth = compute_project_growth(dff)
        if project_growth.is_empty():
            return empty, empty, empty, "Нет данных после фильтров.", dbc.Alert("Нет данных для расчета роста.", color="light")

        top_budget = project_growth.sort("growth_budget_pct", descending=True).head(20)
        fig_budget = go.Figure()
        fig_budget.add_trace(
            go.Bar(
                x=top_budget["growth_budget_pct"].round(2).to_list(),
                y=top_budget["object"].to_list(),
                orientation="h",
                hovertemplate="Проект=%{y}<br>Рост бюджета=%{x:.2f}%<extra></extra>",
            )
        )
        fig_budget.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=380, yaxis=dict(autorange="reversed"))

        top_sqm = project_growth.sort("growth_sqm_pct", descending=True).head(20)
        fig_sqm = go.Figure()
        fig_sqm.add_trace(
            go.Bar(
                x=top_sqm["growth_sqm_pct"].round(2).to_list(),
                y=top_sqm["object"].to_list(),
                orientation="h",
                hovertemplate="Проект=%{y}<br>Рост цены м²=%{x:.2f}%<extra></extra>",
            )
        )
        fig_sqm.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=380, yaxis=dict(autorange="reversed"))

        room_growth = compute_room_growth(dff)
        fig_room = go.Figure()
        fig_room.add_trace(
            go.Bar(
                x=room_growth["room_group"].to_list(),
                y=room_growth["growth_pct"].round(2).to_list(),
                hovertemplate="Тип=%{x}<br>Рост цены м²=%{y:.2f}%<extra></extra>",
            )
        )
        fig_room.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320, yaxis_title="Рост цены м², %")

        view = (
            project_growth.select(
                [
                    pl.col("object").alias("Проект"),
                    pl.col("deals_total").alias("Сделок"),
                    pl.col("first_month").alias("Первый месяц"),
                    pl.col("last_month").alias("Последний месяц"),
                    pl.col("first_budget").round(0).alias("Бюджет старт, ₽"),
                    pl.col("last_budget").round(0).alias("Бюджет текущий, ₽"),
                    pl.col("growth_budget_abs").round(0).alias("Рост бюджета, ₽"),
                    pl.col("growth_budget_pct").round(2).alias("Рост бюджета, %"),
                    pl.col("first_sqm").round(0).alias("Цена м² старт, ₽"),
                    pl.col("last_sqm").round(0).alias("Цена м² текущая, ₽"),
                    pl.col("growth_sqm_abs").round(0).alias("Рост цены м², ₽"),
                    pl.col("growth_sqm_pct").round(2).alias("Рост цены м², %"),
                ]
            )
            .sort("Рост бюджета, %", descending=True)
            .head(300)
        )
        tbl = dash_table.DataTable(
            data=view.to_dicts(),
            columns=[{"name": c, "id": c} for c in view.columns],
            page_size=15,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"padding": "6px", "fontFamily": "system-ui", "fontSize": 12, "whiteSpace": "normal"},
            style_header={"fontWeight": "600"},
        )

        status = f"Проектов в расчете: {project_growth.height}. Показаны лидеры роста."
        return fig_budget, fig_sqm, fig_room, status, tbl

    return app


if __name__ == "__main__":
    app = create_app()
    app.run_server(debug=True)

