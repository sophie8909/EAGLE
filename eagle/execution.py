"""Fixed execution policy shared by runtime and independent LLM stages."""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from threading import BoundedSemaphore, Lock
from typing import Iterator, TypeVar
from urllib.parse import urlsplit

T = TypeVar("T")
R = TypeVar("R")


# An explicit layer count avoids llama.cpp automatic offload fitting.
GPU_LAYERS = 999
MODEL_THREADS = 8
LLM_WORKERS = 2
MATCH_WORKERS = 10


_llm_worker_slot: ContextVar[int] = ContextVar("eagle_llm_worker_slot", default=0)
_server_slots: dict[tuple[str, str, int | None], BoundedSemaphore] = {}
_server_slots_lock = Lock()


@contextmanager
def llm_request_slot(base_url: str) -> Iterator[None]:
    """Share a server's request budget across reflection and generation workers."""

    url = urlsplit(base_url)
    key = (url.scheme.lower(), (url.hostname or "").lower(),
           url.port or (443 if url.scheme == "https" else 80))
    with _server_slots_lock:
        slots = _server_slots.setdefault(key, BoundedSemaphore(LLM_WORKERS))
    with slots:
        yield


def current_llm_worker_slot() -> int:
    """Return the stable endpoint slot assigned to the current candidate task."""

    return _llm_worker_slot.get()


@contextmanager
def llm_worker_slot(index: int) -> Iterator[None]:
    """Keep dependent serial work on the endpoint assigned to a task index."""

    token = _llm_worker_slot.set(index % LLM_WORKERS)
    try:
        yield
    finally:
        _llm_worker_slot.reset(token)


def parallel_map(function: Callable[[T], R], values: Iterable[T]) -> list[R]:
    """Run independent work in bounded slots and retain input/result order."""

    def run_indexed(item: tuple[int, T]) -> R:
        index, value = item
        with llm_worker_slot(index):
            return function(value)

    executor = ThreadPoolExecutor(max_workers=LLM_WORKERS, thread_name_prefix="eagle-llm")
    try:
        return list(executor.map(run_indexed, enumerate(values)))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
