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
                        [
                            dbc.Badge("Local", color="secondary", className="mt-2"),
                            dbc.Button(
                                "Открыть страницу ЕГРЗ",
                                id="open_egrz_tab_button",
                                color="primary",
                                size="sm",
                                className="mt-2",
                            ),
                        ],
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

    compare_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("Сравнение комплексов"),
                            html.Div(
                                "Средний бюджет и средняя цена м² для поиска платежеспособной аудитории.",
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
                                    html.Div("Фильтры (Сравнение)", className="h5 mb-3"),
                                    dbc.Label("Источник данных"),
                                    dcc.Dropdown(
                                        id="cmp_source",
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
                                        id="cmp_agglomeration",
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
                                    dcc.Dropdown(id="cmp_year", options=[], value=None, clearable=False),
                                    dbc.Label("Месяцы (опционально)", className="mt-3"),
                                    dcc.Dropdown(id="cmp_months", options=[], value=[], multi=True),
                                    dbc.Label("Город", className="mt-3"),
                                    dcc.Dropdown(id="cmp_city", options=[], value=[], multi=True),
                                    dbc.Label("Ипотека", className="mt-3"),
                                    dcc.RadioItems(
                                        id="cmp_mortgage_mode",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Ипотека", "value": "mortgage"},
                                            {"label": "Не ипотека", "value": "non_mortgage"},
                                        ],
                                        value="all",
                                        className="mt-1",
                                    ),
                                    dbc.Label("Тип недвижимости", className="mt-3"),
                                    dcc.Dropdown(id="cmp_type_lot", options=[], value=[], multi=True),
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
                                    html.Div(
                                        "Сравнение комплексов: средний бюджет и средняя цена м²",
                                        className="h6",
                                    ),
                                    html.Div(
                                        "Клик по точке добавляет/убирает комплекс из выбора. Можно закрепить несколько точек.",
                                        className="text-muted mb-2",
                                    ),
                                    dbc.Button(
                                        "Сбросить выбранные точки",
                                        id="cmp_clear_selected",
                                        color="light",
                                        size="sm",
                                        className="me-2 mb-2",
                                    ),
                                    dbc.Button(
                                        "На весь экран",
                                        id="cmp_open_fullscreen",
                                        color="secondary",
                                        size="sm",
                                        className="mb-2",
                                    ),
                                    dcc.Graph(id="cmp_fig_complex_compare", config={"displayModeBar": False}),
                                    html.Hr(className="my-3"),
                                    html.Div(id="cmp_tbl_complex_compare"),
                                    dcc.Store(id="cmp_selected_complexes", data=[]),
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
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle("Сравнение комплексов (полный экран)"),
                        close_button=True,
                    ),
                    dbc.ModalBody(
                        dcc.Graph(
                            id="cmp_fig_complex_compare_full",
                            config={"displayModeBar": True},
                            style={"height": "85vh"},
                        )
                    ),
                    dbc.ModalFooter(
                        dbc.Button("Закрыть", id="cmp_close_fullscreen", color="secondary")
                    ),
                ],
                id="cmp_fullscreen_modal",
                is_open=False,
                size="xl",
                fullscreen=True,
                scrollable=True,
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
                                    dbc.Label("Качество данных", className="mt-3"),
                                    dbc.Checklist(
                                        id="h_data_quality_flags",
                                        options=[
                                            {"label": "Исключать оптовые сделки (Крым)", "value": "exclude_wholesale"},
                                            {"label": "Только сделки с известным бюджетом", "value": "known_budget_only"},
                                        ],
                                        value=["exclude_wholesale", "known_budget_only"],
                                        switch=True,
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
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Всплески продаж у застройщиков (по сделкам)", className="h6"),
                                    html.Div(
                                        "Пик = продажи месяца / среднее за предыдущие 3 месяца (с учетом фильтров теплокарты).",
                                        className="text-muted mb-2",
                                    ),
                                    dbc.Label("Окно базы для всплеска", className="mt-2"),
                                    dcc.RadioItems(
                                        id="h_spike_window",
                                        options=[
                                            {"label": "3 месяца", "value": 3},
                                            {"label": "6 месяцев", "value": 6},
                                            {"label": "12 месяцев", "value": 12},
                                        ],
                                        value=3,
                                        inline=True,
                                        className="mb-2",
                                    ),
                                    dbc.Label("Тип базы", className="mt-1"),
                                    dcc.RadioItems(
                                        id="h_spike_baseline_type",
                                        options=[
                                            {"label": "Среднее", "value": "mean"},
                                            {"label": "Медиана", "value": "median"},
                                        ],
                                        value="mean",
                                        inline=True,
                                        className="mb-2",
                                    ),
                                    dcc.Graph(id="h_fig_dev_spikes", config={"displayModeBar": False}),
                                    html.Div(id="h_tbl_dev_spikes"),
                                    html.Hr(className="my-3"),
                                    html.Div("Всплески продаж по комплексам (ЖК)", className="h6"),
                                    dbc.Label("Исключить комплексы из графика/таблицы всплесков", className="mt-1"),
                                    dcc.Dropdown(
                                        id="h_object_exclude",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Отметьте комплексы, которые нужно скрыть",
                                    ),
                                    dcc.Graph(id="h_fig_object_spikes", config={"displayModeBar": False}),
                                    html.Div(id="h_tbl_object_spikes"),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=12,
                        className="mt-3",
                    ),
                ],
            ),
        ],
        fluid=True,
        className="pb-5",
    )

    new_heatmap_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("Теплокарта 2"),
                            html.Div(
                                "Комплексы слева, месяцы справа, цвет — количество сделок. "
                                "Фильтры без режима матрицы и без агломерации.",
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
                                    html.Div("Фильтры", className="h5 mb-3"),
                                    dbc.Label("Год"),
                                    dcc.Dropdown(id="nh_year", options=[], value=None, clearable=True),
                                    dbc.Label("Город", className="mt-3"),
                                    dcc.Dropdown(
                                        id="nh_city",
                                        options=[],
                                        value=None,
                                        clearable=True,
                                        placeholder="Если пусто — все города",
                                    ),
                                    dbc.Label("Район (мультивыбор)", className="mt-3"),
                                    dcc.Dropdown(
                                        id="nh_district",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Если пусто — все районы",
                                    ),
                                    dbc.Label("Тип объекта (квартира/апартаменты)", className="mt-3"),
                                    dcc.Dropdown(
                                        id="nh_type_lot",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Если пусто — все типы",
                                    ),
                                    dbc.Label("Расчёт по сделкам", className="mt-3"),
                                    dcc.RadioItems(
                                        id="nh_mortgage_mode",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Ипотека", "value": "mortgage"},
                                            {"label": "Не ипотека", "value": "non_mortgage"},
                                        ],
                                        value="all",
                                        className="mt-1",
                                    ),
                                    dbc.Label("Качество данных", className="mt-3"),
                                    dbc.Checklist(
                                        id="nh_data_quality_flags",
                                        options=[
                                            {"label": "Исключать оптовые сделки (Крым)", "value": "exclude_wholesale"},
                                            {"label": "Только сделки с известным бюджетом", "value": "known_budget_only"},
                                        ],
                                        value=["exclude_wholesale", "known_budget_only"],
                                        switch=True,
                                        className="mt-1",
                                    ),
                                    dbc.Label("Топ комплексов", className="mt-3"),
                                    dcc.Slider(
                                        id="nh_top_n",
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
                                    html.Div("Сделки по месяцам", className="h6"),
                                    dcc.Graph(id="nh_fig_heatmap", config={"displayModeBar": False}),
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

    euler_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("Эйлер: пересечение бюджетных аудиторий по проектам"),
                            html.Div(
                                "Выберите 2–3 ЖК. Полоса «целевой бюджет ± дельта» задаёт суммы; шаг — коридоры. "
                                "Пересечение — по общим бюджетным коридорам между выбранными проектами: "
                                "по каждому коридору берётся min(число сделок). "
                                "В файле нет id клиента — за покупателя принимается одна сделка.",
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
                                    html.Div("Фильтры (Эйлер)", className="h5 mb-3"),
                                    dbc.Label("Источник данных"),
                                    dcc.Dropdown(
                                        id="e_source",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Основной файл", "value": "main"},
                                            {"label": "Крым", "value": "crimea"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Год", className="mt-3"),
                                    dcc.Dropdown(id="e_year", options=[], value=None, clearable=False),
                                    dbc.Label("Города (опционально)", className="mt-3"),
                                    dcc.Dropdown(id="e_city", options=[], value=[], multi=True),
                                    dbc.Label("Проекты (ЖК), до 3", className="mt-3"),
                                    dcc.Dropdown(id="e_projects", options=[], value=[], multi=True),
                                    dbc.Label("Тип недвижимости (раздельно)", className="mt-3"),
                                    dcc.Dropdown(
                                        id="e_type_lot",
                                        options=[
                                            {"label": "квартира", "value": "квартира"},
                                            {"label": "апартаменты", "value": "апартаменты"},
                                        ],
                                        value="квартира",
                                        clearable=False,
                                    ),
                                    dbc.Label("Целевой бюджет, ₽", className="mt-3"),
                                    dcc.Slider(
                                        id="e_target_budget",
                                        min=1_000_000,
                                        max=30_000_000,
                                        step=250_000,
                                        value=8_000_000,
                                        marks={
                                            1_000_000: "1M",
                                            5_000_000: "5M",
                                            10_000_000: "10M",
                                            20_000_000: "20M",
                                            30_000_000: "30M",
                                        },
                                    ),
                                    dbc.Label("Дельта, ₽", className="mt-3"),
                                    dcc.Slider(
                                        id="e_delta_budget",
                                        min=500_000,
                                        max=10_000_000,
                                        step=250_000,
                                        value=3_000_000,
                                        marks={
                                            500_000: "0.5M",
                                            2_000_000: "2M",
                                            3_000_000: "3M",
                                            5_000_000: "5M",
                                            10_000_000: "10M",
                                        },
                                    ),
                                    dbc.Label("Шаг рыночного коридора, ₽", className="mt-3"),
                                    dcc.Slider(
                                        id="e_corridor_step",
                                        min=250_000,
                                        max=5_000_000,
                                        step=250_000,
                                        value=1_000_000,
                                        marks={
                                            250_000: "0.25M",
                                            1_000_000: "1M",
                                            2_000_000: "2M",
                                            3_000_000: "3M",
                                            5_000_000: "5M",
                                        },
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
                                    html.Div("Круги Эйлера (бюджетные сегменты)", className="h6"),
                                    dcc.Graph(id="e_fig_euler", config={"displayModeBar": False}),
                                    html.Hr(className="my-3"),
                                    html.Div(id="e_tbl_overlaps"),
                                    html.Hr(className="my-3"),
                                    html.Div("Взвешенное пересечение (по структуре долей в коридорах)", className="h6"),
                                    dcc.Graph(id="e_fig_weighted_overlap", config={"displayModeBar": False}),
                                    html.Div(id="e_tbl_weighted"),
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

    egrz_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("ЕГРЗ Парсер"),
                            html.Div(
                                "Ручной запуск парсера ЕГРЗ, просмотр статуса и лога последнего запуска.",
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
                                    html.Div("Управление запуском", className="h5 mb-3"),
                                    dbc.Button(
                                        "Запустить EGRZ парсер (1 цикл)",
                                        id="egrz_run_button",
                                        color="primary",
                                        className="me-2",
                                    ),
                                    dbc.Button(
                                        "Обновить лог",
                                        id="egrz_refresh_log",
                                        color="secondary",
                                        outline=True,
                                    ),
                                    dbc.Button(
                                        "Скачать текущую выборку CSV",
                                        id="egrz_download_button",
                                        color="success",
                                        className="ms-2",
                                    ),
                                    dcc.Download(id="egrz_download"),
                                    html.Div(id="egrz_run_status", className="mt-3"),
                                    html.Hr(),
                                    html.Div(id="egrz_last_outputs"),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=5,
                        className="mt-3",
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Лог последнего запуска", className="h6"),
                                    html.Pre(
                                        id="egrz_log_preview",
                                        style={
                                            "maxHeight": "520px",
                                            "overflowY": "auto",
                                            "whiteSpace": "pre-wrap",
                                            "fontSize": "12px",
                                            "marginBottom": "0",
                                        },
                                    ),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=7,
                        className="mt-3",
                    ),
                ],
                className="g-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div("Фильтры ЕГРЗ", className="h5 mb-3"),
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                [
                                                    dbc.Label("Субъект РФ"),
                                                    dcc.Dropdown(
                                                        id="egrz_filter_region",
                                                        options=[],
                                                        value=[],
                                                        multi=True,
                                                        placeholder="Все регионы",
                                                    ),
                                                ],
                                                md=4,
                                            ),
                                            dbc.Col(
                                                [
                                                    dbc.Label("Вид работ"),
                                                    dcc.Dropdown(
                                                        id="egrz_filter_work_type",
                                                        options=[],
                                                        value=[],
                                                        multi=True,
                                                        placeholder="Все виды работ",
                                                    ),
                                                ],
                                                md=4,
                                            ),
                                            dbc.Col(
                                                [
                                                    dbc.Label("Поиск по объекту/застройщику/РНС"),
                                                    dbc.Input(
                                                        id="egrz_filter_text",
                                                        type="text",
                                                        placeholder="Например: архыз, гостиница, 23-2-...",
                                                    ),
                                                ],
                                                md=4,
                                            ),
                                        ],
                                        className="g-3",
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                [
                                                    dbc.Label("Строк на страницу"),
                                                    dcc.Dropdown(
                                                        id="egrz_page_size",
                                                        options=[
                                                            {"label": "10", "value": "10"},
                                                            {"label": "30", "value": "30"},
                                                            {"label": "100", "value": "100"},
                                                            {"label": "Все", "value": "all"},
                                                        ],
                                                        value="30",
                                                        clearable=False,
                                                    ),
                                                ],
                                                md=3,
                                            ),
                                            dbc.Col(
                                                [
                                                    dbc.Label("Колонки"),
                                                    dbc.Checklist(
                                                        id="egrz_show_all_fields",
                                                        options=[{"label": "Показать все поля", "value": "all_fields"}],
                                                        value=[],
                                                        switch=True,
                                                        className="mt-1",
                                                    ),
                                                ],
                                                md=5,
                                            ),
                                        ],
                                        className="g-3 mt-1",
                                    ),
                                    html.Hr(),
                                    html.Div(id="egrz_table_status", className="mb-2"),
                                    html.Div(id="egrz_table_container"),
                                    html.Hr(),
                                    html.Div("Сводка по городам", className="h6 mb-2"),
                                    html.Div(id="egrz_city_table_status", className="mb-2"),
                                    html.Div(id="egrz_city_table_container"),
                                ]
                            ),
                            className="shadow-sm",
                        ),
                        md=12,
                        className="mt-3",
                    ),
                ]
            ),
        ],
        fluid=True,
        className="pb-5",
    )

    lot_growth_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("Оценка роста лота"),
                            html.Div(
                                "Вы выбираете проект и вводите параметры своей покупки, система подбирает аналоги и считает текущую рыночную динамику.",
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
                                    html.Div("Параметры вашей покупки", className="h5 mb-3"),
                                    dbc.Label("Проект"),
                                    dcc.Dropdown(id="lg_project", options=[], value=None, placeholder="Выберите проект..."),
                                    dbc.Label("Дата приобретения", className="mt-3"),
                                    dcc.DatePickerSingle(
                                        id="lg_purchase_date",
                                        display_format="YYYY-MM-DD",
                                        placeholder="Выберите дату",
                                    ),
                                    dbc.Label("Стоимость приобретения, ₽", className="mt-3"),
                                    dbc.Input(
                                        id="lg_purchase_price",
                                        type="text",
                                        placeholder="Например: 14461610 или 14 461 610",
                                    ),
                                    dbc.Label("Площадь, м²", className="mt-3"),
                                    dbc.Input(id="lg_purchase_area", type="text", placeholder="Например: 29.9 или 29,9"),
                                    dbc.Label("Этаж", className="mt-3"),
                                    dbc.Input(id="lg_purchase_floor", type="text", placeholder="Например: 5"),
                                    dbc.Label("Расходы на продажу, %", className="mt-3"),
                                    dbc.Input(id="lg_sell_cost_pct", type="text", value="3"),
                                    dbc.Label("Допуск по площади, %", className="mt-3"),
                                    dcc.Slider(
                                        id="lg_area_tolerance_pct",
                                        min=3,
                                        max=30,
                                        step=1,
                                        value=10,
                                        marks={3: "3%", 10: "10%", 20: "20%", 30: "30%"},
                                    ),
                                    dbc.Label("Допуск по этажу, +/-", className="mt-3"),
                                    dcc.Slider(
                                        id="lg_floor_tolerance",
                                        min=0,
                                        max=10,
                                        step=1,
                                        value=2,
                                        marks={0: "0", 2: "2", 5: "5", 10: "10"},
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
                                    dbc.Col(kpi_card("Найдено аналогов", "lg_kpi_count"), md=3),
                                    dbc.Col(kpi_card("Текущая средняя цена, ₽", "lg_kpi_current_price"), md=3),
                                    dbc.Col(kpi_card("Рост, ₽", "lg_kpi_growth_abs"), md=3),
                                    dbc.Col(kpi_card("Рост, %", "lg_kpi_growth_pct"), md=3),
                                    dbc.Col(kpi_card("ROI при продаже сейчас, %", "lg_kpi_roi_pct"), md=3),
                                    dbc.Col(kpi_card("ROI annualized, %/год", "lg_kpi_roi_annual_pct"), md=3),
                                ],
                                className="mt-3 g-3",
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Динамика средних цен аналогов по месяцам", className="h6"),
                                                    dcc.Graph(id="lg_price_trend", config={"displayModeBar": False}),
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
                                                    html.Div("Сделки по аналогичным лотам", className="h6"),
                                                    html.Div(id="lg_table_status", className="mb-2"),
                                                    dcc.Dropdown(
                                                        id="lg_page_size",
                                                        options=[
                                                            {"label": "10", "value": 10},
                                                            {"label": "30", "value": 30},
                                                            {"label": "100", "value": 100},
                                                        ],
                                                        value=30,
                                                        clearable=False,
                                                        style={"maxWidth": "180px"},
                                                    ),
                                                    html.Div(id="lg_table_container", className="mt-2"),
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

    project_growth_tab = dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H3("Рост стоимости по проектам"),
                            html.Div(
                                "Рост стоимости лотов и цены за м² по проектам и типам (студии/1к/2к/3к и т.д.) с фильтрами как в теплокарте.",
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
                                    html.Div("Фильтры (рост проектов)", className="h5 mb-3"),
                                    dbc.Label("Источник сделок"),
                                    dcc.Dropdown(
                                        id="pg_deals_source",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Основной файл", "value": "main"},
                                            {"label": "Крым", "value": "crimea"},
                                        ],
                                        value="crimea",
                                        clearable=False,
                                    ),
                                    dbc.Label("Агломерация", className="mt-3"),
                                    dcc.Dropdown(
                                        id="pg_agglomeration",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Анапа", "value": "Анапа"},
                                            {"label": "Сочи", "value": "Сочи"},
                                            {"label": "Крым", "value": "Крым"},
                                            {"label": "Без групп", "value": "без групп"},
                                        ],
                                        value="all",
                                        clearable=False,
                                    ),
                                    dbc.Label("Год", className="mt-3"),
                                    dcc.Dropdown(id="pg_year", options=[], value=None, clearable=False),
                                    dbc.Label("Город", className="mt-3"),
                                    dcc.Dropdown(id="pg_city", options=[], value=[], multi=True),
                                    dbc.Label("Район", className="mt-3"),
                                    dcc.Dropdown(id="pg_district", options=[], value=[], multi=True),
                                    dbc.Label("Тип объекта", className="mt-3"),
                                    dcc.Dropdown(id="pg_type_lot", options=[], value=[], multi=True),
                                    dbc.Label("Ипотека", className="mt-3"),
                                    dcc.RadioItems(
                                        id="pg_mortgage_mode",
                                        options=[
                                            {"label": "Все", "value": "all"},
                                            {"label": "Ипотека", "value": "mortgage"},
                                            {"label": "Не ипотека", "value": "non_mortgage"},
                                        ],
                                        value="all",
                                        className="mt-1",
                                    ),
                                    dbc.Label("Качество данных", className="mt-3"),
                                    dbc.Checklist(
                                        id="pg_data_quality_flags",
                                        options=[
                                            {"label": "Исключать оптовые сделки (Крым)", "value": "exclude_wholesale"},
                                            {"label": "Только сделки с известным бюджетом", "value": "known_budget_only"},
                                        ],
                                        value=["exclude_wholesale", "known_budget_only"],
                                        switch=True,
                                        className="mt-1",
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
                                                    html.Div("Топ проектов по росту бюджета, %", className="h6"),
                                                    dcc.Graph(id="pg_fig_growth_budget_pct", config={"displayModeBar": False}),
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
                                                    html.Div("Топ проектов по росту цены м², %", className="h6"),
                                                    dcc.Graph(id="pg_fig_growth_sqm_pct", config={"displayModeBar": False}),
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
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Рост по комнатности (студии/1к/2к/3к/4+)", className="h6"),
                                                    dcc.Graph(id="pg_fig_room_growth", config={"displayModeBar": False}),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=12,
                                        className="mt-3",
                                    ),
                                ]
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Card(
                                            dbc.CardBody(
                                                [
                                                    html.Div("Таблица наибольшего роста стоимости", className="h6"),
                                                    html.Div(id="pg_table_status", className="mb-2"),
                                                    html.Div(id="pg_table_container"),
                                                ]
                                            ),
                                            className="shadow-sm",
                                        ),
                                        md=12,
                                        className="mt-3",
                                    ),
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

    return dbc.Container(
        [
            dcc.Tabs(
                id="tabs",
                value="tab_deals",
                children=[
                    dcc.Tab(label="Дашборд", value="tab_deals", children=deals_tab),
                    dcc.Tab(label="Комплексы", value="tab_complexes", children=complexes_tab),
                    dcc.Tab(label="Сравнение", value="tab_compare", children=compare_tab),
                    dcc.Tab(label="Эйлер", value="tab_euler", children=euler_tab),
                    dcc.Tab(label="Теплокарта", value="tab_heatmap", children=heatmap_tab),
                    dcc.Tab(label="Теплокарта 2", value="tab_heatmap2", children=new_heatmap_tab),
                    dcc.Tab(label="ЕГРЗ Парсер", value="tab_egrz", children=egrz_tab),
                    dcc.Tab(label="Рост лота", value="tab_lot_growth", children=lot_growth_tab),
                    dcc.Tab(label="Рост проектов", value="tab_project_growth", children=project_growth_tab),
                ],
            )
        ],
        fluid=True,
        className="pb-3",
    )

