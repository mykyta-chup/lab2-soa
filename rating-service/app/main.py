import os
import socket
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

SERVICE = os.getenv("SERVICE_NAME", "rating-service")
INSTANCE = socket.gethostname()

app = FastAPI(title="Rating Service", version="1.0.0")

entries: list[dict[str, Any]] = []


class RatingIn(BaseModel):
    user_id: int
    game_id: int
    title: str
    developer: str
    genre: str
    rating: int = Field(ge=1, le=10)


class ContributeIn(BaseModel):
    text: str


def instance_payload(**extra: Any) -> dict[str, Any]:
    return {"service": SERVICE, "instance": INSTANCE, **extra}


def _average(group: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[int]] = {}
    for entry in entries:
        buckets.setdefault(entry[group], []).append(entry["rating"])
    result = []
    for name, values in sorted(buckets.items()):
        result.append(
            {
                "name": name,
                "votes": len(values),
                "average": round(sum(values) / len(values), 2),
            }
        )
    return result


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
    return instance_payload(message="Game Rating Management context")


@app.post("/contribute")
def contribute(body: ContributeIn):
    note = f"{SERVICE}@{INSTANCE}"
    return instance_payload(text=f"{body.text} -> {note}", protocol="HTTP", appended=note)


@app.post("/ratings", status_code=201)
def add_rating(body: RatingIn):
    record = body.model_dump()
    entries.append(record)
    print(f"[rating] stored rating {record['rating']} for {record['title']}", flush=True)
    return instance_payload(**record, stored=True)


@app.get("/ratings/games")
def game_ratings():
    buckets: dict[int, dict[str, Any]] = {}
    for entry in entries:
        bucket = buckets.setdefault(
            entry["game_id"],
            {"game_id": entry["game_id"], "title": entry["title"], "ratings": []},
        )
        bucket["ratings"].append(entry["rating"])
    items = []
    for bucket in buckets.values():
        values = bucket["ratings"]
        items.append(
            {
                "game_id": bucket["game_id"],
                "title": bucket["title"],
                "votes": len(values),
                "average": round(sum(values) / len(values), 2),
            }
        )
    return instance_payload(items=items)


@app.get("/ratings/genres")
def genre_ratings():
    return instance_payload(items=_average("genre"))


@app.get("/ratings/developers")
def developer_ratings():
    return instance_payload(items=_average("developer"))
