"""MicroRTS match runner adapter."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MatchResult:
    ok: bool
    score: float
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    raw_result: dict[str, Any] = field(default_factory=dict)
    player0_resource: float | None = None
    player1_resource: float | None = None
    weighted_resource_difference: float | None = None
    winner: int | None = None
    final_cycle: int | None = None


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
        raw_result = {
            "winner": 0 if mock_score >= 0 else 1,
            "ticks": tick_limit,
            "players": {
                "p0": {
                    "unit_count": 0,
                    "player_resources": 50.0 + mock_score,
                    "carried_resources": 0.0,
                    "resource_total": 50.0 + mock_score,
                    "material_total": 0.0,
                    "unit_types": {},
                },
                "p1": {
                    "unit_count": 0,
                    "player_resources": 50.0,
                    "carried_resources": 0.0,
                    "resource_total": 50.0,
                    "material_total": 0.0,
                    "unit_types": {},
                },
            },
            "final_scoreboard": {
                "p0_resources": 50.0 + mock_score,
                "p1_resources": 50.0,
                "p0_eval": 50.0 + mock_score,
                "p1_eval": 50.0,
                "units_produced": max(1, int(3 + mock_score % 5)),
                "damage_dealt": max(0.0, mock_score * 2.0),
            },
        }
        return MatchResult(
            ok=True,
            score=mock_score,
            command=command,
            stdout=f"mock match {match_index} score={mock_score}",
            raw_result=raw_result,
            **final_match_values(raw_result, fallback_score=mock_score),
        )
    completed = subprocess.run(command, cwd=microrts_dir, capture_output=True, text=True, check=False)
    raw_result = read_result_json(result_json_path)
    score = parse_score(completed.stdout)
    if score is None and raw_result:
        score = score_from_payload(raw_result)
    return MatchResult(
        ok=completed.returncode == 0 and score is not None,
        score=0.0 if score is None else score,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        raw_result=raw_result,
        **final_match_values(raw_result, fallback_score=0.0 if score is None else score),
    )


def parse_score(output: str) -> float | None:
    for line in output.splitlines():
        if line.startswith("score="):
            return float(line.split("=", 1)[1].strip())
    return None


def read_result_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def score_from_payload(payload: dict[str, Any]) -> float | None:
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


def score_from_result_json(path: Path) -> float | None:
    payload = read_result_json(path)
    if not payload:
        return None
    return score_from_payload(payload)


def final_match_values(payload: dict[str, Any], *, fallback_score: float) -> dict[str, float | int | None]:
    """Return final match values from player 0's perspective."""

    scoreboard = payload.get("final_scoreboard") or {}
    players = payload.get("players") or {}
    p0 = players.get("p0") or {}
    p1 = players.get("p1") or {}
    player0_resource = float_or_none(p0.get("resource_total"))
    player1_resource = float_or_none(p1.get("resource_total"))
    player0_material = float_or_none(p0.get("material_total"))
    player1_material = float_or_none(p1.get("material_total"))

    if player0_resource is None:
        player0_resource = float_or_none(scoreboard.get("p0_resources", scoreboard.get("p0_eval")))
    if player1_resource is None:
        player1_resource = float_or_none(scoreboard.get("p1_resources", scoreboard.get("p1_eval")))
    if player0_material is None:
        player0_material = float_or_none(scoreboard.get("p0_material", scoreboard.get("p0_eval")))
    if player1_material is None:
        player1_material = float_or_none(scoreboard.get("p1_material", scoreboard.get("p1_eval")))
    if player0_resource is None:
        player0_resource = float(fallback_score)
    if player1_resource is None:
        player1_resource = 0.0
    if player0_material is None:
        player0_material = 0.0
    if player1_material is None:
        player1_material = 0.0
    return {
        "player0_resource": player0_resource,
        "player1_resource": player1_resource,
        "weighted_resource_difference": (player0_resource + player0_material) - (player1_resource + player1_material),
        "winner": int_or_none(payload.get("winner")),
        "final_cycle": int_or_none(payload.get("final_cycle", payload.get("ticks"))),
    }


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
