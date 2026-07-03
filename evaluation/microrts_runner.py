"""MicroRTS match runner adapter."""

from __future__ import annotations

import json
import os
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
    result_json_path = classes_dir / f"match_{match_index}.json"
    command = [
        "java",
        "-cp",
        os.pathsep.join([str(classes_dir), str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")]),
        "rts.MicroRTS",
        "-l",
        "STANDALONE",
        "--headless",
        "true",
        "-m",
        "maps/8x8/basesWorkers8x8.xml",
        "-c",
        str(tick_limit),
        "-i",
        "0",
        "--ai1",
        agent_class,
        "--ai2",
        opponent,
        "--result-json",
        str(result_json_path),
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
    if score is None and result_json_path.exists():
        score = score_from_result_json(result_json_path)
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


def score_from_result_json(path: Path) -> float | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    winner = payload.get("winner")
    if winner == 0:
        return 1.0
    if winner == 1:
        return -1.0

    scoreboard = payload.get("final_scoreboard") or {}
    try:
        p0_eval = float(scoreboard.get("p0_eval", 0.0))
        p1_eval = float(scoreboard.get("p1_eval", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return (p0_eval - p1_eval) / max(1.0, p0_eval + p1_eval)
