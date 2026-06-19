#!/usr/bin/env python3
"""Pre-build parquet cache for faster app cold starts (local + Vercel)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_loader import build_combined_deals_cache, COMBINED_CACHE_PATH  # noqa: E402


def main() -> None:
    df = build_combined_deals_cache()
    print(f"Rows: {df.height:,}")
    print(f"Cache: {COMBINED_CACHE_PATH}")


if __name__ == "__main__":
    main()
