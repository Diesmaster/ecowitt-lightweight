"""A minimal parquet-backed time-series store.

Layout on disk:

    <base_dir>/<station_id>/<filename>

Each station gets its own file. Rows are keyed by `timestamp`: writing a
row whose timestamp already exists overwrites it (upsert), so replays /
retries from a station are idempotent rather than creating duplicates.

Every row/frame is validated against `schema` before it touches disk:
unknown columns or values that don't match the declared dtype raise
immediately instead of Polars silently inferring a new column or
writing a mismatched type.

This class is deliberately schema-agnostic (pass in whatever pl.Schema
and filename you like) so the same store backs both the raw-reading
table and the 1m/1h/1d aggregate tables - see app/services/aggregation.py.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import polars as pl

from app.schemas.raw_data_schema import RAW_DATA_SCHEMA, TIMESTAMP_COL

RAW_DATA_FILENAME = "raw_data.parquet"


class ParquetTimeSeriesStore:
    def __init__(
        self,
        base_dir: Path | str,
        schema: pl.Schema = RAW_DATA_SCHEMA,
        filename: str = RAW_DATA_FILENAME,
    ):
        self.base_dir = Path(base_dir)
        self.schema = schema
        self.filename = filename
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, station_id: str) -> asyncio.Lock:
        if station_id not in self._locks:
            self._locks[station_id] = asyncio.Lock()
        return self._locks[station_id]

    def _path_for(self, station_id: str) -> Path:
        return self.base_dir / station_id / self.filename

    def _row_to_dataframe(self, row: dict) -> pl.DataFrame:
        if TIMESTAMP_COL not in row:
            raise ValueError(f"row must contain a '{TIMESTAMP_COL}' key")

        unknown = set(row) - set(self.schema.names())
        if unknown:
            raise ValueError(
                f"Unknown column(s) not in schema: {sorted(unknown)}. "
                "If this is a genuinely new field, add it to "
                "app/schemas/raw_data_schema.py (or the relevant schema module)."
            )

        # Every declared column is present (missing -> null), in schema
        # order, cast to its declared dtype. A value that can't be cast
        # (e.g. a stray string landing in a Float64 column) raises here
        # rather than silently corrupting the file.
        ordered = {col: [row.get(col)] for col in self.schema.names()}
        return self._cast_to_schema(pl.DataFrame(ordered, schema=self.schema))

    def _align_frame_to_schema(self, df: pl.DataFrame) -> pl.DataFrame:
        """Validate + reorder + cast an arbitrary multi-row frame to `schema`."""
        unknown = set(df.columns) - set(self.schema.names())
        if unknown:
            raise ValueError(
                f"Unknown column(s) not in schema: {sorted(unknown)}. "
                "If this is a genuinely new field, add it to the relevant schema module."
            )
        missing = [c for c in self.schema.names() if c not in df.columns]
        if missing:
            df = df.with_columns(
                pl.lit(None, dtype=self.schema[c]).alias(c) for c in missing
            )
        return self._cast_to_schema(df.select(self.schema.names()))

    def _cast_to_schema(self, df: pl.DataFrame) -> pl.DataFrame:
        try:
            return df.cast(dict(self.schema))
        except (pl.exceptions.SchemaError, pl.exceptions.ComputeError, TypeError) as exc:
            raise ValueError(f"data does not match schema: {exc}") from exc

    async def upsert_row(self, station_id: str, row: dict) -> None:
        """Insert or overwrite a single row, keyed by row[TIMESTAMP_COL]."""
        new_row = self._row_to_dataframe(row)

        path = self._path_for(station_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        async with self._lock_for(station_id):
            if path.exists():
                # polars' parquet reader/writer is a native Rust implementation.
                # diagonal_relaxed lets older files written before a new
                # column existed (e.g. `thi`, added later) still merge in:
                # those historical rows just get null for the new column.
                existing = pl.read_parquet(path)
                combined = pl.concat([existing, new_row], how="diagonal_relaxed")
            else:
                combined = new_row

            combined = (
                combined.sort(TIMESTAMP_COL)
                .unique(subset=[TIMESTAMP_COL], keep="last")
                .sort(TIMESTAMP_COL)
            )
            combined.write_parquet(path)

    async def write_all(self, station_id: str, df: pl.DataFrame) -> None:
        """Overwrite the entire file for a station with `df`.

        Unlike `upsert_row`, this replaces the whole table rather than
        merging - the right operation for aggregate tables, which are
        cheaply and correctly recomputed from scratch each time rather
        than patched incrementally.
        """
        aligned = self._align_frame_to_schema(df).sort(TIMESTAMP_COL)

        path = self._path_for(station_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        async with self._lock_for(station_id):
            aligned.write_parquet(path)

    def read_all(self, station_id: str) -> pl.DataFrame:
        """Read the full history for a station. Empty (correctly-typed) frame if none yet."""
        path = self._path_for(station_id)
        if not path.exists():
            return pl.DataFrame(schema=self.schema)
        return pl.read_parquet(path)

    def read_latest(self, station_id: str) -> pl.DataFrame:
        """Read just the most recent row. Empty frame if none yet.

        Every write keeps the file sorted by TIMESTAMP_COL (see
        upsert_row/write_all), so the latest row is always the last one.
        Using a lazy scan + `.tail(1)` lets Polars push the slice down
        into the parquet reader (see the `SLICE` step in
        `.explain()`), so this reads only the final row group instead
        of the whole file.
        """
        path = self._path_for(station_id)
        if not path.exists():
            return pl.DataFrame(schema=self.schema)
        return pl.scan_parquet(path).tail(1).collect()

    def read_range(self, station_id: str, start: datetime, end: datetime) -> pl.DataFrame:
        """Read all rows with TIMESTAMP_COL in [start, end] (inclusive).

        Each parquet row group carries min/max statistics for every
        column, including TIMESTAMP_COL. Filtering on a lazy scan lets
        Polars prune whole row groups that fall entirely outside
        [start, end] using those statistics (see the `SELECTION` step
        pushed into the `Parquet SCAN` in `.explain()`), instead of
        reading the full file and then filtering row by row. This is
        what gives "random access on the timestamp column" without a
        separate index - the row-group statistics ARE the index.
        """
        path = self._path_for(station_id)
        if not path.exists():
            return pl.DataFrame(schema=self.schema)
        return (
            pl.scan_parquet(path)
            .filter(pl.col(TIMESTAMP_COL).is_between(start, end, closed="both"))
            .collect()
        )
