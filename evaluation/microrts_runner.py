"""MicroRTS match runner adapter."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MatchResult:
    ok: bool
    score: float
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def run_microrts_match(
    *,
    microrts_dir: Path,
    classes_dir: Path,
    agent_class: str,
    opponent: str,
    tick_limit: int,
    match_index: int,
    mock: bool = False,
    mock_score: float = 0.0,
) -> MatchResult:
    microrts_dir = microrts_dir.resolve()
    classes_dir = classes_dir.resolve()
    command = [
        "java",
        "-cp",
        f"{classes_dir};{microrts_dir / 'bin'};{microrts_dir / 'lib' / '*'}",
        # TODO: Replace this placeholder with the confirmed MicroRTS batch evaluation main.
        "tests.EvaluateAI",
        agent_class,
        opponent,
        str(tick_limit),
    ]
    if mock:
        return MatchResult(
            ok=True,
            score=mock_score,
            command=command,
            stdout=f"mock match {match_index} score={mock_score}",
        )
    completed = subprocess.run(command, cwd=microrts_dir, capture_output=True, text=True, check=False)
    score = parse_score(completed.stdout)
    return MatchResult(
        ok=completed.returncode == 0 and score is not None,
        score=0.0 if score is None else score,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def parse_score(output: str) -> float | None:
    for line in output.splitlines():
        if line.startswith("score="):
            return float(line.split("=", 1)[1].strip())
    return None
