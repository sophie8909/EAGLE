"""Human-readable progress for blocking local LLM requests."""

from __future__ import annotations

import os
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
    """Report only abnormal requests unless verbose LLM progress is enabled."""

    started = time.monotonic()
    stopped = threading.Event()
    verbose = os.environ.get("EAGLE_LLM_PROGRESS", "").lower() in {"1", "true", "yes", "on"}
    candidate_text = f" candidate={candidate_id}" if candidate_id else ""
    prefix = f"[llm {stage}]{candidate_text} endpoint={endpoint} model={model}"
    if verbose:
        print(f"{prefix} status=started", flush=True)

    def heartbeat() -> None:
        while not stopped.wait(heartbeat_seconds):
            elapsed = time.monotonic() - started
            print(f"{prefix} status=waiting elapsed_seconds={elapsed:.1f}", flush=True)

    thread = None
    if verbose:
        thread = threading.Thread(target=heartbeat, name=f"llm-{stage}-heartbeat", daemon=True)
        thread.start()
    try:
        yield
    except BaseException as exc:
        elapsed = time.monotonic() - started
        detail = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:300]
        print(f"{prefix} status=failed elapsed_seconds={elapsed:.1f} error={detail}", flush=True)
        raise
    else:
        if verbose:
            elapsed = time.monotonic() - started
            print(f"{prefix} status=completed elapsed_seconds={elapsed:.1f}", flush=True)
    finally:
        stopped.set()
        if thread is not None:
            thread.join(timeout=1)
