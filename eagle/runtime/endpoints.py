"""Endpoint resolution, persistence, and HTTP health checks."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import RuntimeConfig, ServerConfig

ENDPOINT_SCHEMA_VERSION = "runtime-endpoints-v1"


def health_check(server: ServerConfig, runtime: RuntimeConfig, *, retries: int | None = None) -> tuple[bool, str]:
    attempts = retries if retries is not None else runtime.health_check.retries
    errors: list[str] = []
    for attempt in range(attempts):
        for path in (runtime.health_check.path, runtime.health_check.fallback_path):
            url = server.base_url + path
            try:
                with urllib.request.urlopen(url, timeout=runtime.watchdog.health_timeout_seconds) as response:
                    if 200 <= response.status < 300:
                        return True, f"{url} returned HTTP {response.status}"
                    errors.append(f"{url}: HTTP {response.status}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                errors.append(f"{url}: {exc}")
        if attempt + 1 < attempts:
            time.sleep(runtime.health_check.retry_delay_seconds)
    return False, errors[-1] if errors else "health check failed"


def endpoint_payload(runtime: RuntimeConfig) -> dict[str, object]:
    return {
        "schema_version": ENDPOINT_SCHEMA_VERSION,
        "roles": {
            role: {"server": server.name, "base_url": server.base_url}
            for server in runtime.enabled_servers()
            for role in server.roles
        },
    }


def atomic_write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def write_resolved_endpoints(runtime: RuntimeConfig) -> Path:
    return atomic_write_json(runtime.resolved_endpoints_path, endpoint_payload(runtime))


def load_resolved_endpoints(path: str | Path) -> dict[str, dict[str, str]]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ENDPOINT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported endpoint mapping schema in {source}.")
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        raise ValueError(f"Endpoint mapping {source} has no roles mapping.")
    return {
        str(role): {"server": str(item["server"]), "base_url": str(item["base_url"])}
        for role, item in roles.items()
        if isinstance(item, dict) and item.get("server") and item.get("base_url")
    }
