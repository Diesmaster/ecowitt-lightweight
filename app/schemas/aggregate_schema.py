"""Schema for aggregated (1m / 1h / 1d) station rollups.

For every numeric (Float64) field in RAW_DATA_SCHEMA, one aggregate row
reports:

    <field>_avg, <field>_min, <field>_max, <field>_std, <field>_mode

"avg" is the arithmetic mean - "average" and "mean" are the same
statistic, so there's one column for it, not two. "mode" is a distinct
statistic (the most frequently occurring value) and is NOT the same
thing as the mean; see aggregation_service.py for why it's often not
very meaningful for continuous sensor data specifically. Plus:

    timestamp      - start of the bucket (UTC)
    PASSKEY        - the station, carried through unchanged
    sample_count   - how many raw rows fed into this bucket

String/metadata columns from the raw schema (stationtype, freq, model)
don't have a meaningful avg/min/max/std and are excluded.

Built programmatically from RAW_DATA_SCHEMA so this can't silently
drift out of sync with the raw table it's derived from - add a field to
the raw schema and its four aggregate columns show up here for free.
"""

from __future__ import annotations

import polars as pl

from app.schemas.raw_data_schema import RAW_DATA_SCHEMA, TIMESTAMP_COL

AGGREGATABLE_FIELDS: list[str] = [
    name for name, dtype in RAW_DATA_SCHEMA.items() if dtype == pl.Float64
]

AGGREGATE_STATS: tuple[str, ...] = ("avg", "min", "max", "std", "mode")


def _build_schema() -> pl.Schema:
    fields: dict[str, pl.DataType] = {
        TIMESTAMP_COL: pl.Datetime(time_zone="UTC"),
        "PASSKEY": pl.Utf8,
        "sample_count": pl.UInt32,
    }
    for name in AGGREGATABLE_FIELDS:
        for stat in AGGREGATE_STATS:
            fields[f"{name}_{stat}"] = pl.Float64
    return pl.Schema(fields)


AGGREGATE_SCHEMA: pl.Schema = _build_schema()
