"""Loads and caches stations.json (written by scripts/add_weather_station.py).

Each entry whitelists one physical weather station by the salted hash
of its Ecowitt PASSKEY - never the raw PASSKEY itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.security.hashed_registry import HashedRegistry


@dataclass(frozen=True)
class StationRecord:
    title: str
    salted_station_hash: str


class StationStore(HashedRegistry[StationRecord]):
    def __init__(self, path: Path | str):
        super().__init__(
            path,
            record_factory=lambda d: StationRecord(**d),
            hash_getter=lambda r: r.salted_station_hash,
        )
