from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def kpi_card(title: str, value_id: str) -> dbc.Card:
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(title, className="text-muted small"),
                html.Div(id=value_id, className="h4 mb-0"),
            ]
        ),
        className="shadow-sm",
    )


def layout() -> dbc.Container:
    deals_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H2("Сделки недвижимости"),
                            html.Div(
                                "Фильтры слева, графики по месяцам и рейтинги по комплексам справа.",
                                className="text-muted",
                            ),
                        ],
                        md=9,
                    ),
                    dbc.Col(
                        dbc.Badge("Local", color="secondary", className="mt-2"),
                        md=3,
                        className="text-end",
                    ),
                ],
                className="mt-4 align-items-center",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Alert(
                            [
                                html.Div(
                                    "Подсказка: чтобы посмотреть агрегаты “Анапа” или “Сочи”, выберите их в фильтре “Агломерация”.",
                                ),
                            ],
                            color="light",
                            className="mt-3 mb-0",
                        ),
                        md=12,
                    )
                ]
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Фильтры", className="h5 mb-3"),
                                    dbc.Label("Источник данных"),
                                    dcc.Dropdown(
                                        id="source",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Основной файл", "value": "main"},
                                            {"label": "Крым", "value": "crimea"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Агломерация"),
                                    dcc.Dropdown(
                                        id="agglomeration",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Анапа", "value": "Анапа"},
                                            {"label": "Сочи", "value": "Сочи"},
                                            {"label": "Без групп", "value": "без групп"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Город", className="mt-3"),
                                    dcc.Dropdown(
                                        id="city",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Выберите город(а)…",
                                    ),
                                    dbc.Label("Год", className="mt-3"),
                                    dcc.Dropdown(
                                        id="year",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        placeholder="Выберите год…",
                                    ),
                                    dbc.Label("Месяцы (опционально)", className="mt-3"),
                                    dcc.Dropdown(
                                        id="months",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Если пусто — весь год",
                                    ),
                                    dbc.Label("Ипотека", className="mt-3"),
                                    dcc.RadioItems(
                                        id="mortgage_mode",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Ипотека", "value": "mortgage"},
                                            {"label": "Не ипотека", "value": "non_mortgage"},
                                        ],
                                        value="all",
                                        className="mt-1",
                                    ),
                                    dbc.Label("Застройщик", className="mt-3"),
                                    dcc.Dropdown(
                                        id="developer",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Выберите застройщика(ов)…",
                                    ),
                                    dbc.Label("Тип недвижимости", className="mt-3"),
                                    dcc.Dropdown(
                                        id="type_lot",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Выберите тип(ы)…",
                                    ),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=4,
                        className="mt-3",
                    ),
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(kpi_card("Сделок", "kpi_total_deals"), md=4),
                                    dbc.Col(kpi_card("Объём, ₽", "kpi_sum_budget"), md=4),
                                    dbc.Col(kpi_card("Средняя цена лота, ₽", "kpi_avg_budget"), md=4),
                                ],
                                className="mt-3 g-3",
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div(
                                                        "Сделки по месяцам (всего / ипотека / не ипотека)",
                                                        className="h6",
                                                    ),
                                                    dcc.Graph(id="fig_monthly_counts", config={"displayModeBar": False}),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=12,
                                        className="mt-3",
                                    )
                                ]
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Средняя стоимость лота по месяцам", className="h6"),
                                                    dcc.Graph(id="fig_monthly_avg", config={"displayModeBar": False}),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=12,
                                        className="mt-3",
                                    )
                                ]
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Топ комплексов за год (все сделки)", className="h6"),
                                                    dcc.Graph(id="fig_top_complexes_total", config={"displayModeBar": False}),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=6,
                                        className="mt-3",
                                    ),
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Топ комплексов за год (ипотека)", className="h6"),
                                                    dcc.Graph(
                                                        id="fig_top_complexes_mortgage",
                                                        config={"displayModeBar": False},
                                                    ),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=6,
                                        className="mt-3",
                                    ),
                                ],
                                className="g-3",
                            ),
                        ],
                        md=8,
                    ),
                ],
                className="g-3",
            ),
        ],
        fluid=True,
        className="pb-5",
    )

    complexes_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("Комплексы"),
                            html.Div(
                                "Сравнение городов по сделкам и помесячные продажи выбранного комплекса.",
                                className="text-muted",
                            ),
                        ],
                        md=12,
                    )
                ],
                className="mt-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Фильтры (Комплексы)", className="h5 mb-3"),
                                    dbc.Label("Источник данных"),
                                    dcc.Dropdown(
                                        id="c_source",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Основной файл", "value": "main"},
                                            {"label": "Крым", "value": "crimea"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Агломерация"),
                                    dcc.Dropdown(
                                        id="c_agglomeration",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Анапа", "value": "Анапа"},
                                            {"label": "Сочи", "value": "Сочи"},
                                            {"label": "Без групп", "value": "без групп"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Год", className="mt-3"),
                                    dcc.Dropdown(id="c_year", options=[], value=None, clearable=False),
                                    dbc.Label("Месяцы (опционально)", className="mt-3"),
                                    dcc.Dropdown(id="c_months", options=[], value=[], multi=True),
                                    dbc.Label("Город", className="mt-3"),
                                    dcc.Dropdown(id="c_city", options=[], value=[], multi=True),
                                    dbc.Label("Ипотека", className="mt-3"),
                                    dcc.RadioItems(
                                        id="c_mortgage_mode",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Ипотека", "value": "mortgage"},
                                            {"label": "Не ипотека", "value": "non_mortgage"},
                                        ],
                                        value="all",
                                        className="mt-1",
                                    ),
                                    dbc.Label("Тип недвижимости", className="mt-3"),
                                    dcc.Dropdown(
                                        id="c_type_lot",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Квартира/апартаменты/…",
                                    ),
                                    dbc.Label("Комплекс", className="mt-3"),
                                    dcc.Dropdown(
                                        id="c_object",
                                        options=[],
                                        value=None,
                                        clearable=True,
                                        placeholder="Выберите комплекс…",
                                    ),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=4,
                        className="mt-3",
                    ),
                    dbc.Col(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Сделки по городам", className="h6"),
                                                    dcc.Graph(id="c_fig_city_counts", config={"displayModeBar": False}),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=12,
                                        className="mt-3",
                                    )
                                ]
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Продажи комплекса по месяцам", className="h6"),
                                                    dcc.Graph(id="c_fig_complex_monthly", config={"displayModeBar": False}),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=12,
                                        className="mt-3",
                                    )
                                ]
                            ),
                        ],
                        md=8,
                    ),
                ],
                className="g-3",
            ),
        ],
        fluid=True,
        className="pb-5",
    )

    heatmap_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("Теплокарта"),
                            html.Div(
                                "Комплексы слева, месяцы справа, цвет отражает количество сделок.",
                                className="text-muted",
                            ),
                        ],
                        md=12,
                    )
                ],
                className="mt-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Фильтры (Теплокарта)", className="h5 mb-3"),
                                    dbc.Label("Источник"),
                                    dcc.Dropdown(
                                        id="h_source",
                                        options=[
                                            {"label": "Основные сделки (Analitic.csv)", "value": "deals"},
                                            {"label": "Крым (матрица, как в примере)", "value": "matrix_crimea"},
                                        ],
                                        value="deals",
                                        clearable=False,
                                    ),
                                    dbc.Label("Источник сделок (для режима 'Основные сделки')", className="mt-3"),
                                    dcc.Dropdown(
                                        id="h_deals_source",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Основной файл", "value": "main"},
                                            {"label": "Крым", "value": "crimea"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Агломерация", className="mt-3"),
                                    dcc.Dropdown(
                                        id="h_agglomeration",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Анапа", "value": "Анапа"},
                                            {"label": "Сочи", "value": "Сочи"},
                                            {"label": "Без групп", "value": "без групп"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Год", className="mt-3"),
                                    dcc.Dropdown(id="h_year", options=[], value=None, clearable=False),
                                    dbc.Label("Город (для Analitic.csv)", className="mt-3"),
                                    dcc.Dropdown(
                                        id="h_city",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Если пусто — все города (в рамках агломерации)",
                                    ),
                                    dbc.Label("Район (мультивыбор)", className="mt-3"),
                                    dcc.Dropdown(
                                        id="h_district",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Если пусто — все районы",
                                    ),
                                    dbc.Label("Тип объекта (квартира/апартаменты)", className="mt-3"),
                                    dcc.Dropdown(
                                        id="h_type_lot",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Если пусто — все типы",
                                    ),
                                    dbc.Label("Ипотека", className="mt-3"),
                                    dcc.RadioItems(
                                        id="h_mortgage_mode",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Ипотека", "value": "mortgage"},
                                            {"label": "Не ипотека", "value": "non_mortgage"},
                                        ],
                                        value="all",
                                        className="mt-1",
                                    ),
                                    dbc.Label("Топ комплексов", className="mt-3"),
                                    dcc.Slider(
                                        id="h_top_n",
                                        min=10,
                                        max=100,
                                        step=5,
                                        value=40,
                                        marks={10: "10", 25: "25", 40: "40", 60: "60", 100: "100"},
                                    ),
                                    dbc.FormText(
                                        "Цветовая шкала обрезает экстремумы (квантили), чтобы середина распределения читалась лучше.",
                                        className="mt-2",
                                    ),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=4,
                        className="mt-3",
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Теплокарта: сделки по месяцам", className="h6"),
                                    dcc.Graph(id="h_fig_heatmap", config={"displayModeBar": False}),
                                    html.Hr(className="my-3"),
                                    html.Div(id="h_click_details_title", className="h6"),
                                    html.Div(id="h_click_details_table"),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=8,
                        className="mt-3",
                    ),
                ],
                className="g-3",
            ),
        ],
        fluid=True,
        className="pb-5",
    )

    return dbc.Container(
        [
            dcc.Tabs(
                id="tabs",
                value="tab_deals",
                children=[
                    dcc.Tab(label="Дашборд", value="tab_deals", children=deals_tab),
                    dcc.Tab(label="Комплексы", value="tab_complexes", children=complexes_tab),
                    dcc.Tab(label="Теплокарта", value="tab_heatmap", children=heatmap_tab),
                ],
            )
        ],
        fluid=True,
        className="pb-3",
    )

