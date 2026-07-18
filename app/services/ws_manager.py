"""In-memory WebSocket connection manager.

Tracks active connections per (station_id, data_type) channel and
broadcasts JSON messages to all of them.

This is purely in-process state. If this app ever runs as multiple
worker processes (e.g. `uvicorn --workers 4`), each worker has its own
independent set of subscribers - a reading ingested on worker A would
never reach a client connected to worker B. Fine for a single process
(the deployment this project runs as); flag this explicitly if you
ever scale out, since the fix (Redis pub/sub or similar) is a real
architecture change, not a tweak.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

Channel = tuple[str, str]  # (station_id, data_type)


class WebSocketManager:
    def __init__(self):
        self._connections: dict[Channel, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, station_id: str, data_type: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[(station_id, data_type)].add(websocket)

    async def disconnect(self, station_id: str, data_type: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[(station_id, data_type)].discard(websocket)

    async def broadcast(self, station_id: str, data_type: str, message: dict) -> None:
        """Send `message` to every socket subscribed to this channel.

        Uses fastapi's jsonable_encoder (not raw json.dumps) because
        message dicts can contain datetime/Polars values that plain
        json.dumps can't serialize on its own.
        """
        async with self._lock:
            subscribers = list(self._connections.get((station_id, data_type), ()))
        if not subscribers:
            return

        payload = jsonable_encoder(message)
        dead: list[WebSocket] = []
        for ws in subscribers:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[(station_id, data_type)].discard(ws)

    def subscriber_count(self, station_id: str, data_type: str) -> int:
        return len(self._connections.get((station_id, data_type), ()))
