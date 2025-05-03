from fastapi import APIRouter, Request, Form, Depends, Response, Cookie, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.config.database import get_db, SessionLocal
from app.config.auth import pwd_context, create_session, clear_session, get_current_user
from app.models.models import User
from app.websocket import manager
import asyncio

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/sign-up", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@router.post("/sign-up")
async def signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    hashed_password = pwd_context.hash(password)
    user = User(username=username, email=email, password=hashed_password)
    db.add(user)
    db.commit()
    
    response = RedirectResponse(url="/log-in", status_code=302)
    return response

@router.get("/log-in", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/log-in")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.password):
        return {"error": "Invalid username or password"}
    
    response = RedirectResponse(url="/chat", status_code=302)
    create_session(response, username)
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/log-in", status_code=302)
    clear_session(response)
    return response