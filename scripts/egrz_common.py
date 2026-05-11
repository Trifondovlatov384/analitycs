from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from egrz_text_analysis import (
    COLUMN_DEVELOPER,
    COLUMN_OBJECT,
    COLUMN_REGION,
    COLUMN_WORK_TYPE,
    KEYWORDS,
    TARGET_REGIONS,
    filter_rows,
)


COLUMN_ID = "Идентификатор"
COLUMN_NUMBER = "Номер заключения экспертизы"
COLUMN_REGISTRY_DATE = "Дата включения сведений в реестр"

REQUIRED_COLUMNS = [
    COLUMN_ID,
    COLUMN_NUMBER,
    COLUMN_REGION,
    COLUMN_OBJECT,
    COLUMN_DEVELOPER,
    COLUMN_REGISTRY_DATE,
    COLUMN_WORK_TYPE,
]

def detect_encoding(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            content.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def parse_csv_bytes(content: bytes, delimiter: str = ";") -> tuple[list[dict[str, str]], list[str]]:
    encoding = detect_encoding(content)
    text = content.decode(encoding, errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = [dict(row) for row in reader]
    headers = reader.fieldnames or []
    return rows, headers


def parse_csv_file(path: Path, delimiter: str = ";") -> tuple[list[dict[str, str]], list[str]]:
    return parse_csv_bytes(path.read_bytes(), delimiter=delimiter)


def fetch_url_bytes(url: str, timeout: int = 90, retries: int = 3, retry_delay_seconds: int = 5) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": "egrz-monitor/1.0"})
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (URLError, TimeoutError, OSError, ConnectionResetError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_delay_seconds)
    if last_error is None:
        raise RuntimeError("Failed to fetch URL for unknown reason.")
    raise RuntimeError(f"Failed to fetch URL after {retries} attempts: {last_error}") from last_error


def validate_required_columns(headers: list[str]) -> list[str]:
    header_set = set(headers)
    return [column for column in REQUIRED_COLUMNS if column not in header_set]


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None, delimiter: str = ";") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, delimiter=delimiter, extrasaction="ignore")
        if fieldnames:
            writer.writeheader()
        if rows:
            writer.writerows(rows)


def row_identity_keys(row: dict[str, str]) -> tuple[str, str]:
    row_id = (row.get(COLUMN_ID) or "").strip()
    number = (row.get(COLUMN_NUMBER) or "").strip()
    date_in_registry = (row.get(COLUMN_REGISTRY_DATE) or "").strip()
    number_and_date = f"{number}||{date_in_registry}"
    return row_id, number_and_date


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seen_ids": [], "seen_number_dates": []}
    with path.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    return {
        "seen_ids": list(data.get("seen_ids", [])),
        "seen_number_dates": list(data.get("seen_number_dates", [])),
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(state, file_obj, ensure_ascii=False, indent=2)


def split_new_rows(rows: list[dict[str, str]], state: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    seen_ids = set(state.get("seen_ids", []))
    seen_number_dates = set(state.get("seen_number_dates", []))
    new_rows: list[dict[str, str]] = []

    for row in rows:
        row_id, number_and_date = row_identity_keys(row)
        id_is_new = bool(row_id) and row_id not in seen_ids
        number_date_is_new = bool(number_and_date.strip("|")) and number_and_date not in seen_number_dates
        if id_is_new and number_date_is_new:
            new_rows.append(row)
        if row_id:
            seen_ids.add(row_id)
        if number_and_date.strip("|"):
            seen_number_dates.add(number_and_date)

    updated_state = {
        "seen_ids": sorted(seen_ids),
        "seen_number_dates": sorted(seen_number_dates),
    }
    return new_rows, updated_state


def build_mind_map(
    rows: list[dict[str, str]],
    regions: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    selected_regions = regions or TARGET_REGIONS
    selected_keywords = keywords or KEYWORDS
    tree: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "regions": selected_regions,
            "keywords": selected_keywords,
        },
        "regions": {},
    }

    for row in rows:
        region = row.get(COLUMN_REGION, "Не указан")
        number = row.get(COLUMN_NUMBER, "Без номера")
        entry = {
            "id": row.get(COLUMN_ID, ""),
            "registry_date": row.get(COLUMN_REGISTRY_DATE, ""),
            "work_type": row.get(COLUMN_WORK_TYPE, ""),
            "object": row.get(COLUMN_OBJECT, ""),
            "developer": row.get(COLUMN_DEVELOPER, ""),
            "matched_keywords": row.get("MatchedKeywords", ""),
        }
        region_obj = tree["regions"].setdefault(region, {"count": 0, "rns": {}})
        region_obj["count"] += 1
        region_obj["rns"].setdefault(number, []).append(entry)
    return tree
