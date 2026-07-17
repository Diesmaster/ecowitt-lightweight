"""FastAPI dependency that enforces API key auth + scoping.

Usage - attach to any route that should require a key:

    @router.get("/data/{passkey}/{data_type}/current",
                dependencies=[Depends(require_api_key)])
    def get_current(...): ...

Or, if the handler wants to know which key was used (e.g. for logging):

    def get_current(..., key: ApiKeyRecord = Depends(require_api_key)):
        ...

Reads the raw key from the `X-API-Key` header and checks, in order:

  1. the header is present at all, and matches SOME stored key
     (401 if not - "who are you")
  2. that key's `endpoints` list allows this route (403 if not -
     "you're someone, but not allowed here")
  3. if the route has a `passkey` path parameter (i.e. it's scoped to a
     specific weather station), that key's `weatherstations` list
     allows it (403 if not)

Endpoint matching uses the route's *path template* (e.g.
"/data/{passkey}/{data_type}/current"), not the resolved URL - so a key
scoped to that template covers all data_types and all stations it's
otherwise allowed to see, rather than needing one entry per concrete
URL. This is exactly what scripts/add_api_key.py's `--endpoints` values
should contain.

NOTE: POST /data/report/ deliberately has no `require_api_key`
dependency - that's the endpoint real Ecowitt stations POST to, and
station firmware can't send a custom header. Its only "auth" is the
station's own PASSKEY field, which is Ecowitt's protocol, not this
one. Don't add this dependency there.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Header, HTTPException, Request

from app.security.key_store import ApiKeyRecord, KeyStore

KEYS_FILE = Path("keys.json")
key_store = KeyStore(KEYS_FILE)


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyRecord:
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

    passkey = request.path_params.get("passkey")
    if passkey is not None and not record.allows_station(passkey):
        raise HTTPException(
            status_code=403,
            detail=f"API key '{record.title}' is not authorized for weather station '{passkey}'",
        )

    return record
