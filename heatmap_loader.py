from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from typing import Optional

import polars as pl


@dataclass(frozen=True)
class MatrixCsv:
    row_label: str
    columns: list[str]
    df: pl.DataFrame  # columns: [row_label] + columns


def parse_month_label(label: str) -> tuple[int, int]:
    """Sort key for MM.YYYY or YYYY-MM month labels."""
    label = str(label).strip()
    m = re.match(r"^(\d{2})\.(\d{4})$", label)
    if m:
        return int(m.group(2)), int(m.group(1))
    m2 = re.match(r"^(\d{4})-(\d{2})$", label)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    return 0, 0


def sold_month_to_label(sold_month: str) -> str:
    """2026-05 -> 05.2026"""
    parts = str(sold_month).split("-", 1)
    if len(parts) != 2:
        return str(sold_month)
    return f"{parts[1]}.{parts[0]}"


def month_label_to_sold_month(label: str) -> str | None:
    """05.2026 or 2026-05 -> 2026-05"""
    label = str(label).strip()
    if re.match(r"^\d{4}-\d{2}$", label):
        return label
    m = re.match(r"^(\d{2})\.(\d{4})$", label)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    if len(label) >= 7 and re.match(r"^\d{4}-\d{2}", label):
        return label[:7]
    return None


def sort_month_labels(labels: list[str]) -> list[str]:
    return sorted(labels, key=parse_month_label)


def _to_number(v: str) -> int:
    if v is None:
        return 0
    s = str(v).strip()
    if s == "":
        return 0
    try:
        return int(float(s.replace(" ", "")))
    except Exception:
        return 0


def load_matrix_csv(path: str) -> Optional[MatrixCsv]:
    """
    Parses a CSV formatted like the user's example:
      - Several header rows
      - A header row starting with "Проект"
      - First column is complex/project name, other columns are month labels (e.g., 01.2024)
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header_idx = None
    for i, r in enumerate(rows):
        if len(r) > 0 and str(r[0]).strip() == "Проект":
            header_idx = i
            break

    if header_idx is None:
        return None

    header = [c.strip() for c in rows[header_idx] if c is not None]
    if len(header) < 2:
        return None

    row_label = header[0]
    columns = [c.strip() for c in header[2:] if c.strip() != ""]  # skip second column (often totals)

    data = []
    for r in rows[header_idx + 1 :]:
        if not r or (len(r) == 1 and str(r[0]).strip() == ""):
            continue
        name = str(r[0]).strip()
        if name == "":
            continue

        # r[1] is usually total; month values start at r[2]
        vals = r[2 : 2 + len(columns)]
        row = {row_label: name}
        for c, v in zip(columns, vals):
            row[c] = _to_number(v)
        data.append(row)

    df = pl.DataFrame(data) if data else pl.DataFrame({row_label: []})
    return MatrixCsv(row_label=row_label, columns=columns, df=df)

