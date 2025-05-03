from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Cookie, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.config.auth import get_current_user
from app.models.models import Message, User  # Added User import
from app.websocket import manager
import json
from datetime import datetime

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/chat", response_class=HTMLResponse)
async def chat(request: Request, session: str = Cookie(None)):
    username = get_current_user(session)
    if not username:
        return RedirectResponse(url="/log-in", status_code=status.HTTP_302_FOUND)
    
    db = next(get_db())
    messages = db.query(Message).order_by(Message.timestamp.desc()).limit(50).all()
    messages = list(reversed(messages))
    
    all_users = db.query(User).all()
    
    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "username": username,
            "messages": messages,
            "users": all_users
        }
    )

@router.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(websocket, username)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                if message_data["type"] == "message":
                    content = message_data["message"].strip()
                    if content:
                        db = next(get_db())
                        message = Message(username=username, content=content)
                        db.add(message)
                        db.commit()
                        
                        # Send message to all connected clients
                        await manager.broadcast_json({
                            "type": "message",
                            "username": username,
                            "message": content,
                            "timestamp": datetime.utcnow().isoformat()
                        })
            except json.JSONDecodeError:
                continue
            except KeyError:
                continue
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast_userlist_status()