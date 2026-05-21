# Deals dashboard (local)

Локальный интерактивный дашборд по сделкам из `may2026.csv` (экспорт bnMAP; при необходимости можно подставить свой CSV).

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Открыть в браузере: `http://127.0.0.1:8050`

## Скрытые разделы (только по прямой ссылке)

В меню видны: Дашборд, Комплексы, Сравнение, Эйлер, Теплокарта.  
Разделы **ЕГРЗ**, **Рост лота** и **Рост проектов** скрыты; открываются по URL с ключом доступа.

Задайте ключ (по умолчанию `dev-admin-key`):

```bash
export ADMIN_ACCESS_KEY="ваш-секретный-ключ"
python app.py
```

Прямые ссылки (подставьте свой ключ и хост):

- `http://127.0.0.1:8050/?access=ваш-секретный-ключ&tab=tab_egrz`
- `http://127.0.0.1:8050/?access=ваш-секретный-ключ&tab=tab_lot_growth`
- `http://127.0.0.1:8050/?access=ваш-секретный-ключ&tab=tab_project_growth`

Без правильного `access` откроется обычный дашборд.

## Данные

По умолчанию подгружаются все доступные CSV в папке проекта:

- `may2026.csv` — источник **may2026** (bnMAP, в т.ч. Крым)
- `Analitic.csv` — источник **Analitic** (Анапа, Сочи и др. направления)
- отдельный файл Крыма — источник **Крым**, если путь не совпадает с двумя выше

Форматы: **bnMAP** (колонки «Проект», «Дата договора», …) и **Analitic** (`object`, `date_sold` YYYY-MM-DD, …) — определяется по заголовку.

```bash
DATA_PATH="/полный/путь/к/may2026.csv" python app.py
ANALYTIC_PATH="/полный/путь/к/Analitic.csv" python app.py
CRIMEA_DEALS_PATH="/полный/путь/к/крым.csv" python app.py
```

## Деплой на Vercel

Проект настроен для Vercel через `api/index.py` и `vercel.json`.

1. Запушьте код в GitHub.
2. В Vercel: **Add New Project** -> выберите репозиторий.
3. Framework Preset: **Other**.
4. Root Directory: `/` (по умолчанию).
5. Нажмите Deploy.
