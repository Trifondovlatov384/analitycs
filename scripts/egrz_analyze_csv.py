from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from egrz_common import (
    KEYWORDS,
    TARGET_REGIONS,
    build_mind_map,
    filter_rows,
    parse_csv_file,
    validate_required_columns,
    write_csv,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Одноразовый анализ CSV ЕГРЗ с фильтрацией по регионам и ключевым словам."
    )
    parser.add_argument("--input", required=True, help="Путь до входного CSV файла ЕГРЗ.")
    parser.add_argument(
        "--output-csv",
        default="output/filtered_latest.csv",
        help="Путь для отфильтрованной CSV-выгрузки.",
    )
    parser.add_argument(
        "--output-mind-map",
        default="output/mind_map.json",
        help="Путь для mind-map JSON (регион -> РНС -> записи).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        return 1

    rows, headers = parse_csv_file(input_path)
    missing_columns = validate_required_columns(headers)
    if missing_columns:
        print("ERROR: missing required columns:")
        for column in missing_columns:
            print(f"  - {column}")
        return 2

    filtered_rows = filter_rows(rows, regions=TARGET_REGIONS, keywords=KEYWORDS)
    output_csv = Path(args.output_csv)
    output_map = Path(args.output_mind_map)

    if filtered_rows:
        fieldnames = list(filtered_rows[0].keys())
    else:
        fieldnames = headers + ["MatchedKeywords"]
    write_csv(output_csv, filtered_rows, fieldnames=fieldnames)

    mind_map = build_mind_map(filtered_rows, regions=TARGET_REGIONS, keywords=KEYWORDS)
    output_map.parent.mkdir(parents=True, exist_ok=True)
    output_map.write_text(json.dumps(mind_map, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Total rows: {len(rows)}")
    print(f"Matched rows: {len(filtered_rows)}")
    print(f"Filtered CSV: {output_csv}")
    print(f"Mind map JSON: {output_map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
