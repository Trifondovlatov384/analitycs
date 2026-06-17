from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

PUBLIC_TABS: list[tuple[str, str]] = [
    ("tab_deals", "Дашборд"),
    ("tab_complexes", "Комплексы"),
    ("tab_compare", "Сравнение"),
    ("tab_euler", "Эйлер"),
    ("tab_heatmap", "Теплокарта"),
]

HIDDEN_TABS: list[tuple[str, str]] = [
    ("tab_egrz", "ЕГРЗ"),
    ("tab_lot_growth", "Рост лота"),
    ("tab_project_growth", "Рост проектов"),
]

# Скрыты из меню, но открываются по ?tab=... без ключа доступа
DIRECT_LINK_TAB_IDS = {"tab_egrz"}

# Скрыты из меню и требуют ?access=ADMIN_ACCESS_KEY
ADMIN_ACCESS_TAB_IDS = {tab_id for tab_id, _ in HIDDEN_TABS if tab_id not in DIRECT_LINK_TAB_IDS}

ALL_TAB_IDS = [t[0] for t in PUBLIC_TABS + HIDDEN_TABS]
PUBLIC_TAB_IDS = [t[0] for t in PUBLIC_TABS]


def kpi_card(title: str, value_id: str) -> dbc.Card:
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(title, className="kpi-label"),
                html.Div(id=value_id, className="kpi-value"),
            ]
        ),
        className="card-modern kpi-card-modern",
    )


def chart_line_style_toggle(toggle_id: str = "dash_line_style") -> html.Div:
    return html.Div(
        dbc.ButtonGroup(
            [
                dbc.Button("Резкие", id=f"{toggle_id}_linear", size="sm", outline=True, className="active"),
                dbc.Button("Плавные", id=f"{toggle_id}_spline", size="sm", outline=True),
            ],
            className="line-style-group",
        ),
        className="chart-toolbar-right",
    )


def chart_card(title: str, graph_id: str, *, line_toggle: bool = False, toggle_id: str = "dash_line_style") -> dbc.Card:
    header_children: list = [html.Div(title, className="h6")]
    if line_toggle:
        header_children.append(chart_line_style_toggle(toggle_id))
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(header_children, className="chart-toolbar"),
                dcc.Graph(id=graph_id, config={"displayModeBar": False}),
            ]
        ),
        className="card-modern mt-3",
    )


def period_filter_block(
    *,
    date_from_id: str,
    date_to_id: str,
    year_id: str,
    months_id: str,
    months_placeholder: str = "Если пусто — весь выбранный период",
) -> list:
    return [
        html.Div("Период", className="filter-section-title"),
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Label("С даты", className="small text-muted"),
                        dcc.DatePickerSingle(
                            id=date_from_id,
                            display_format="DD.MM.YYYY",
                            placeholder="Начало",
                            clearable=True,
                        ),
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        dbc.Label("По дату", className="small text-muted"),
                        dcc.DatePickerSingle(
                            id=date_to_id,
                            display_format="DD.MM.YYYY",
                            placeholder="Конец",
                            clearable=True,
                        ),
                    ],
                    md=6,
                ),
            ],
            className="g-2",
        ),
        html.Div("При выборе дат фильтр «Год» не применяется", className="form-hint"),
        dbc.Label("Год", className="mt-2"),
        dcc.Dropdown(id=year_id, options=[], value=None, clearable=True, placeholder="Все годы"),
        dbc.Label("Месяцы", className="mt-2"),
        dcc.Dropdown(
            id=months_id,
            options=[],
            value=[],
            multi=True,
            placeholder=months_placeholder,
        ),
    ]


def source_filter_block(dropdown_id: str) -> html.Div:
    return html.Div(
        [
            dbc.Label("Источник данных"),
            dcc.Dropdown(id=dropdown_id, options=[], value=None, clearable=False),
        ],
        id=f"wrap-{dropdown_id}",
        className="filter-source-wrap",
    )


def app_shell(children: list, *, matrix_available: bool) -> html.Div:
    tab_buttons = [
        html.Button(
            label,
            id={"type": "nav-tab", "id": tab_id},
            type="button",
            n_clicks=0,
            className=(
                "app-tab-btn app-tab-btn--active"
                if tab_id == "tab_deals"
                else "app-tab-btn"
            ),
        )
        for tab_id, label in PUBLIC_TABS
    ]

    return html.Div(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="tabs", data="tab_deals"),
            dcc.Store(id="chart_line_shape", data="linear"),
            html.Div(tab_buttons, className="app-tab-bar", role="tablist"),
            *children,
            dcc.Store(id="meta_matrix_available", data=matrix_available),
        ],
        className="app-root",
    )
