import hashlib
import os
import secrets
import socket
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

SERVICE = os.getenv("SERVICE_NAME", "auth-service")
INSTANCE = socket.gethostname()
security = HTTPBearer(auto_error=False)

app = FastAPI(title="Auth Service", version="1.0.0")

users: dict[int, dict[str, Any]] = {}
tokens: dict[str, int] = {}
next_id = 1


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=4, max_length=64)


class LoginIn(BaseModel):
    username: str
    password: str


class ContributeIn(BaseModel):
    text: str


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _public(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user["email"],
    }


def instance_payload(**extra: Any) -> dict[str, Any]:
    return {"service": SERVICE, "instance": INSTANCE, **extra}


@app.middleware("http")
async def mark_instance(request, call_next):
    response = await call_next(request)
    response.headers["X-Service-Instance"] = INSTANCE
    return response


@app.get("/health")
def health():
    return instance_payload(status="ok")


@app.get("/")
def root():
    return instance_payload(message="User Management context")


@app.post("/contribute")
def contribute(body: ContributeIn):
    note = f"{SERVICE}@{INSTANCE}"
    return instance_payload(
        text=f"{body.text} -> {note}",
        protocol="HTTP",
        appended=note,
    )


@app.post("/auth/register", status_code=201)
def register(body: RegisterIn):
    global next_id
    if any(user["username"] == body.username for user in users.values()):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = {
        "user_id": next_id,
        "username": body.username,
        "email": body.email,
        "password_hash": _hash(body.password),
    }
    users[next_id] = user
    next_id += 1
    token = secrets.token_urlsafe(24)
    tokens[token] = user["user_id"]
    return instance_payload(**_public(user), token=token)


@app.post("/auth/login")
def login(body: LoginIn):
    user = next((item for item in users.values() if item["username"] == body.username), None)
    if user is None or user["password_hash"] != _hash(body.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_urlsafe(24)
    tokens[token] = user["user_id"]
    return instance_payload(**_public(user), token=token)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    user_id = tokens.get(credentials.credentials)
    if user_id is None or user_id not in users:
        raise HTTPException(status_code=401, detail="Invalid token")
    return users[user_id]


@app.get("/auth/me")
def me(user: dict[str, Any] = Depends(current_user)):
    return instance_payload(**_public(user))


@app.get("/users/{user_id}")
def get_user(user_id: int):
    user = users.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return instance_payload(**_public(user))
