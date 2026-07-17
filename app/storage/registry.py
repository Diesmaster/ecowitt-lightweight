"""Shared store/service instances.

Both the ingestion routes and the query routes need the same
ParquetTimeSeriesStore/AggregationService instances - not separate ones
constructed independently, since each store owns its own per-station
asyncio.Lock. Constructing it here once and importing it elsewhere
keeps that single-instance guarantee.
"""

from pathlib import Path

from app.services.aggregation_service import AggregationService
from app.storage.parquet_store import ParquetTimeSeriesStore

DATA_DIR = Path("data")

# data/<PASSKEY>/raw_data.parquet
raw_store = ParquetTimeSeriesStore(base_dir=DATA_DIR)

# data/<PASSKEY>/agg_1m.parquet, agg_1h.parquet, agg_1d.parquet
aggregation_service = AggregationService(raw_store=raw_store, base_dir=DATA_DIR)

# The four data types the API exposes, keyed by the name used in the URL.
DATA_TYPE_STORES: dict[str, ParquetTimeSeriesStore] = {
    "raw": raw_store,
    **aggregation_service.agg_stores,  # "1m", "1h", "1d"
}
