import os
import socket
import sys
import time

import requests

CONSUL_HOST = os.getenv("CONSUL_HOST", "consul")
CONSUL_PORT = int(os.getenv("CONSUL_PORT", "8500"))
SERVICE_NAME = os.environ["SERVICE_NAME"]
SERVICE_PORT = int(os.environ["SERVICE_PORT"])


def wait_until_healthy() -> None:
    url = f"http://127.0.0.1:{SERVICE_PORT}/health"
    for attempt in range(1, 41):
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200:
                print(f"[consul] {SERVICE_NAME} is accepting requests", flush=True)
                return
        except requests.RequestException:
            pass
        print(f"[consul] waiting for local app ({attempt}/40)", flush=True)
        time.sleep(0.5)
    print(f"[consul] {SERVICE_NAME} did not become healthy", flush=True)
    sys.exit(1)


def register_service() -> None:
    host = socket.gethostname()
    payload = {
        "Name": SERVICE_NAME,
        "ID": f"{SERVICE_NAME}-{host}",
        "Address": host,
        "Port": SERVICE_PORT,
        "Check": {
            "HTTP": f"http://{host}:{SERVICE_PORT}/health",
            "Interval": "5s",
            "Timeout": "2s",
            "DeregisterCriticalServiceAfter": "1m",
        },
    }
    endpoint = f"http://{CONSUL_HOST}:{CONSUL_PORT}/v1/agent/service/register"
    for attempt in range(1, 31):
        try:
            response = requests.put(endpoint, json=payload, timeout=3)
            if response.status_code == 200:
                print(f"[consul] registered {payload['ID']} at {host}:{SERVICE_PORT}", flush=True)
                return
            print(f"[consul] register failed ({response.status_code}) {response.text}", flush=True)
        except requests.RequestException as exc:
            print(f"[consul] retry {attempt}/30: {exc}", flush=True)
        time.sleep(1)
    print(f"[consul] could not register {SERVICE_NAME}", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    wait_until_healthy()
    register_service()
