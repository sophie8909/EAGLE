"""Read-only access to versioned final-test summaries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eagle.final_test import FINAL_TEST_SCHEMA_VERSION


class FinalTestReadError(ValueError):
    """An existing final-test summary is malformed or unsupported."""


@dataclass(frozen=True)
class FinalTestSummary:
    final_test_id: str
    path: Path
    status: str
    formal: bool
    selector: str
    tested_candidate_ids: tuple[str, ...]
    expected_matches: int
    completed_matches: int
    incomplete_matches: int
    candidates: dict[str, Any] = field(default_factory=dict)
    artifact_paths: dict[str, Path] = field(default_factory=dict)

    def for_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        value = self.candidates.get(candidate_id)
        return value if isinstance(value, dict) else None


def load_final_test_summaries(run_dir: Path) -> list[FinalTestSummary]:
    root = run_dir / "final_tests"
    if not root.is_dir():
        return []
    summaries = [_load_summary(path) for path in sorted(root.glob("*/summary.json"))]
    return sorted(summaries, key=lambda item: item.final_test_id, reverse=True)


def _load_summary(path: Path) -> FinalTestSummary:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FinalTestReadError(f"Cannot parse final-test summary {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FinalTestReadError(f"Final-test summary must be an object: {path}")
    version = payload.get("final_test_schema_version")
    if version != FINAL_TEST_SCHEMA_VERSION:
        raise FinalTestReadError(
            f"Unsupported final-test schema {version!r} in {path}; "
            f"expected {FINAL_TEST_SCHEMA_VERSION!r}."
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, dict):
        raise FinalTestReadError(f"Final-test summary has no candidates object: {path}")
    tested = payload.get("tested_candidate_ids")
    if not isinstance(tested, list) or not all(isinstance(item, str) for item in tested):
        raise FinalTestReadError(f"Final-test summary has invalid tested_candidate_ids: {path}")
    artifact_names = payload.get("artifact_paths")
    artifact_paths: dict[str, Path] = {"summary": path}
    if isinstance(artifact_names, dict):
        for name, relative in artifact_names.items():
            if isinstance(name, str) and isinstance(relative, str):
                artifact_paths[name] = path.parent / relative
    return FinalTestSummary(
        final_test_id=str(payload.get("final_test_id") or path.parent.name),
        path=path.parent,
        status=str(payload.get("status") or "unknown"),
        formal=bool(payload.get("formal_final_test")),
        selector=str(payload.get("selector") or "unknown"),
        tested_candidate_ids=tuple(tested),
        expected_matches=_integer(payload.get("expected_total_matches")),
        completed_matches=_integer(payload.get("completed_total_matches")),
        incomplete_matches=_integer(payload.get("incomplete_total_matches")),
        candidates={str(key): value for key, value in candidates.items() if isinstance(value, dict)},
        artifact_paths=artifact_paths,
    )


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
