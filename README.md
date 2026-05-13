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

## Данные

По умолчанию приложение читает `may2026.csv` в текущей папке (рядом с `app.py`). Поддерживаются два формата: **bnMAP** (колонки «Проект», «Дата договора», …) и старый **Analitic** (`object`, `date_sold` в формате YYYY-MM-DD, …) — формат определяется по заголовку файла.

Дополнительный файл Крыма (`CRIMEA_DEALS_PATH`) подмешивается только если его путь **не совпадает** с основным — иначе сделки не дублируются.

```bash
DATA_PATH="/полный/путь/к/сделкам.csv" python app.py
CRIMEA_DEALS_PATH="/полный/путь/к/крым.csv" python app.py
```

## Деплой на Vercel

Проект настроен для Vercel через `api/index.py` и `vercel.json`.

1. Запушьте код в GitHub.
2. В Vercel: **Add New Project** -> выберите репозиторий.
3. Framework Preset: **Other**.
4. Root Directory: `/` (по умолчанию).
5. Нажмите Deploy.
