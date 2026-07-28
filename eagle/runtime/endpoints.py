"""Single endpoint resolution and health checks."""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from .config import RuntimeConfig

ENDPOINT_SCHEMA_VERSION = "runtime-endpoint-v1"

def health_check(runtime: RuntimeConfig, *, retries: int | None = None) -> tuple[bool, str]:
    attempts = retries if retries is not None else runtime.health_check.retries
    errors = []
    for attempt in range(attempts):
        for path in (runtime.health_check.path, runtime.health_check.fallback_path):
            url = runtime.llm.base_url + path
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
    payload = {"schema_version": ENDPOINT_SCHEMA_VERSION, "base_url": runtime.llm.base_url, "mode": runtime.llm.mode}
    if runtime.llm.model is not None:
        payload["model"] = str(runtime.llm.model)
    return payload

def atomic_write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    temporary.replace(path)
    return path

def write_resolved_endpoint(runtime: RuntimeConfig) -> Path:
    return atomic_write_json(runtime.resolved_endpoint_path, endpoint_payload(runtime))

def load_resolved_endpoint(path: str | Path) -> dict[str, object]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ENDPOINT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported endpoint schema in {source}.")
    if not isinstance(payload.get("base_url"), str) or not isinstance(payload.get("mode"), str):
        raise ValueError(f"Resolved endpoint {source} is incomplete.")
    return payload

