"""Fixtures for reading historical per-tick match artifacts."""

from pathlib import Path

from eagle.evaluation.runtime_evaluation import mock_round_state


def write_mock_round_state(
    directory: Path, *, tick: int, p0_resource: float, p1_resource: float,
) -> None:
    name, content = mock_round_state(tick=tick, p0_resource=p0_resource, p1_resource=p1_resource)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(content, encoding="utf-8")
