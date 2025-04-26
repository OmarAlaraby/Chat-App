from fastapi import FastAPI, Request, Form, status, Response, Cookie, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer, BadSignature
from starlette.responses import Response
from typing import List
from datetime import datetime
from collections import defaultdict
import json

app = FastAPI()

templates = Jinja2Templates(directory='templates')

# SQLite database setup
DATABASE_URL = "sqlite:///./chat_app.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    content = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = "super-secret-key"  # Change this in production
serializer = URLSafeSerializer(SECRET_KEY, salt="session")

# Helper functions for session management
def create_session(response: Response, username: str):
    session_token = serializer.dumps({"username": username})
    response.set_cookie("session", session_token, httponly=True)

def get_current_user(session: str = Cookie(None)):
    if not session:
        return None
    try:
        data = serializer.loads(session)
        return data.get("username")
    except BadSignature:
        return None

def clear_session(response: Response):
    response.delete_cookie("session")

@app.get("/")
def root():
    return RedirectResponse(url="/chat", status_code=status.HTTP_302_FOUND)

@app.get('/log-in', response_class=HTMLResponse)
async def login_get(request: Request, session: str = Cookie(None)):
    if get_current_user(session):
        return RedirectResponse(url="/chat", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name='login.html', context={"error": None})

@app.post('/log-in', response_class=HTMLResponse)
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    user = db.query(User).filter(User.username == username).first()
    db.close()
    if user and pwd_context.verify(password, user.password):
        response = RedirectResponse(url="/chat", status_code=status.HTTP_302_FOUND)
        create_session(response, username)
        return response
    error = "Invalid username or password"
    return templates.TemplateResponse(request=request, name='login.html', context={"error": error})

@app.get('/sign-up', response_class=HTMLResponse)
async def signup_get(request: Request, session: str = Cookie(None)):
    if get_current_user(session):
        return RedirectResponse(url="/chat", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name='signup.html', context={"error": None})

@app.post('/sign-up', response_class=HTMLResponse)
async def signup_post(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...), confirm: str = Form(...)):
    db = SessionLocal()
    user = db.query(User).filter(User.username == username).first()
    if user:
        db.close()
        error = "Username already exists"
        return templates.TemplateResponse(request=request, name='signup.html', context={"error": error})
    if password != confirm:
        db.close()
        error = "Passwords do not match"
        return templates.TemplateResponse(request=request, name='signup.html', context={"error": error})
    hashed_password = pwd_context.hash(password)
    new_user = User(username=username, email=email, password=hashed_password)
    db.add(new_user)
    db.commit()
    db.close()
    # Broadcast the new user list to all connected clients
    import asyncio
    asyncio.create_task(manager.broadcast_userlist_status())
    response = RedirectResponse(url="/chat", status_code=status.HTTP_302_FOUND)
    create_session(response, username)
    return response

@app.get('/chat', response_class=HTMLResponse)
async def chat_page(request: Request, session: str = Cookie(None)):
    username = get_current_user(session)
    if not username:
        return RedirectResponse(url="/log-in", status_code=status.HTTP_302_FOUND)
    db = SessionLocal()
    users = db.query(User).all()
    messages = db.query(Message).order_by(Message.id.asc()).all()
    db.close()
    return templates.TemplateResponse(request=request, name='chat.html', context={"users": users, "current_user": username, "messages": messages})

@app.post('/logout')
async def logout():
    response = RedirectResponse(url="/log-in", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session")
    return response

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[tuple[WebSocket, str]] = []
        self.user_status = defaultdict(lambda: 'offline')  # username -> status

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.active_connections.append((websocket, username))
        self.user_status[username] = 'online'
        await self.broadcast_userlist_status()
        await self.send_userlist_status(websocket)

    def disconnect(self, websocket: WebSocket):
        for conn, username in list(self.active_connections):
            if conn == websocket:
                self.active_connections.remove((conn, username))
                if not any(u == username for _, u in self.active_connections):
                    self.user_status[username] = 'offline'
                break
        import asyncio
        asyncio.create_task(self.broadcast_userlist_status())

    async def broadcast(self, message: str):
        for conn, _ in self.active_connections:
            await conn.send_text(message)

    async def broadcast_json(self, data):
        for conn, _ in self.active_connections:
            await conn.send_json(data)

    async def broadcast_userlist_status(self):
        db = SessionLocal()
        users = db.query(User).all()
        db.close()
        user_names = [user.username for user in users]
        data = {
            "type": "userlist",
            "users": user_names,
            "status": {user: self.user_status[user] for user in user_names}
        }
        for conn, _ in self.active_connections:
            await conn.send_json(data)

    async def send_userlist_status(self, websocket: WebSocket):
        db = SessionLocal()
        users = db.query(User).all()
        db.close()
        user_names = [user.username for user in users]
        data = {
            "type": "userlist",
            "users": user_names,
            "status": {user: self.user_status[user] for user in user_names}
        }
        await websocket.send_json(data)

manager = ConnectionManager()

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket, session: str = Cookie(None)):
    username = get_current_user(session)
    if not username:
        await websocket.close()
        return
    await manager.connect(websocket, username)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg_data = json.loads(data)
                if msg_data.get('type') == 'chat':
                    content = msg_data.get('content')
                    db = SessionLocal()
                    msg = Message(username=username, content=content)
                    db.add(msg)
                    db.commit()
                    timestamp = msg.timestamp.strftime('%Y-%m-%d %H:%M')
                    db.close()
                    await manager.broadcast_json({
                        'type': 'chat',
                        'username': username,
                        'content': content,
                        'timestamp': timestamp
                    })
            except Exception:
                # fallback for plain text
                await manager.broadcast(f"{username}: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
