"""WebSocket endpoint: real-time push of new readings/aggregates.

    ws://<host>/ws/{station_id}/{data_type}?api_key=<key>

`station_id` and `data_type` mean the same thing as the REST
current/range endpoints (see app.api.query_routes) - data_type is one
of raw/1m/1h/1d. Auth uses the same keys.json records as the REST API,
but since browser WebSocket clients can't set custom headers on the
handshake, the key goes in an `api_key` query parameter instead of the
X-API-Key header - see app.security.dependencies.require_api_key_ws.

This is purely server-push: nothing is sent on connect, and the server
never expects the client to send anything either. The first message
arrives whenever the next matching ingestion happens (see
app.api.routes, which calls ws_manager.broadcast() after every write).
Message shape is just the row itself - no `storage_status` wrapper like
the REST endpoints have, kept minimal since these can arrive
frequently.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.security.dependencies import require_api_key_ws
from app.storage.registry import ws_manager

router = APIRouter()


class DataType(str, Enum):
    raw = "raw"
    one_minute = "1m"
    one_hour = "1h"
    one_day = "1d"


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
