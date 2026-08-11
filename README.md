# Deals dashboard (local)

Локальный интерактивный дашборд по сделкам из `august2026.csv` (экспорт bnMAP по Крыму; при необходимости можно подставить свой CSV).

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Открыть в браузере: `http://127.0.0.1:8050`

## Скрытые разделы

В меню видны: Дашборд, Комплексы, Сравнение, Эйлер, Теплокарта.

**ЕГРЗ** скрыт из меню, но открывается по прямой ссылке без ключа:

- `http://127.0.0.1:8050/?tab=tab_egrz`

**Рост лота** и **Рост проектов** тоже скрыты из меню и открываются только с ключом доступа.

Задайте ключ (по умолчанию `dev-admin-key`):

```bash
export ADMIN_ACCESS_KEY="ваш-секретный-ключ"
python app.py
```

Прямые ссылки (подставьте свой ключ и хост):

- `http://127.0.0.1:8050/?access=ваш-секретный-ключ&tab=tab_lot_growth`
- `http://127.0.0.1:8050/?access=ваш-секретный-ключ&tab=tab_project_growth`

Без правильного `access` эти два раздела не откроются.

## Данные

По умолчанию подгружаются все доступные CSV в папке проекта:

- `august2026.csv` / `july2026.csv` / … — bnMAP по Крыму (берётся более новый файл, сейчас **august2026** с данными до июля 2026)
- `Analitic.csv` — источник **Analitic** (Анапа, Сочи и др. направления)
- `KK2026.csv` — сделки **2026** по **Краснодарскому краю** (источник **KK2026**)
- отдельный файл Крыма — источник **Крым**, если путь не совпадает с двумя выше

Форматы: **bnMAP** (колонки «Проект», «Дата договора», …) и **Analitic** (`object`, `date_sold` YYYY-MM-DD, …) — определяется по заголовку.

```bash
DATA_PATH="/полный/путь/к/august2026.csv" python app.py
BNMAP_EXPORT_PATHS="july2026.csv,august2026.csv" python app.py  # несколько выгрузок bnMAP
ANALYTIC_PATH="/полный/путь/к/Analitic.csv" python app.py
KK2026_PATH="/полный/путь/к/KK2026.csv" python app.py
CRIMEA_DEALS_PATH="/полный/путь/к/крым.csv" python app.py
```

## Деплой на Vercel

Проект настроен для Vercel через `api/index.py` и `vercel.json`.

1. Запушьте код в GitHub.
2. В Vercel: **Add New Project** -> выберите репозиторий.
3. Framework Preset: **Other**.
4. Root Directory: `/` (по умолчанию).
5. Нажмите Deploy.
