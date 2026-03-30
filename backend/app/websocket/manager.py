import json
import logging
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time data push."""

    def __init__(self) -> None:
        # All active connections
        self._connections: list[WebSocket] = []
        # Authenticated user connections: user_id -> list of websockets
        self._user_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: Optional[int] = None) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        if user_id is not None:
            if user_id not in self._user_connections:
                self._user_connections[user_id] = []
            self._user_connections[user_id].append(websocket)
        logger.info("WebSocket connected. Total connections: %d", len(self._connections))

    def disconnect(self, websocket: WebSocket, user_id: Optional[int] = None) -> None:
        """Remove a WebSocket connection."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        if user_id is not None and user_id in self._user_connections:
            conns = self._user_connections[user_id]
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                del self._user_connections[user_id]
        logger.info("WebSocket disconnected. Total connections: %d", len(self._connections))

    async def broadcast(self, channel: str, data: Any) -> None:
        """Broadcast a message to all connected clients."""
        message = json.dumps({"channel": channel, "data": data})
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        # Clean up stale connections
        for ws in stale:
            self.disconnect(ws)

    async def send_personal(self, user_id: int, channel: str, data: Any) -> None:
        """Send a message to all connections of a specific user."""
        conns = self._user_connections.get(user_id, [])
        message = json.dumps({"channel": channel, "data": data})
        stale: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws, user_id)


# Singleton instance
manager = ConnectionManager()
