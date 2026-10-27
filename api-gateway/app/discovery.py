import os
import threading

import httpx

CONSUL_HOST = os.getenv("CONSUL_HOST", "consul")
CONSUL_PORT = int(os.getenv("CONSUL_PORT", "8500"))

_counters: dict[str, int] = {}
_lock = threading.Lock()


def _service_urls(service_name: str) -> list[str]:
    base = f"http://{CONSUL_HOST}:{CONSUL_PORT}"
    with httpx.Client(timeout=3) as client:
        healthy = client.get(f"{base}/v1/health/service/{service_name}", params={"passing": "true"})
        healthy.raise_for_status()
        payload = healthy.json()
        if not payload:
            catalog = client.get(f"{base}/v1/catalog/service/{service_name}")
            catalog.raise_for_status()
            payload = [
                {"Service": item}
                for item in catalog.json()
            ]
    urls = []
    for item in payload:
        service = item["Service"]
        address = service.get("ServiceAddress") or service.get("Address")
        port = service.get("ServicePort") or service.get("Port")
        if address and port:
            urls.append(f"http://{address}:{port}")
    return urls


def next_url(service_name: str) -> str:
    urls = _service_urls(service_name)
    if not urls:
        raise LookupError(service_name)
    with _lock:
        index = _counters.get(service_name, 0)
        _counters[service_name] = index + 1
    return urls[index % len(urls)]
