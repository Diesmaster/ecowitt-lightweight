"""FastAPI dependencies enforcing this app's two separate auth mechanisms.

require_api_key: for GET endpoints (current/range/storage status),
checked against an `X-API-Key` header.

require_whitelisted_station: for POST /data/report/, checked against
the station's own PASSKEY field in the request body - stations can't
send custom headers, so this can't use the same header-based approach.

Usage - attach to any route that should require a key:

    @router.get("/data/{station_id}/{data_type}/current",
                dependencies=[Depends(require_api_key)])
    def get_current(...): ...

    @router.post("/data/report/")
    async def receive_report(
        request: Request,
        station_id: str = Depends(require_whitelisted_station),
    ): ...

Or, if the handler wants to know which key was used (e.g. for logging):

    def get_current(..., key: ApiKeyRecord = Depends(require_api_key)):
        ...
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Header, HTTPException, Request

from app.security.key_store import ApiKeyRecord, KeyStore
from app.security.station_auth import resolve_station_id

KEYS_FILE = Path("keys.json")
key_store = KeyStore(KEYS_FILE)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyRecord:
    """Reads the raw key from the `X-API-Key` header and checks, in order:

    1. the header is present at all, and matches SOME stored key
       (401 if not - "who are you")
    2. that key's `endpoints` list allows this route (403 if not -
       "you're someone, but not allowed here")
    3. if the route has a `station_id` path parameter (i.e. it's scoped
       to a specific weather station), that key's `weatherstations`
       list allows it (403 if not)

    Endpoint matching uses the route's *path template* (e.g.
    "/data/{station_id}/{data_type}/current"), not the resolved URL -
    so a key scoped to that template covers all data_types and all
    stations it's otherwise allowed to see, rather than needing one
    entry per concrete URL. This is exactly what
    scripts/add_api_key.py's `--endpoints` values should contain.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    record = key_store.find_matching(x_api_key)
    if record is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    route = request.scope.get("route")
    route_template = getattr(route, "path", request.url.path)
    if not record.allows_endpoint(route_template):
        raise HTTPException(
            status_code=403,
            detail=f"API key '{record.title}' is not authorized for endpoint '{route_template}'",
        )

    station_id = request.path_params.get("station_id")
    if station_id is not None and not record.allows_station(station_id):
        raise HTTPException(
            status_code=403,
            detail=f"API key '{record.title}' is not authorized for station_id '{station_id}'",
        )

    return record


async def require_whitelisted_station(request: Request) -> str:
    """Dependency for POST /data/report/: pulls PASSKEY out of the
    incoming form body, checks it against the station whitelist
    (app.security.station_auth), and returns the resolved station_id
    (the salted hash) for the route handler to use.

    `request.form()` is called here, and again in the route handler
    itself to build the full EcowittPayload - Starlette caches the
    parsed form internally after the first call, so this doesn't
    double-read or double-parse the request body.

    Raises 422 if PASSKEY is missing entirely (malformed request - not
    really an auth failure), or 403 if it's present but not whitelisted
    (see resolve_station_id).
    """
    form = await request.form()
    raw_passkey = form.get("PASSKEY")
    if not raw_passkey:
        raise HTTPException(status_code=422, detail="Missing PASSKEY")
    return resolve_station_id(str(raw_passkey))
