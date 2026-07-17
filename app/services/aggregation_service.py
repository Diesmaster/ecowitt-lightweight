"""Compute and persist 1-minute / 1-hour / 1-day aggregates per station.

Each granularity gets recomputed fresh from that station's full raw
history rather than patched incrementally. Simplest correct approach,
and cheap enough at Ecowitt's once-every-~30s cadence and the history
sizes this project deals with. If that stops being true (years of
history, many stations), the place to optimize is `compute()` - e.g.
only reprocessing raw rows newer than the last aggregate bucket.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from app.schemas.aggregate_schema import AGGREGATABLE_FIELDS, AGGREGATE_SCHEMA
from app.schemas.raw_data_schema import TIMESTAMP_COL
from app.storage.parquet_store import ParquetTimeSeriesStore

# polars duration-string suffixes: "m" = minute, "h" = hour, "d" = day
# (not to be confused with "mo" = month). See:
# https://docs.pola.rs/user-guide/expressions/temporal/
_INTERVAL_TO_DURATION: dict[str, str] = {"1m": "1m", "1h": "1h", "1d": "1d"}

_AGG_FILENAME: dict[str, str] = {
    "1m": "agg_1m.parquet",
    "1h": "agg_1h.parquet",
    "1d": "agg_1d.parquet",
}


class AggregationService:
    """Reads a station's raw history and (re)builds its 1m/1h/1d rollups."""

    def __init__(self, raw_store: ParquetTimeSeriesStore, base_dir: str | Path = "data"):
        self.raw_store = raw_store
        self.agg_stores: dict[str, ParquetTimeSeriesStore] = {
            interval: ParquetTimeSeriesStore(
                base_dir=base_dir, schema=AGGREGATE_SCHEMA, filename=filename
            )
            for interval, filename in _AGG_FILENAME.items()
        }

    @staticmethod
    def compute(raw: pl.DataFrame, interval: str) -> pl.DataFrame:
        """Bucket `raw` by `interval`; one row per bucket with avg/min/max/std/mode per field.

        Args:
            raw: a frame shaped like RAW_DATA_SCHEMA (or a subset of its
                columns - only columns present in both `raw` and
                AGGREGATABLE_FIELDS are aggregated).
            interval: one of "1m", "1h", "1d".
        """
        if interval not in _INTERVAL_TO_DURATION:
            raise ValueError(
                f"interval must be one of {list(_INTERVAL_TO_DURATION)}, got {interval!r}"
            )
        if raw.is_empty():
            return pl.DataFrame(schema=AGGREGATE_SCHEMA)

        duration = _INTERVAL_TO_DURATION[interval]
        bucket = pl.col(TIMESTAMP_COL).dt.truncate(duration).alias(TIMESTAMP_COL)

        agg_exprs = [pl.len().alias("sample_count")]
        if "PASSKEY" in raw.columns:
            agg_exprs.append(pl.col("PASSKEY").first().alias("PASSKEY"))

        for field in AGGREGATABLE_FIELDS:
            if field not in raw.columns:
                continue
            agg_exprs += [
                pl.col(field).mean().alias(f"{field}_avg"),
                pl.col(field).min().alias(f"{field}_min"),
                pl.col(field).max().alias(f"{field}_max"),
                pl.col(field).std(ddof=1).alias(f"{field}_std"),
                # mode() can return multiple tied values per group (a
                # List, not a scalar) - .sort().first() forces one
                # deterministic value. Note this is a real limitation
                # for continuous sensor data: with high-precision float
                # readings, every value in a bucket is often unique, so
                # "the mode" degenerates into an arbitrary tiebreak
                # among all-equally-common values rather than a
                # meaningful "most common reading." It's much more
                # informative for naturally discrete fields
                # (wh65batt, winddir, integer-valued humidity).
                pl.col(field).mode().sort().first().alias(f"{field}_mode"),
            ]

        return raw.group_by(bucket).agg(agg_exprs).sort(TIMESTAMP_COL)

    async def recompute_and_store(self, station_id: str, interval: str) -> pl.DataFrame:
        """Recompute one granularity's rollup from raw history and persist it."""
        raw = self.raw_store.read_all(station_id)
        aggregated = self.compute(raw, interval)
        await self.agg_stores[interval].write_all(station_id, aggregated)
        return aggregated

    async def recompute_all(self, station_id: str) -> dict[str, pl.DataFrame]:
        """Recompute and persist all three granularities for one station."""
        return {
            interval: await self.recompute_and_store(station_id, interval)
            for interval in _INTERVAL_TO_DURATION
        }
