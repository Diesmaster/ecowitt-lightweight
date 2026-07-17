"""Checks the on-disk size of the data directory against configured
warning/error thresholds (in GB), set via environment variables
(STORAGE_WARNING_GB, STORAGE_ERROR_GB - see app/config.py).

This measures the *apparent* size (sum of file byte sizes), not
allocated-block size (what `du` reports) - apparent size is what's
portable across platforms without relying on POSIX-only stat fields,
and it's a reasonable proxy for parquet files specifically, since they
don't have large block-alignment padding the way some formats do.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.config import settings

BYTES_PER_GB = 1024**3  # GiB (binary), matches how most disk tools report "GB"


class StorageStatus(str, Enum):
    ok = "ok"
    warning = "warning"
    error = "error"


@dataclass(frozen=True)
class StorageCheckResult:
    status: StorageStatus
    size_bytes: int
    size_gb: float
    warning_threshold_gb: float
    error_threshold_gb: float
    message: str

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "size_bytes": self.size_bytes,
            "size_gb": round(self.size_gb, 4),
            "warning_threshold_gb": self.warning_threshold_gb,
            "error_threshold_gb": self.error_threshold_gb,
            "message": self.message,
        }


class StorageCheckerService:
    def __init__(
        self,
        data_dir: Path | str | None = None,
        warning_threshold_gb: float | None = None,
        error_threshold_gb: float | None = None,
    ):
        self.data_dir = Path(data_dir if data_dir is not None else settings.data_dir)
        self.warning_threshold_gb = (
            warning_threshold_gb if warning_threshold_gb is not None else settings.storage_warning_gb
        )
        self.error_threshold_gb = (
            error_threshold_gb if error_threshold_gb is not None else settings.storage_error_gb
        )

    def _directory_size_bytes(self) -> int:
        if not self.data_dir.exists():
            return 0
        return sum(f.stat().st_size for f in self.data_dir.rglob("*") if f.is_file())

    def check(self) -> StorageCheckResult:
        size_bytes = self._directory_size_bytes()
        size_gb = size_bytes / BYTES_PER_GB

        if size_gb >= self.error_threshold_gb:
            status = StorageStatus.error
            message = (
                f"'{self.data_dir}' is {size_gb:.2f} GB, at or above the "
                f"error threshold of {self.error_threshold_gb} GB."
            )
        elif size_gb >= self.warning_threshold_gb:
            status = StorageStatus.warning
            message = (
                f"'{self.data_dir}' is {size_gb:.2f} GB, at or above the "
                f"warning threshold of {self.warning_threshold_gb} GB."
            )
        else:
            status = StorageStatus.ok
            message = f"'{self.data_dir}' is {size_gb:.2f} GB, within limits."

        return StorageCheckResult(
            status=status,
            size_bytes=size_bytes,
            size_gb=size_gb,
            warning_threshold_gb=self.warning_threshold_gb,
            error_threshold_gb=self.error_threshold_gb,
            message=message,
        )
