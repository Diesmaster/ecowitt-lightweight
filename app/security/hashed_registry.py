"""Generic JSON-file-backed registry of salted-hash records.

Both the API key store and the weather station whitelist have the same
shape: a JSON list of records, each carrying a salted hash, matched
against an incoming raw secret by linear scan (there's no way to look
up a salted hash by its plaintext directly - that's the point of
salting it). This factors that shared load/cache/match logic out once,
parameterized by the record type.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Generic, TypeVar

from app.security.api_key import verify_key

T = TypeVar("T")


class HashedRegistry(Generic[T]):
    def __init__(
        self,
        path: Path | str,
        record_factory: Callable[[dict], T],
        hash_getter: Callable[[T], str],
    ):
        self.path = Path(path)
        self._record_factory = record_factory
        self._hash_getter = hash_getter
        self._records: list[T] = []
        self._loaded_mtime: float | None = None

    def _reload_if_changed(self) -> None:
        """Re-read the file only when its mtime changes, so entries added
        while the server is running are picked up on the next lookup
        without a restart, but the file isn't re-read every call."""
        if not self.path.exists():
            self._records = []
            self._loaded_mtime = None
            return
        mtime = self.path.stat().st_mtime
        if mtime == self._loaded_mtime:
            return
        with self.path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        self._records = [self._record_factory(entry) for entry in raw]
        self._loaded_mtime = mtime

    def find_matching(self, raw_secret: str) -> T | None:
        self._reload_if_changed()
        for record in self._records:
            if verify_key(raw_secret, self._hash_getter(record)):
                return record
        return None
