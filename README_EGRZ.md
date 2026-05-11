# EGRZ Parser + Monitor

Скрипты для:
- разового анализа CSV ЕГРЗ;
- регулярного мониторинга `open-api.egrz.ru`;
- фильтрации по регионам и ключевым словам;
- формирования структуры `регион -> РНС -> записи`;
- Telegram-уведомлений о новых записях.

## Логика фильтра

- Регионы:
  - `Краснодарский край`
  - `Республика Крым`
  - `Алтай` (совпадения по формам "Алтайский край"/"Республика Алтай")
  - `Карачаево-Черкесская Республика` (включая упоминания `Архыз`)
- Ключи:
  - `гостиница`
  - `гостиничный`
  - `апартаментный`
  - `санаторий`
  - `апартаментов`
  - `апарт-`
  - `гостинично`

Ключи ищутся в объединенном тексте полей:
- `Наименование и адрес ... объекта ...`
- `Сведения о застройщике ...`
- `Вид работ`

## Файлы

- `scripts/egrz_text_analysis.py` - отдельный модуль анализа текста/предложений (нормализация, поиск ключей, fuzzy, фильтрация).
- `scripts/egrz_common.py` - общие функции (парсинг, фильтры, дедуп, state, mind-map).
- `scripts/egrz_analyze_csv.py` - разовый анализ локального CSV.
- `scripts/egrz_monitor.py` - регулярный мониторинг и Telegram.
- `data/state.json` - хранение уже обработанных записей.
- `output/filtered_latest.csv` - последний отфильтрованный набор.
- `output/new_matches_latest.csv` - только новые записи текущего цикла.
- `output/mind_map.json` - древо: регион -> РНС -> записи.

## 1) Разовый анализ CSV

```bash
python3 scripts/egrz_analyze_csv.py --input /полный/путь/к/вашему.csv
```

Опционально:

```bash
python3 scripts/egrz_analyze_csv.py \
  --input data/sample_egrz.csv \
  --output-csv output/filtered_latest.csv \
  --output-mind-map output/mind_map.json
```

## 2) Мониторинг (один цикл)

```bash
python3 scripts/egrz_monitor.py --once
```

## 3) Мониторинг (постоянно)

По умолчанию:
- интервал: 30 минут;
- окно: 10:00-19:00 по `Europe/Moscow`;
- дедуп: одновременно по `Идентификатор` и связке `Номер заключения + Дата включения сведений в реестр`.

```bash
python3 scripts/egrz_monitor.py
```

Настройки:

```bash
python3 scripts/egrz_monitor.py \
  --interval-minutes 30 \
  --start-hour 10 \
  --end-hour 19
```

## Telegram

Через переменные окружения:

```bash
export EGRZ_TELEGRAM_BOT_TOKEN="123456:ABCDEF..."
export EGRZ_TELEGRAM_CHAT_ID="-1001234567890"
python3 scripts/egrz_monitor.py --once
```

Или аргументами:

```bash
python3 scripts/egrz_monitor.py --once \
  --telegram-token "123456:ABCDEF..." \
  --telegram-chat-id "-1001234567890"
```

## Cron (каждые 30 минут, МСК)

Рекомендуется запускать скрипт в UTC-расписании с учетом вашей системы.
Если сервер работает в `Europe/Moscow`, используйте:

```cron
*/30 10-18 * * * cd /Users/nikitavisicki/Desktop/analitycs && /usr/bin/python3 scripts/egrz_monitor.py --once >> logs/egrz_monitor.log 2>&1
```

Почему `10-18`: диапазон часов в cron включает `18:30`, но не запускает в `19:00`, что соответствует окну `[10:00, 19:00)`.

## Быстрая самопроверка

```bash
python3 -m py_compile scripts/egrz_common.py scripts/egrz_analyze_csv.py scripts/egrz_monitor.py
python3 scripts/egrz_analyze_csv.py --input data/sample_egrz.csv
python3 scripts/egrz_monitor.py --once --api-url "file:///Users/nikitavisicki/Desktop/analitycs/data/sample_egrz.csv"
```
