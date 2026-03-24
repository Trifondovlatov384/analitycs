# Deals dashboard (local)

Локальный интерактивный дашборд по сделкам из `Analitic.csv`.

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Открыть в браузере: `http://127.0.0.1:8050`

## Данные

По умолчанию приложение ищет файл `Analitic.csv` в текущей папке (рядом с `app.py`).
Можно указать путь через переменную окружения:

```bash
DATA_PATH="/полный/путь/к/Analitic.csv" python app.py
```
