from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from egrz_common import (
    KEYWORDS,
    TARGET_REGIONS,
    build_mind_map,
    filter_rows,
    fetch_url_bytes,
    load_state,
    parse_csv_bytes,
    save_state,
    split_new_rows,
    validate_required_columns,
    write_csv,
    COLUMN_DEVELOPER,
    COLUMN_NUMBER,
    COLUMN_OBJECT,
    COLUMN_REGION,
    COLUMN_REGISTRY_DATE,
    COLUMN_WORK_TYPE,
)

DEFAULT_API_URL = (
    "https://open-api.egrz.ru/api/PublicRegistrationBook/openDataFile"
    "?$filter=contains(tolower(ExpertiseResultType),tolower(%27"
    "%D0%9F%D0%BE%D0%BB%D0%BE%D0%B6%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D0%BE%D0%B5%20"
    "%D0%B7%D0%B0%D0%BA%D0%BB%D1%8E%D1%87%D0%B5%D0%BD%D0%B8%D0%B5%27))"
    "&$orderby=ExpertiseDate%20desc%20&$count=true&$top=500&$skip=0"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Регулярный мониторинг CSV ЕГРЗ с фильтрацией и Telegram-уведомлениями."
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Ссылка на CSV open-api ЕГРЗ.")
    parser.add_argument("--state-file", default="data/state.json", help="Путь к state JSON.")
    parser.add_argument("--output-csv", default="output/filtered_latest.csv", help="Актуальный filtered CSV.")
    parser.add_argument(
        "--output-new-csv",
        default="output/new_matches_latest.csv",
        help="CSV только с новыми релевантными записями текущего цикла.",
    )
    parser.add_argument(
        "--output-mind-map",
        default="output/mind_map.json",
        help="Путь к mind-map JSON.",
    )
    parser.add_argument("--once", action="store_true", help="Выполнить один цикл и завершить работу.")
    parser.add_argument("--interval-minutes", type=int, default=30, help="Интервал опроса в минутах.")
    parser.add_argument("--start-hour", type=int, default=10, help="Начало окна по МСК (включительно).")
    parser.add_argument("--end-hour", type=int, default=19, help="Конец окна по МСК (исключительно).")
    parser.add_argument("--telegram-token", default=os.getenv("EGRZ_TELEGRAM_BOT_TOKEN", ""))
    parser.add_argument("--telegram-chat-id", default=os.getenv("EGRZ_TELEGRAM_CHAT_ID", ""))
    return parser.parse_args()


def now_moscow() -> datetime:
    return datetime.now(ZoneInfo("Europe/Moscow"))


def in_work_window(current: datetime, start_hour: int, end_hour: int) -> bool:
    return start_hour <= current.hour < end_hour


def next_schedule_time(current: datetime, interval_minutes: int) -> datetime:
    rounded = current.replace(second=0, microsecond=0)
    minutes_to_add = interval_minutes - (rounded.minute % interval_minutes)
    if minutes_to_add == interval_minutes:
        minutes_to_add = interval_minutes
    return rounded + timedelta(minutes=minutes_to_add)


def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = Request(url=url, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return bool(data.get("ok"))


def format_telegram_row(row: dict[str, str]) -> str:
    return (
        "Новая запись ЕГРЗ\n"
        f"Регион: {row.get(COLUMN_REGION, '')}\n"
        f"РНС: {row.get(COLUMN_NUMBER, '')}\n"
        f"Дата включения: {row.get(COLUMN_REGISTRY_DATE, '')}\n"
        f"Вид работ: {row.get(COLUMN_WORK_TYPE, '')}\n"
        f"Объект: {row.get(COLUMN_OBJECT, '')}\n"
        f"Застройщик: {row.get(COLUMN_DEVELOPER, '')}\n"
        f"Ключи: {row.get('MatchedKeywords', '')}"
    )


def run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    raw_bytes = fetch_url_bytes(args.api_url, timeout=120, retries=3, retry_delay_seconds=10)
    rows, headers = parse_csv_bytes(raw_bytes)
    missing_columns = validate_required_columns(headers)
    if missing_columns:
        raise RuntimeError(f"Missing required columns: {missing_columns}")

    filtered_rows = filter_rows(rows, regions=TARGET_REGIONS, keywords=KEYWORDS)
    write_csv(Path(args.output_csv), filtered_rows)

    mind_map = build_mind_map(filtered_rows, regions=TARGET_REGIONS, keywords=KEYWORDS)
    output_map = Path(args.output_mind_map)
    output_map.parent.mkdir(parents=True, exist_ok=True)
    output_map.write_text(json.dumps(mind_map, ensure_ascii=False, indent=2), encoding="utf-8")

    state_path = Path(args.state_file)
    state = load_state(state_path)
    new_rows, updated_state = split_new_rows(filtered_rows, state)
    save_state(state_path, updated_state)
    write_csv(Path(args.output_new_csv), new_rows)

    sent = 0
    for row in new_rows:
        if send_telegram_message(args.telegram_token, args.telegram_chat_id, format_telegram_row(row)):
            sent += 1

    return {
        "raw_total": len(rows),
        "filtered_total": len(filtered_rows),
        "new_total": len(new_rows),
        "telegram_sent": sent,
    }


def main() -> int:
    args = parse_args()

    if args.once:
        stats = run_cycle(args)
        print(
            "[once] raw={raw_total} filtered={filtered_total} new={new_total} telegram_sent={telegram_sent}".format(
                **stats
            )
        )
        return 0

    while True:
        current = now_moscow()
        if in_work_window(current, args.start_hour, args.end_hour):
            try:
                stats = run_cycle(args)
                print(
                    "[cycle] {ts} raw={raw_total} filtered={filtered_total} new={new_total} telegram_sent={telegram_sent}".format(
                        ts=current.isoformat(),
                        **stats,
                    )
                )
            except Exception as exc:
                print(f"[cycle] {current.isoformat()} ERROR: {exc}")
        else:
            print(f"[idle] {current.isoformat()} вне рабочего окна {args.start_hour}:00-{args.end_hour}:00 МСК")

        target = next_schedule_time(now_moscow(), args.interval_minutes)
        sleep_seconds = max((target - now_moscow()).total_seconds(), 1)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    sys.exit(main())
