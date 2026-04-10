from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def timer(name: str, stats: dict[str, float]) -> Iterator[None]:
    """Accumulate elapsed time for one named phase into the provided stats dict."""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    stats[name] = stats.get(name, 0.0) + elapsed


def summarize_total_eval_time(stats: dict[str, float]) -> float:
    """Recompute the aggregate `total_eval_time` from all `*_time` entries."""
    total = 0.0
    for key, value in stats.items():
        if key.endswith("_time") and key != "total_eval_time":
            total += value
    stats["total_eval_time"] = total
    return total


def write_jsonl(record: dict[str, Any], path: str | Path) -> None:
    """Append one JSON object as a JSONL row, creating parent folders if needed."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_base_record(
    *,
    generation: int | None = None,
    individual_id: str | None = None,
    record_type: str,
) -> dict[str, Any]:
    """Create the common metadata envelope shared by profiler records."""
    return {
        "timestamp": datetime.now().isoformat(),
        "record_type": record_type,
        "generation": generation,
        "individual_id": individual_id,
    }
