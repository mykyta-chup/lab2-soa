import json
import os

import pika

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "mykyta")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "mykyta")
QUEUE = os.getenv("RABBITMQ_QUEUE", "game_events")


def publish_event(event: dict) -> None:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=5672,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=10,
    )
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE, durable=True)
    body = json.dumps(event)
    channel.basic_publish(
        exchange="",
        routing_key=QUEUE,
        body=body,
        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
    )
    connection.close()
    print(f"[library] published {event['event']}", flush=True)
