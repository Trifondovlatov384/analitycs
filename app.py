from __future__ import annotations

import os
import re
from pathlib import Path

from dash import Dash, Input, Output, State, dcc, html
import dash_bootstrap_components as dbc
from dash import dash_table
import plotly.graph_objects as go
import polars as pl

from aggregations import (
    apply_filters,
    city_deal_counts,
    complex_monthly_counts,
    kpis,
    monthly_avg_price,
    monthly_deal_counts,
    yearly_top_complexes,
)
from data_loader import list_sorted, load_crimea_deals, load_deals, resolve_data_path
from heatmap_loader import load_matrix_csv
from ui import layout


# ---- Helpers (declared before callbacks) ----

def pl_from_dicts(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def pl_col(name: str) -> pl.Expr:
    return pl.col(name)


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
        Output("h_year", "options"),
        Output("h_year", "value"),
        Input("meta_years", "data"),
        Input("meta_default_year", "data"),
    )
    def _init_years_heatmap(meta_years: list[int], meta_default_year: int | None):
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
        if year is not None:
            dff = dff.filter(pl_col("year") == year)
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

        # Default: build from Analitic.csv deals
        dff = df
        if deals_source and deals_source != "all":
            dff = dff.filter(pl_col("source") == deals_source)
        if year is not None:
            dff = dff.filter(pl_col("year") == int(year))
        if agglomeration and agglomeration != "all":
            dff = dff.filter(pl_col("agglomeration") == agglomeration)
        if districts_sel:
            dff = dff.filter(pl_col("loc_district").is_in(districts_sel))

        years = None  # уже отфильтровали по году выше
        cities = cities_sel or None
        type_lots = type_lot_sel or None

        filtered = apply_filters(
            dff,
            years=years,
            months=None,
            agglomeration=None,
            cities=cities,
            mortgage_mode=mortgage_mode,
            sources=None,
            developers=None,
            type_lots=type_lots,
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

        dff = df
        if deals_source and deals_source != "all":
            dff = dff.filter(pl_col("source") == deals_source)
        if year is not None:
            dff = dff.filter(pl_col("year") == int(year))
        if agglomeration and agglomeration != "all":
            dff = dff.filter(pl_col("agglomeration") == agglomeration)
        if cities_sel:
            dff = dff.filter(pl_col("city").is_in(cities_sel))
        if districts_sel:
            dff = dff.filter(pl_col("loc_district").is_in(districts_sel))
        if type_lot_sel:
            dff = dff.filter(pl_col("type_lot").is_in(type_lot_sel))
        if mortgage_mode == "mortgage":
            dff = dff.filter(pl_col("is_mortgage") == True)  # noqa: E712
        elif mortgage_mode == "non_mortgage":
            dff = dff.filter(pl_col("is_mortgage") == False)  # noqa: E712

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

    return app


if __name__ == "__main__":
    app = create_app()
    app.run_server(debug=True)

