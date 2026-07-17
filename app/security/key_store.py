"""Loads and caches keys.json (written by scripts/add_api_key.py).

Re-reads the file only when its mtime changes, so a key added while the
server is running is picked up on the next request without a restart -
but the file isn't re-read on every single request either.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.security.api_key import verify_key


@dataclass(frozen=True)
class ApiKeyRecord:
    title: str
    endpoints: list[str]
    weatherstations: list[str]
    salted_key_hash: str

    def allows_endpoint(self, route_template: str) -> bool:
        return "*" in self.endpoints or route_template in self.endpoints

    def allows_station(self, passkey: str) -> bool:
        return "*" in self.weatherstations or passkey in self.weatherstations


class KeyStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._records: list[ApiKeyRecord] = []
        self._loaded_mtime: float | None = None

    def _reload_if_changed(self) -> None:
        if not self.path.exists():
            self._records = []
            self._loaded_mtime = None
            return
        mtime = self.path.stat().st_mtime
        if mtime == self._loaded_mtime:
            return
        with self.path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        self._records = [ApiKeyRecord(**entry) for entry in raw]
        self._loaded_mtime = mtime

    def find_matching(self, raw_key: str) -> ApiKeyRecord | None:
        """Find the record whose hash this raw key satisfies, if any.

        This is a linear scan over every stored key, verifying each
        PBKDF2 hash in turn - there's no way to look a salted hash up
        by raw key directly, that's the point of salting it. Fine at
        the scale of "a handful to a few dozen issued keys"; if you
        end up issuing hundreds, the standard fix is prefixing raw keys
        with a public, unhashed key ID (e.g. "whk_<id>_<secret>") to
        make lookup O(1) - not needed here yet.
        """
        self._reload_if_changed()
        for record in self._records:
            if verify_key(raw_key, record.salted_key_hash):
                return record
        return None
