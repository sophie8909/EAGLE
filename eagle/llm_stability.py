"""Repeated-request checks for LLM response stability."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STABILITY_SCHEMA_VERSION = "eagle-llm-stability-v1"


@dataclass(frozen=True)
class StabilityResult:
    """Hashes and raw responses from repeated identical LLM requests."""

    repeats: int
    responses: tuple[str, ...]

    @property
    def response_hashes(self) -> tuple[str, ...]:
        return tuple(hashlib.sha256(response.encode("utf-8")).hexdigest() for response in self.responses)

    @property
    def stable(self) -> bool:
        return len(set(self.response_hashes)) == 1

    def to_mapping(self) -> dict[str, Any]:
        return {
            "repeats": self.repeats,
            "stable": self.stable,
            "unique_response_count": len(set(self.response_hashes)),
            "responses": [
                {
                    "index": index,
                    "sha256": response_hash,
                    "length": len(response),
                }
                for index, (response_hash, response) in enumerate(
                    zip(self.response_hashes, self.responses), start=1
                )
            ],
        }


def run_stability_test(request: Callable[[], str], *, repeats: int = 3) -> StabilityResult:
    """Run the same request repeatedly and compare exact UTF-8 response hashes."""

    if repeats < 2:
        raise ValueError("repeats must be at least 2")
    responses = tuple(request() for _ in range(repeats))
    return StabilityResult(repeats=repeats, responses=responses)


def write_stability_report(
    output_dir: Path,
    result: StabilityResult,
    *,
    metadata: Mapping[str, object] | None = None,
) -> Path:
    """Persist raw responses and a compact hash report for later comparison."""

    output_dir.mkdir(parents=True, exist_ok=True)
    response_dir = output_dir / "responses"
    response_dir.mkdir(exist_ok=True)
    response_records = result.to_mapping()["responses"]
    assert isinstance(response_records, list)
    for record, response in zip(response_records, result.responses):
        assert isinstance(record, dict)
        path = response_dir / f"response_{record['index']:03d}.txt"
        path.write_text(response, encoding="utf-8")
        record["path"] = path.relative_to(output_dir).as_posix()
    report = {
        "schema_version": STABILITY_SCHEMA_VERSION,
        **dict(metadata or {}),
        **result.to_mapping(),
        "responses": response_records,
    }
    report_path = output_dir / "stability_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path
