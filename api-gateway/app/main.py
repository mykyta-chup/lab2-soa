import os
import socket
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.discovery import next_url

SERVICE = os.getenv("SERVICE_NAME", "api-gateway")
INSTANCE = socket.gethostname()
CONSUL_HOST = os.getenv("CONSUL_HOST", "consul")
CONSUL_PORT = int(os.getenv("CONSUL_PORT", "8500"))

app = FastAPI(
    title="Game Library Tracker API Gateway",
    version="1.0.0",
)


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=4, max_length=64)


class LoginIn(BaseModel):
    username: str
    password: str


class AddIn(BaseModel):
    game_id: int


class ProgressIn(BaseModel):
    status: str | None = None
    hours_played: float | None = Field(default=None, ge=0)


class CompleteIn(BaseModel):
    rating: int = Field(ge=1, le=10)
    hours_played: float | None = Field(default=None, ge=0)


class ContributeIn(BaseModel):
    text: str


PIPELINE = (
    "auth-service",
    "metadata-service",
    "library-service",
    "rating-service",
    "analytics-service",
)


bearer = HTTPBearer()


def _auth_header(credentials: HTTPAuthorizationCredentials) -> dict[str, str]:
    return {"authorization": f"Bearer {credentials.credentials}"}


async def call_service(
    service_name: str,
    method: str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, Any, str | None]:
    try:
        base = next_url(service_name)
    except LookupError:
        raise HTTPException(status_code=503, detail=f"{service_name} is not registered in Consul")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Discovery failed for {service_name}: {exc}")

    print(f"[gateway] {method} {service_name} -> {base}{path}", flush=True)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.request(
                method,
                f"{base}{path}",
                json=json_body,
                params=params,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{service_name} call failed: {exc}")

    instance = response.headers.get("x-service-instance")
    try:
        payload: Any = response.json()
    except Exception:
        payload = {"detail": response.text}
    if isinstance(payload, dict):
        payload["routed_to"] = instance
    return response.status_code, payload, instance


def forward(
    service_name: str,
    method: str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
    headers: dict | None = None,
):
    async def _respond():
        status, payload, _instance = await call_service(
            service_name, method, path, json_body, params, headers
        )
        return JSONResponse(status_code=status, content=payload)

    return _respond()


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE, "instance": INSTANCE}


@app.get("/")
def root():
    return {
        "system": "Game Library Tracker",
        "service": SERVICE,
        "instance": INSTANCE,
        "docs": "/docs",
        "contexts": [
            "auth-service",
            "metadata-service",
            "library-service",
            "rating-service",
            "analytics-service",
        ],
    }


@app.get("/discovery/{service_name}")
def discovery(service_name: str):
    url = f"http://{CONSUL_HOST}:{CONSUL_PORT}/v1/health/service/{service_name}"
    try:
        response = httpx.get(url, timeout=3)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Consul is unavailable: {exc}")
    instances = []
    for item in response.json():
        service = item["Service"]
        instances.append(
            {
                "id": service["ID"],
                "address": service["Address"],
                "port": service["Port"],
                "checks": [check["Status"] for check in item.get("Checks", [])],
            }
        )
    return {"service": service_name, "count": len(instances), "instances": instances}


@app.post("/demo/pipeline")
async def pipeline(body: ContributeIn):
    text = body.text
    steps = []
    for service_name in PIPELINE:
        status, data, instance = await call_service(
            service_name, "POST", "/contribute", {"text": text}
        )
        if status >= 400:
            raise HTTPException(status_code=status, detail=data)
        text = data["text"]
        steps.append(
            {
                "service": service_name,
                "instance": instance,
                "protocol": "HTTP",
                "text": text,
            }
        )
    return {"pattern": "orchestration", "protocol": "HTTP", "text": text, "steps": steps}


@app.get("/demo/balance/{service_name}")
async def balance(service_name: str, n: int = 6):
    if service_name not in PIPELINE:
        raise HTTPException(status_code=404, detail="Unknown service")
    hits = []
    for _ in range(max(1, min(n, 20))):
        status, payload, instance = await call_service(service_name, "GET", "/health")
        hits.append(
            {
                "status": status,
                "instance": payload.get("instance") if isinstance(payload, dict) else instance,
            }
        )
    return {"service": service_name, "hits": hits}


@app.post("/auth/register", status_code=201)
async def register(body: RegisterIn):
    return await forward("auth-service", "POST", "/auth/register", body.model_dump())


@app.post("/auth/login")
async def login(body: LoginIn):
    return await forward("auth-service", "POST", "/auth/login", body.model_dump())


@app.get("/auth/me")
async def me(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    return await forward("auth-service", "GET", "/auth/me", headers=_auth_header(credentials))


@app.get("/games")
async def games(q: str = ""):
    return await forward("metadata-service", "GET", "/games", params={"q": q})


@app.get("/games/{game_id}")
async def game(game_id: int):
    return await forward("metadata-service", "GET", f"/games/{game_id}")


@app.post("/library/items", status_code=201)
async def add_item(body: AddIn, credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    return await forward(
        "library-service",
        "POST",
        "/library/items",
        body.model_dump(),
        headers=_auth_header(credentials),
    )


@app.get("/library/me")
async def my_library(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    return await forward(
        "library-service",
        "GET",
        "/library/me",
        headers=_auth_header(credentials),
    )


@app.patch("/library/items/{item_id}")
async def update_progress(
    item_id: int,
    body: ProgressIn,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    return await forward(
        "library-service",
        "PATCH",
        f"/library/items/{item_id}",
        body.model_dump(exclude_none=True),
        headers=_auth_header(credentials),
    )


@app.post("/library/items/{item_id}/complete")
async def complete_item(
    item_id: int,
    body: CompleteIn,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    return await forward(
        "library-service",
        "POST",
        f"/library/items/{item_id}/complete",
        body.model_dump(exclude_none=True),
        headers=_auth_header(credentials),
    )


@app.delete("/library/items/{item_id}")
async def remove_item(item_id: int, credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    return await forward(
        "library-service",
        "DELETE",
        f"/library/items/{item_id}",
        headers=_auth_header(credentials),
    )


@app.get("/ratings/games")
async def rating_games():
    return await forward("rating-service", "GET", "/ratings/games")


@app.get("/ratings/genres")
async def rating_genres():
    return await forward("rating-service", "GET", "/ratings/genres")


@app.get("/ratings/developers")
async def rating_developers():
    return await forward("rating-service", "GET", "/ratings/developers")


@app.get("/analytics/events")
async def analytics_events():
    return await forward("analytics-service", "GET", "/analytics/events")


@app.get("/analytics/stats")
async def analytics_stats():
    return await forward("analytics-service", "GET", "/analytics/stats")
