"""Fixed execution policy shared by runtime and independent LLM stages."""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, TypeVar

T = TypeVar("T")
R = TypeVar("R")


# An explicit layer count avoids llama.cpp automatic offload fitting.
GPU_LAYERS = 999
MODEL_THREADS = 8
LLM_WORKERS = 2
MATCH_WORKERS = 10


_llm_worker_slot: ContextVar[int] = ContextVar("eagle_llm_worker_slot", default=0)


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
