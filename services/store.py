from __future__ import annotations

import threading
from pathlib import Path

import polars as pl

from data_loader import load_combined_deals

_lock = threading.Lock()
_df: pl.DataFrame | None = None
_matrix_available: bool | None = None


def get_deals() -> pl.DataFrame:
    global _df
    if _df is not None:
        return _df
    with _lock:
        if _df is not None:
            return _df
        df = load_combined_deals()
        if "deal_status" not in df.columns:
            df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias("deal_status"))
        if not df.is_empty() and "source" in df.columns and "ipoteka" in df.columns:
            df = df.with_columns(
                [
                    pl.when(pl.col("source") == "analitic")
                    .then(pl.col("deal_status"))
                    .otherwise(pl.col("ipoteka"))
                    .cast(pl.Utf8)
                    .alias("deal_status"),
                ]
            )
        _df = df
        return _df


def matrix_available() -> bool:
    global _matrix_available
    if _matrix_available is not None:
        return _matrix_available
    candidates = [
        str(Path.cwd() / "Аналитика сделок по Крыму - По кол-ву.csv"),
        "/Users/nikitavisicki/Downloads/Аналитика сделок по Крыму - По кол-ву.csv",
    ]
    import os

    env = os.environ.get("CRIMEA_MATRIX_PATH", "")
    if env:
        candidates.insert(0, env)
    _matrix_available = any(Path(p).exists() for p in candidates if p)
    return _matrix_available


def reset_cache() -> None:
    global _df, _matrix_available
    with _lock:
        _df = None
        _matrix_available = None
        load_combined_deals.cache_clear()
