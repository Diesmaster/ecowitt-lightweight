"""WebSocket endpoints: real-time push, and range-download-as-CSV.

    ws://<host>/ws/{station_id}/{data_type}?api_key=<key>
    ws://<host>/ws/download/{station_id}/{data_type}?api_key=<key>&start=...&end=...

`station_id` and `data_type` mean the same thing as the REST
current/range endpoints (see app.api.query_routes) - data_type is one
of raw/1m/1h/1d. Auth uses the same keys.json records as the REST API,
but since browser WebSocket clients can't set custom headers on the
handshake, the key goes in an `api_key` query parameter instead of the
X-API-Key header - see app.security.dependencies.require_api_key_ws.

## /ws/{station_id}/{data_type}  (subscribe)

Purely server-push: nothing is sent on connect, and the server never
expects the client to send anything either. The first message arrives
whenever the next matching ingestion happens (see app.api.routes,
which calls ws_manager.broadcast() after every write). Message shape
is just the row itself - no `storage_status` wrapper like the REST
endpoints have, kept minimal since these can arrive frequently.

## /ws/download/{station_id}/{data_type}  (CSV download)

Request/response, not push: connect with `start`/`end` in the query
string (same as the REST `/range` endpoint), get back the matching
parquet range converted to CSV, then the connection closes. No
persistent subscription, one download per connection.

Protocol: auth happens before accept() (403 handshake rejection on
failure, same as /ws/{station_id}/{data_type} - see
require_api_key_ws). Once accepted, a bad/missing/malformed `start` or
`end` sends one JSON error message (`{"error": "..."}`) and closes with
code 1003; this can't be signaled as a pre-accept HTTP status the way
auth failures are, since WebSocketException's `code` doesn't actually
reach the client as a distinct HTTP status - verified empirically, not
assumed (every pre-accept rejection surfaces as HTTP 403 regardless of
the code passed). On success, the CSV text is sent as one or more
plain-text frames (chunked for large downloads, not the fixed shape of
a single-row broadcast message), then the socket closes normally
(code 1000). A client just concatenates every received frame's payload
in order until the connection closes.

GOTCHA (applies to /data/{station_id}/{data_type}/range too, not just
here): `start`/`end` values MUST be URL-encoded. An ISO datetime like
"2026-01-01T00:00:00+00:00" contains a literal "+", which - if not
percent-encoded to "%2B" - gets decoded by standard query-string
parsing as a space, silently corrupting the timestamp before it's even
parsed as a datetime. Verified this is a pre-existing gotcha on the
REST /range endpoint too, not something specific to this WS route: a
naively-built query string breaks both the same way. Browsers'
`URLSearchParams`/`encodeURIComponent` handle this correctly
automatically; hand-built query strings (an f-string, string
concatenation) do not, and are the actual footgun.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.security.dependencies import require_api_key_ws
from app.storage.registry import DATA_TYPE_STORES, ws_manager

router = APIRouter()

CSV_CHUNK_SIZE = 64 * 1024  # characters per WS text frame while streaming a CSV download


class DataType(str, Enum):
    raw = "raw"
    one_minute = "1m"
    one_hour = "1h"
    one_day = "1d"


def _ensure_utc(value: datetime) -> datetime:
    """Treat a timezone-naive datetime as UTC (matches how timestamps are stored)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime string, tolerant of a trailing "Z" UTC
    designator regardless of Python version.

    datetime.fromisoformat() only accepts a trailing "Z" natively as of
    Python 3.11 - on 3.10 and earlier it raises ValueError for a string
    like "2026-01-01T00:00:00.000Z", even though that's valid ISO 8601.
    JavaScript's Date.prototype.toISOString() (used by the admin
    frontend) always produces exactly that "Z"-suffixed format, so this
    normalizes "Z" -> "+00:00" before parsing instead of depending on
    which Python version happens to be running this process. Confirmed
    by actually reproducing the failure on 3.10 and verifying this fix
    resolves it, not just reasoned about.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


@router.websocket("/ws/{station_id}/{data_type}")
async def subscribe(
    websocket: WebSocket,
    station_id: str,
    data_type: DataType,
    _auth=Depends(require_api_key_ws),
):
    await ws_manager.connect(station_id, data_type.value, websocket)
    try:
        while True:
            # The client isn't expected to send anything, but we need to
            # keep awaiting *something* to notice a disconnect -
            # WebSocketDisconnect is raised here, not on send().
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(station_id, data_type.value, websocket)


@router.websocket("/ws/download/{station_id}/{data_type}")
async def download_csv(
    websocket: WebSocket,
    station_id: str,
    data_type: DataType,
    _auth=Depends(require_api_key_ws),
):
    await websocket.accept()

    start_raw = websocket.query_params.get("start")
    end_raw = websocket.query_params.get("end")
    if not start_raw or not end_raw:
        await websocket.send_json({"error": "missing 'start' and/or 'end' query parameters"})
        await websocket.close(code=1003, reason="missing start/end")
        return

    try:
        start = _ensure_utc(_parse_iso_datetime(start_raw))
        end = _ensure_utc(_parse_iso_datetime(end_raw))
    except ValueError:
        await websocket.send_json({"error": "'start'/'end' must be ISO 8601 datetimes"})
        await websocket.close(code=1003, reason="invalid start/end")
        return

    if start > end:
        await websocket.send_json({"error": "'start' must be <= 'end'"})
        await websocket.close(code=1003, reason="start > end")
        return

    store = DATA_TYPE_STORES[data_type.value]
    df = store.read_range(station_id, start, end)
    csv_text = df.write_csv()

    for i in range(0, len(csv_text), CSV_CHUNK_SIZE):
        await websocket.send_text(csv_text[i : i + CSV_CHUNK_SIZE])

    await websocket.close(code=1000, reason="download complete")
