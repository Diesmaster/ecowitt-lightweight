"""Loads and caches keys.json (written by scripts/add_api_key.py)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.security.hashed_registry import HashedRegistry


@dataclass(frozen=True)
class ApiKeyRecord:
    title: str
    endpoints: list[str]
    weatherstations: list[str]
    salted_key_hash: str

    def allows_endpoint(self, route_template: str) -> bool:
        return "*" in self.endpoints or route_template in self.endpoints

    def allows_station(self, station_id: str) -> bool:
        return "*" in self.weatherstations or station_id in self.weatherstations


class KeyStore(HashedRegistry[ApiKeyRecord]):
    def __init__(self, path: Path | str):
        super().__init__(
            path,
            record_factory=lambda d: ApiKeyRecord(**d),
            hash_getter=lambda r: r.salted_key_hash,
        )
