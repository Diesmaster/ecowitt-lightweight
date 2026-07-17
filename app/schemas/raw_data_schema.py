"""Explicit parquet schema for the station time-series store.

Built programmatically from `EcowittPayload`'s own field definitions
plus the known derived-metric field names from `metric_utils`, rather
than hand-typed twice - so the schema can't silently drift out of sync
with the model/utils that actually produce the data.

`ParquetTimeSeriesStore` validates every row against this before it
touches disk: an unknown key (typo, unexpected new sensor field) or a
value that can't be cast to the declared dtype raises immediately,
instead of Polars silently inferring a new column or writing a mixed
type into what should be a Float64 column.
"""

from __future__ import annotations

import typing

import polars as pl

from app.models.ecowitt import EcowittPayload
from app.utils.metric_utils import (
    PRESSURE_FIELDS,
    RAIN_FIELDS,
    TEMPERATURE_FIELDS,
    VPD_FIELDS,
    WIND_SPEED_FIELDS,
)

TIMESTAMP_COL = "timestamp"

_PY_TO_POLARS: dict[type, pl.DataType] = {
    str: pl.Utf8,
    float: pl.Float64,
}


def _polars_dtype_for(annotation: object) -> pl.DataType:
    """Map a pydantic field annotation (e.g. `float | None`) to a polars dtype."""
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    base = args[0] if args else annotation
    return _PY_TO_POLARS.get(base, pl.Utf8)


def _build_schema() -> pl.Schema:
    fields: dict[str, pl.DataType] = {TIMESTAMP_COL: pl.Datetime(time_zone="UTC")}

    for name, field in EcowittPayload.model_fields.items():
        if name == "dateutc":
            continue  # renamed to TIMESTAMP_COL before storage
        fields[name] = _polars_dtype_for(field.annotation)

    # Every field metric_utils.to_metric() can add is always a float.
    derived_field_names = [
        *TEMPERATURE_FIELDS.values(),
        *PRESSURE_FIELDS.values(),
        *WIND_SPEED_FIELDS.values(),
        *RAIN_FIELDS.values(),
        *VPD_FIELDS.values(),
        "thi",
    ]
    for name in derived_field_names:
        fields[name] = pl.Float64

    # Ecowitt also sends "model" (e.g. "WS2350_V2.40"). It isn't an
    # explicitly declared EcowittPayload field - it arrives via that
    # model's extra="allow" - so it's declared here by hand. If your
    # station starts sending some other new field, add it here; that's
    # the point of an explicit schema: new fields are a deliberate
    # decision, not something that silently appears in the file.
    fields["model"] = pl.Utf8

    return pl.Schema(fields)


RAW_DATA_SCHEMA: pl.Schema = _build_schema()
