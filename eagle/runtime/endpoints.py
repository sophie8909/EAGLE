"""Health checks for the one configured local llama-server endpoint."""
from __future__ import annotations

import time
import urllib.error
import urllib.request

from .config import RuntimeConfig


def health_check(runtime: RuntimeConfig, *, retries: int = 1) -> tuple[bool, str]:
    errors: list[str] = []
    for attempt in range(max(1, retries)):
        for path in ("/health", "/v1/models"):
            url = runtime.llm.base_url + path
            try:
                with urllib.request.urlopen(url, timeout=runtime.llm.health_timeout_seconds) as response:
                    if 200 <= response.status < 300:
                        return True, f"{url} returned HTTP {response.status}"
                    errors.append(f"{url}: HTTP {response.status}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                errors.append(f"{url}: {exc}")
        if attempt + 1 < max(1, retries):
            time.sleep(0.25)
    return False, errors[-1] if errors else "health check failed"
