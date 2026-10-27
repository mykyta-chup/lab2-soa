import json
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import pika
from fastapi import FastAPI
from pydantic import BaseModel

SERVICE = os.getenv("SERVICE_NAME", "analytics-service")
INSTANCE = socket.gethostname()
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "mykyta")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "mykyta")
QUEUE = os.getenv("RABBITMQ_QUEUE", "game_events")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    thread = threading.Thread(target=_consume, name="analytics-consumer", daemon=True)
    thread.start()
    yield


app = FastAPI(title="Analytics Service", version="1.0.0", lifespan=lifespan)

events: list[dict[str, Any]] = []
lock = threading.Lock()


class ContributeIn(BaseModel):
    text: str


def instance_payload(**extra: Any) -> dict[str, Any]:
    return {"service": SERVICE, "instance": INSTANCE, **extra}


def _callback(channel, method, properties, body):
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body.decode(errors="replace")}
    record = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "consumer": f"{SERVICE}@{INSTANCE}",
        "event": data,
    }
    with lock:
        events.append(record)
        if len(events) > 500:
            del events[:-500]
    print(f"[Analytics] Received event: {data}", flush=True)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _consume() -> None:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=5672,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=30,
    )
    while True:
        try:
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE, on_message_callback=_callback)
            print(f"[Analytics] Waiting for events on '{QUEUE}'...", flush=True)
            channel.start_consuming()
        except Exception as exc:
            print(f"[Analytics] broker unavailable, retrying: {exc}", flush=True)
            time.sleep(3)


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
    return instance_payload(message="Game Analytics consumer")


@app.post("/contribute")
def contribute(body: ContributeIn):
    note = f"{SERVICE}@{INSTANCE}"
    return instance_payload(text=f"{body.text} -> {note}", protocol="HTTP", appended=note)


@app.get("/analytics/events")
def list_events():
    with lock:
        items = list(events)
    return instance_payload(items=items, total=len(items))


@app.get("/analytics/stats")
def stats():
    with lock:
        snapshot = list(events)
    by_event: dict[str, int] = {}
    for record in snapshot:
        name = record["event"].get("event", "unknown") if isinstance(record["event"], dict) else "unknown"
        by_event[name] = by_event.get(name, 0) + 1
    return instance_payload(total=len(snapshot), by_event=by_event)
