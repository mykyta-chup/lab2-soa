import os
import socket
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.discovery import next_url
from app.producer import publish_event

SERVICE = os.getenv("SERVICE_NAME", "library-service")
INSTANCE = socket.gethostname()

app = FastAPI(title="Library Service", version="1.0.0")

items: dict[int, dict[str, Any]] = {}
next_id = 1


class AddIn(BaseModel):
    game_id: int


class ProgressIn(BaseModel):
    status: Literal["Planned", "Playing", "Dropped"] | None = None
    hours_played: float | None = Field(default=None, ge=0)


class CompleteIn(BaseModel):
    rating: int = Field(ge=1, le=10)
    hours_played: float | None = Field(default=None, ge=0)


class ContributeIn(BaseModel):
    text: str


def instance_payload(**extra: Any) -> dict[str, Any]:
    return {"service": SERVICE, "instance": INSTANCE, **extra}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bearer(authorization: str | None) -> dict[str, str]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return {"authorization": authorization}


def call_service(
    service_name: str,
    method: str,
    path: str,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> dict[str, Any]:
    try:
        url = next_url(service_name)
    except LookupError:
        raise HTTPException(status_code=503, detail=f"{service_name} is not registered in Consul")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Discovery failed for {service_name}: {exc}")

    print(f"[library] {method} {service_name} -> {url}{path}", flush=True)
    try:
        with httpx.Client(timeout=5) as client:
            response = client.request(method, f"{url}{path}", json=json_body, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{service_name} call failed: {exc}")

    try:
        payload = response.json()
    except Exception:
        payload = {"detail": response.text}
    if response.status_code >= 400:
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        raise HTTPException(status_code=response.status_code, detail=detail)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail=f"Unexpected response from {service_name}")
    return payload


def require_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return call_service("auth-service", "GET", "/auth/me", headers=_bearer(authorization))


def _owned_item(item_id: int, user_id: int) -> dict[str, Any]:
    item = items.get(item_id)
    if item is None or item["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Library item not found")
    return item


def _emit(event_name: str, item: dict[str, Any]) -> None:
    event = {
        "event": event_name,
        "occurred_at": _now(),
        "producer": f"{SERVICE}@{INSTANCE}",
        "user_id": item["user_id"],
        "item_id": item["id"],
        "game_id": item["game_id"],
        "title": item["title"],
        "developer": item["developer"],
        "genre": item["genre"],
        "status": item["status"],
        "hours_played": item["hours_played"],
        "rating": item["rating"],
    }
    try:
        publish_event(event)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to publish {event_name}: {exc}")


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
    return instance_payload(message="Game Library Management context")


@app.post("/contribute")
def contribute(body: ContributeIn):
    note = f"{SERVICE}@{INSTANCE}"
    return instance_payload(text=f"{body.text} -> {note}", protocol="HTTP", appended=note)


@app.post("/library/items", status_code=201)
def add_item(body: AddIn, user: dict[str, Any] = Depends(require_user)):
    global next_id
    game = call_service("metadata-service", "GET", f"/games/{body.game_id}")
    duplicate = any(
        item["user_id"] == user["user_id"] and item["game_id"] == body.game_id
        for item in items.values()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Game is already in the library")

    item = {
        "id": next_id,
        "user_id": user["user_id"],
        "game_id": game["game_id"],
        "title": game["title"],
        "developer": game["developer"],
        "genre": game["genre"],
        "platform": game["platform"],
        "status": "Planned",
        "hours_played": 0,
        "rating": None,
        "added_at": _now(),
    }
    items[next_id] = item
    next_id += 1
    try:
        _emit("library.game-added", item)
    except HTTPException:
        del items[item["id"]]
        raise
    return instance_payload(item=item, event_published=True)


@app.get("/library/me")
def my_library(user: dict[str, Any] = Depends(require_user)):
    owned = [item for item in items.values() if item["user_id"] == user["user_id"]]
    return instance_payload(user_id=user["user_id"], items=owned, total=len(owned))


@app.patch("/library/items/{item_id}")
def update_progress(
    item_id: int,
    body: ProgressIn,
    user: dict[str, Any] = Depends(require_user),
):
    item = _owned_item(item_id, user["user_id"])
    if item["status"] == "Completed":
        raise HTTPException(status_code=409, detail="Completed game progress is closed")
    if body.status is not None:
        item["status"] = body.status
    if body.hours_played is not None:
        item["hours_played"] = body.hours_played
    _emit("library.progress-updated", item)
    return instance_payload(item=item, event_published=True)


@app.post("/library/items/{item_id}/complete")
def complete_item(
    item_id: int,
    body: CompleteIn,
    user: dict[str, Any] = Depends(require_user),
):
    item = _owned_item(item_id, user["user_id"])
    if body.hours_played is not None:
        item["hours_played"] = body.hours_played
    rating = call_service(
        "rating-service",
        "POST",
        "/ratings",
        json_body={
            "user_id": user["user_id"],
            "game_id": item["game_id"],
            "title": item["title"],
            "developer": item["developer"],
            "genre": item["genre"],
            "rating": body.rating,
        },
    )
    item["status"] = "Completed"
    item["rating"] = body.rating
    _emit("library.game-completed", item)
    return instance_payload(item=item, rating=rating, event_published=True)


@app.delete("/library/items/{item_id}")
def remove_item(item_id: int, user: dict[str, Any] = Depends(require_user)):
    item = _owned_item(item_id, user["user_id"])
    removed = dict(item)
    removed["status"] = "Removed"
    del items[item_id]
    _emit("library.game-removed", removed)
    return instance_payload(removed=removed, event_published=True)
