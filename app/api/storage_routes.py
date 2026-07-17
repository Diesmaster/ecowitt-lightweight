"""Storage status endpoint.

    GET /storage/status

Always returns 200 - this is a monitoring-style check, not a functional
failure of the request. The severity lives in the `status` field of the
body ("ok" / "warning" / "error"), so whatever's polling this (a
dashboard, a cron job, an alert rule) reads that field rather than
relying on the HTTP status code as the signal.

Like every other GET endpoint, this reads the cache rather than
re-walking the data directory - see app.services.storage_status_cache.

Requires a valid `X-API-Key` header - see app.security.dependencies.
This route has no `passkey` path parameter, so only endpoint scoping
applies, not per-station scoping.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security.dependencies import require_api_key
from app.storage.registry import storage_status_cache

router = APIRouter()


@router.get("/storage/status", dependencies=[Depends(require_api_key)])
def get_storage_status():
    return storage_status_cache.current.to_dict()
