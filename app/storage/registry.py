"""Shared store/service instances.

Both the ingestion routes and the query routes need the same
ParquetTimeSeriesStore/AggregationService instances - not separate ones
constructed independently, since each store owns its own per-station
asyncio.Lock. Constructing it here once and importing it elsewhere
keeps that single-instance guarantee.
"""

from pathlib import Path

from app.services.aggregation_service import AggregationService
from app.services.storage_checker_service import StorageCheckerService
from app.services.storage_status_cache import StorageStatusCache
from app.services.ws_manager import WebSocketManager
from app.storage.parquet_store import ParquetTimeSeriesStore

DATA_DIR = Path("data")

# data/<PASSKEY>/raw_data.parquet
raw_store = ParquetTimeSeriesStore(base_dir=DATA_DIR)

# data/<PASSKEY>/agg_1m.parquet, agg_1h.parquet, agg_1d.parquet
aggregation_service = AggregationService(raw_store=raw_store, base_dir=DATA_DIR)

# Checks total size of DATA_DIR against STORAGE_WARNING_GB / STORAGE_ERROR_GB.
storage_checker_service = StorageCheckerService(data_dir=DATA_DIR)

# Computed once here (import time, i.e. app startup) and refreshed
# explicitly after every write - see app/api/routes.py. Every GET reads
# this cache rather than re-walking the data directory itself.
storage_status_cache = StorageStatusCache(storage_checker_service)

# Tracks WebSocket subscribers per (station_id, data_type) and
# broadcasts new readings/aggregates to them after every write.
ws_manager = WebSocketManager()

# The four data types the API exposes, keyed by the name used in the URL.
DATA_TYPE_STORES: dict[str, ParquetTimeSeriesStore] = {
    "raw": raw_store,
    **aggregation_service.agg_stores,  # "1m", "1h", "1d"
}
