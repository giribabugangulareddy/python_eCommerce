import asyncio
from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, dict[WebSocket, str]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, role: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id][websocket] = role

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(user_id)
            if connections is not None:
                connections.pop(websocket, None)
                if not connections:
                    self._connections.pop(user_id, None)

    async def publish(self, event: dict[str, Any], audience: str = "all") -> None:
        async with self._lock:
            targets = [
                (user_id, websocket)
                for user_id, connections in self._connections.items()
                for websocket, role in connections.items()
                if audience == "all"
                or audience == f"user:{user_id}"
                or (audience == "admins" and role == "admin")
            ]
        stale: list[tuple[int, WebSocket]] = []
        for user_id, websocket in targets:
            try:
                await websocket.send_json(
                    jsonable_encoder(event, custom_encoder={Decimal: str})
                )
            except (RuntimeError, OSError, WebSocketDisconnect):
                stale.append((user_id, websocket))
        for user_id, websocket in stale:
            await self.disconnect(user_id, websocket)


manager = ConnectionManager()
