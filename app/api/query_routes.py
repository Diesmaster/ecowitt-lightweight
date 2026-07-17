"""Read endpoints: current reading and time-range queries.

    GET /data/{passkey}/{data_type}/current
    GET /data/{passkey}/{data_type}/range?start=...&end=...

`data_type` is one of "raw", "1m", "1h", "1d" - the four tables written
by the ingestion route (see app.storage.registry.DATA_TYPE_STORES).
Both endpoints go through ParquetTimeSeriesStore.read_latest() /
read_range(), which use Polars' lazy scan + pushdown to prune parquet
row groups by their timestamp statistics rather than reading the whole
file - see the docstrings there for why that's "smart" and not just
read-everything-then-filter.

Every response also carries a `storage_status` field - the current
disk-usage cache, appended for free rather than recomputed per request;
see app.services.storage_status_cache.

Both endpoints require a valid `X-API-Key` header, scoped to this
route and to the requested `passkey` - see app.security.dependencies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security.dependencies import require_api_key
from app.storage.registry import DATA_TYPE_STORES, storage_status_cache

router = APIRouter()


class DataType(str, Enum):
    raw = "raw"
    one_minute = "1m"
    one_hour = "1h"
    one_day = "1d"


def _ensure_utc(value: datetime) -> datetime:
    """Treat a timezone-naive datetime as UTC (matches how timestamps are stored)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@router.get("/data/{passkey}/{data_type}/current", dependencies=[Depends(require_api_key)])
def get_current(passkey: str, data_type: DataType):
    store = DATA_TYPE_STORES[data_type.value]
    row = store.read_latest(passkey)
    if row.is_empty():
        raise HTTPException(
            status_code=404,
            detail=f"no '{data_type.value}' data found for station {passkey!r}",
        )
    return {
        "data": row.to_dicts()[0],
        "storage_status": storage_status_cache.current.to_dict(),
    }


@router.get("/data/{passkey}/{data_type}/range", dependencies=[Depends(require_api_key)])
def get_range(
    passkey: str,
    data_type: DataType,
    start: datetime = Query(
        ..., description="range start, inclusive (ISO 8601; UTC assumed if no offset given)"
    ),
    end: datetime = Query(
        ..., description="range end, inclusive (ISO 8601; UTC assumed if no offset given)"
    ),
):
    start, end = _ensure_utc(start), _ensure_utc(end)
    if start > end:
        raise HTTPException(status_code=400, detail="'start' must be <= 'end'")

    store = DATA_TYPE_STORES[data_type.value]
    df = store.read_range(passkey, start, end)
    return {
        "data": df.to_dicts(),
        "storage_status": storage_status_cache.current.to_dict(),
    }
