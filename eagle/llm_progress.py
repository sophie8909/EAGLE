"""Human-readable progress for blocking local LLM requests."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator


@contextmanager
def llm_request_progress(
    *,
    stage: str,
    endpoint: str,
    model: str,
    candidate_id: str | None = None,
    heartbeat_seconds: float = 30.0,
) -> Iterator[None]:
    """Print request start, periodic heartbeat, and terminal status to stdout."""

    started = time.monotonic()
    stopped = threading.Event()
    candidate_text = f" candidate={candidate_id}" if candidate_id else ""
    prefix = f"[llm {stage}]{candidate_text} endpoint={endpoint} model={model}"
    print(f"{prefix} status=started", flush=True)

    def heartbeat() -> None:
        while not stopped.wait(heartbeat_seconds):
            elapsed = time.monotonic() - started
            print(f"{prefix} status=waiting elapsed_seconds={elapsed:.1f}", flush=True)

    thread = threading.Thread(target=heartbeat, name=f"llm-{stage}-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    except BaseException:
        elapsed = time.monotonic() - started
        print(f"{prefix} status=failed elapsed_seconds={elapsed:.1f}", flush=True)
        raise
    else:
        elapsed = time.monotonic() - started
        print(f"{prefix} status=completed elapsed_seconds={elapsed:.1f}", flush=True)
    finally:
        stopped.set()
        thread.join(timeout=1)
