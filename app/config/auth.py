from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer
from fastapi import Cookie
from starlette.responses import Response

SECRET_KEY = "super-secret-key"  # Change this in production
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
serializer = URLSafeSerializer(SECRET_KEY, salt="session")

def create_session(response: Response, username: str):
    session_token = serializer.dumps({"username": username})
    response.set_cookie("session", session_token, httponly=True)

def get_current_user(session: str = Cookie(None)):
    if not session:
        return None
    try:
        data = serializer.loads(session)
        return data.get("username")
    except:
        return None

def clear_session(response: Response):
    response.delete_cookie("session")