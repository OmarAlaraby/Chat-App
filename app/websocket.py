from fastapi import WebSocket, WebSocketDisconnect
from typing import List
from collections import defaultdict
from contextlib import contextmanager
from app.config.database import SessionLocal
from app.models.models import User

@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[tuple[WebSocket, str]] = []
        self.user_status = defaultdict(lambda: 'offline')

    async def connect(self, websocket: WebSocket, username: str):
        try:
            await websocket.accept()
            self.active_connections.append((websocket, username))
            self.user_status[username] = 'online'
            await self.broadcast_userlist_status()
        except Exception as e:
            print(f"Error connecting websocket: {e}")
            if websocket in [conn for conn, _ in self.active_connections]:
                self.disconnect(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            for conn, username in list(self.active_connections):
                if conn == websocket:
                    self.active_connections.remove((conn, username))
                    if not any(u == username for _, u in self.active_connections):
                        self.user_status[username] = 'offline'
                    break
            import asyncio
            asyncio.create_task(self.broadcast_userlist_status())
        except Exception as e:
            print(f"Error disconnecting websocket: {e}")

    async def broadcast(self, message: str):
        disconnected = []
        for conn, _ in self.active_connections:
            try:
                await conn.send_text(message)
            except WebSocketDisconnect:
                disconnected.append(conn)
            except Exception as e:
                print(f"Error broadcasting message: {e}")
                disconnected.append(conn)
        
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_json(self, data):
        disconnected = []
        for conn, _ in self.active_connections:
            try:
                await conn.send_json(data)
            except WebSocketDisconnect:
                disconnected.append(conn)
            except Exception as e:
                print(f"Error broadcasting JSON: {e}")
                disconnected.append(conn)
        
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_userlist_status(self):
        with get_db() as db:
            users = db.query(User).all()
            user_names = [user.username for user in users]
            data = {
                "type": "userlist",
                "users": user_names,
                "status": {user: self.user_status[user] for user in user_names}
            }
            await self.broadcast_json(data)

manager = ConnectionManager()