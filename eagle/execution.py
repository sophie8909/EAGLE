"""Fixed execution policy shared by runtime and independent LLM stages."""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


# An explicit layer count avoids llama.cpp automatic offload fitting.
GPU_LAYERS = 999
MODEL_THREADS = 8
LLM_WORKERS = 2
MATCH_WORKERS = 10


def parallel_map(function: Callable[[T], R], values: Iterable[T]) -> list[R]:
    """Run independent work in bounded slots and retain input/result order."""
    executor = ThreadPoolExecutor(max_workers=LLM_WORKERS, thread_name_prefix="eagle-llm")
    try:
        return list(executor.map(function, values))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
