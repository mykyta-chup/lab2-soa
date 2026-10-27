import os
import socket
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

SERVICE = os.getenv("SERVICE_NAME", "metadata-service")
INSTANCE = socket.gethostname()

app = FastAPI(title="Game Metadata Service", version="1.0.0")

GAMES: dict[int, dict[str, Any]] = {
    1: {
        "game_id": 1,
        "title": "The Witcher 3: Wild Hunt",
        "developer": "CD Projekt Red",
        "genre": "RPG",
        "platform": "PC",
        "description": "Open-world RPG about Geralt of Rivia.",
    },
    2: {
        "game_id": 2,
        "title": "Hades",
        "developer": "Supergiant Games",
        "genre": "Roguelike",
        "platform": "PC",
        "description": "Roguelike about escaping the Underworld.",
    },
    3: {
        "game_id": 3,
        "title": "God of War",
        "developer": "Santa Monica Studio",
        "genre": "Action",
        "platform": "PlayStation",
        "description": "Action adventure of Kratos and Atreus.",
    },
    4: {
        "game_id": 4,
        "title": "Hollow Knight",
        "developer": "Team Cherry",
        "genre": "Metroidvania",
        "platform": "PC",
        "description": "Action-adventure in the kingdom of Hallownest.",
    },
    5: {
        "game_id": 5,
        "title": "Elden Ring",
        "developer": "FromSoftware",
        "genre": "RPG",
        "platform": "PC",
        "description": "Open-world action RPG in the Lands Between.",
    },
    6: {
        "game_id": 6,
        "title": "Celeste",
        "developer": "Extremely OK Games",
        "genre": "Platformer",
        "platform": "PC",
        "description": "Precision platformer about climbing a mountain.",
    },
    7: {
        "game_id": 7,
        "title": "Stardew Valley",
        "developer": "ConcernedApe",
        "genre": "Simulation",
        "platform": "PC",
        "description": "Farming and life simulation.",
    },
    8: {
        "game_id": 8,
        "title": "Cyberpunk 2077",
        "developer": "CD Projekt Red",
        "genre": "RPG",
        "platform": "PC",
        "description": "Open-world RPG in Night City.",
    },
}


class ContributeIn(BaseModel):
    text: str


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
    return instance_payload(message="Game Search and Metadata context")


@app.post("/contribute")
def contribute(body: ContributeIn):
    note = f"{SERVICE}@{INSTANCE}"
    return instance_payload(text=f"{body.text} -> {note}", protocol="HTTP", appended=note)


@app.get("/games")
def search_games(q: str = ""):
    query = q.strip().lower()
    items = []
    for game in GAMES.values():
        blob = " ".join(
            [game["title"], game["developer"], game["genre"], game["platform"]]
        ).lower()
        if not query or query in blob:
            items.append(game)
    return instance_payload(items=items, query=query)


@app.get("/games/{game_id}")
def get_game(game_id: int):
    game = GAMES.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return instance_payload(**game)
