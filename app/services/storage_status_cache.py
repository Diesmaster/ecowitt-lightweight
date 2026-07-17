"""Caches the most recent StorageCheckResult.

Walking the data directory on every single GET (or worse, on every GET
across every endpoint) is wasted work - the size only actually changes
on writes. This cache is refreshed explicitly:

  - once at import time (which happens before the app starts serving,
    i.e. "on startup" - see app/storage/registry.py)
  - once after every successful write (see app/api/routes.py)

Every read (GET endpoints) just returns whatever's currently cached -
no directory walk on the read path at all.
"""

from __future__ import annotations

from app.services.storage_checker_service import StorageCheckerService, StorageCheckResult


class StorageStatusCache:
    def __init__(self, checker: StorageCheckerService):
        self._checker = checker
        self.current: StorageCheckResult = checker.check()  # computed once, at construction/startup

    def refresh(self) -> StorageCheckResult:
        self.current = self._checker.check()
        return self.current
