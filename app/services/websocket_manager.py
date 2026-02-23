from typing import List, Dict
from fastapi import WebSocket
import json

class ConnectionManager:
    def __init__(self):
        # Map clientId to list of active WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = []
        self.active_connections[client_id].append(websocket)

    def disconnect(self, client_id: str, websocket: WebSocket):
        if client_id in self.active_connections:
            self.active_connections[client_id].remove(websocket)
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]

    async def broadcast_to_client(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            # We use a list copy to avoid issues if a connection drops during iteration
            for connection in list(self.active_connections[client_id]):
                try:
                    await connection.send_json(message)
                except Exception:
                    # If sending fails, the connection might be closed
                    self.disconnect(client_id, connection)

manager = ConnectionManager()
