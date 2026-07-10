"""MicroRTS match runner adapter."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .game_performance import (
    GamePerformanceBreakdown,
    GamePerformanceConfig,
    MatchTelemetry,
    build_match_telemetry,
    telemetry_summary,
    write_summary_json,
    write_telemetry_json,
)


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
    telemetry: MatchTelemetry | None = None
    performance_breakdown: GamePerformanceBreakdown | None = None
    replay_path: str | None = None
    telemetry_path: str | None = None
    summary_path: str | None = None
    persistence_error: str | None = None


def run_microrts_match(
    *,
    microrts_dir: Path,
    classes_dir: Path,
    agent_class: str,
    opponent: str,
    tick_limit: int,
    match_index: int,
    match_artifacts_dir: Path | None = None,
    scoring_config: GamePerformanceConfig | None = None,
    mock: bool = False,
    mock_score: float = 0.0,
) -> MatchResult:
    microrts_dir = microrts_dir.resolve()
    classes_dir = classes_dir.resolve()
    scoring_config = scoring_config or GamePerformanceConfig()
    map_path = "maps/8x8/basesWorkers8x8.xml"
    match_dir = match_directory(
        match_artifacts_dir or classes_dir,
        match_index=match_index,
        opponent=opponent,
        map_path=map_path,
        seed=None,
    )
    result_json_path = match_dir / "result.json"
    replay_path = match_dir / "replay.xml"
    round_state_dir = match_dir / "round_states"
    telemetry_path = match_dir / "telemetry.json"
    summary_path = match_dir / "summary.json"
    command = [
        "java",
        f"-Dmicrorts.trace.path={replay_path}",
        f"-Dmicrorts.round_state_dir={round_state_dir}",
        "-cp",
        os.pathsep.join([str(classes_dir), str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")]),
        "rts.MicroRTS",
        "-l",
        "STANDALONE",
        "--headless",
        "true",
        "-m",
        map_path,
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
        match_dir.mkdir(parents=True, exist_ok=True)
        raw_result = {
            "winner": 0 if mock_score >= 0 else 1,
            "final_tick": tick_limit,
            "max_cycles": tick_limit,
            "result": "p0_win" if mock_score >= 0 else "p1_win",
            "tick_timeout": False,
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
        write_mock_round_state(round_state_dir, tick=0, p0_resource=50.0, p1_resource=50.0)
        write_mock_round_state(round_state_dir, tick=tick_limit, p0_resource=50.0 + mock_score, p1_resource=50.0)
        replay_path.write_text("<mock-replay />\n", encoding="utf-8")
        telemetry, _, persistence_error = persist_match_artifacts(
            raw_result=raw_result,
            round_state_dir=round_state_dir,
            replay_path=replay_path,
            telemetry_path=telemetry_path,
            summary_path=summary_path,
            match_dir=match_dir,
            tick_limit=tick_limit,
            scoring_config=scoring_config,
        )
        score = telemetry.performance.total_performance if telemetry.performance is not None else mock_score
        return MatchResult(
            ok=True,
            score=score,
            command=command,
            stdout=f"mock match {match_index} score={mock_score}",
            raw_result=raw_result,
            telemetry=telemetry,
            performance_breakdown=telemetry.performance,
            replay_path=relative_or_absolute(replay_path, match_dir.parent.parent),
            telemetry_path=relative_or_absolute(telemetry_path, match_dir.parent.parent),
            summary_path=relative_or_absolute(summary_path, match_dir.parent.parent),
            persistence_error=persistence_error,
            **final_match_values(raw_result, fallback_score=mock_score),
        )
    match_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=microrts_dir, capture_output=True, text=True, check=False)
    raw_result = read_result_json(result_json_path)
    score = parse_score(completed.stdout)
    if score is None and raw_result:
        score = score_from_payload(raw_result)
    telemetry: MatchTelemetry | None = None
    persistence_error: str | None = None
    if raw_result:
        telemetry, _, persistence_error = persist_match_artifacts(
            raw_result=raw_result,
            round_state_dir=round_state_dir,
            replay_path=replay_path,
            telemetry_path=telemetry_path,
            summary_path=summary_path,
            match_dir=match_dir,
            tick_limit=tick_limit,
            scoring_config=scoring_config,
        )
        if telemetry.performance is not None:
            score = telemetry.performance.total_performance
    return MatchResult(
        ok=completed.returncode == 0 and score is not None,
        score=0.0 if score is None else score,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        raw_result=raw_result,
        telemetry=telemetry,
        performance_breakdown=None if telemetry is None else telemetry.performance,
        replay_path=None if not replay_path.exists() else relative_or_absolute(replay_path, match_dir.parent.parent),
        telemetry_path=None if telemetry is None else relative_or_absolute(telemetry_path, match_dir.parent.parent),
        summary_path=None if telemetry is None else relative_or_absolute(summary_path, match_dir.parent.parent),
        persistence_error=persistence_error,
        **final_match_values(raw_result, fallback_score=0.0 if score is None else score),
    )


def match_directory(
    root: Path,
    *,
    match_index: int,
    opponent: str,
    map_path: str,
    seed: int | None,
) -> Path:
    seed_label = "none" if seed is None else str(seed)
    match_id = f"match_{match_index:03d}_p0_vs_{safe_path_part(opponent)}_{safe_path_part(map_path)}_seed_{seed_label}"
    return root / match_id


def persist_match_artifacts(
    *,
    raw_result: dict[str, Any],
    round_state_dir: Path,
    replay_path: Path,
    telemetry_path: Path,
    summary_path: Path,
    match_dir: Path,
    tick_limit: int,
    scoring_config: GamePerformanceConfig,
) -> tuple[MatchTelemetry, dict[str, Any], str | None]:
    telemetry = build_match_telemetry(
        raw_result=raw_result,
        round_state_dir=round_state_dir,
        max_tick=tick_limit,
        player_index=0,
        opponent_index=1,
        replay_path=relative_or_absolute(replay_path, match_dir),
        scoring_config=scoring_config,
    )
    summary = telemetry_summary(
        telemetry,
        telemetry_path=relative_or_absolute(telemetry_path, match_dir),
        summary_path=relative_or_absolute(summary_path, match_dir),
    )
    try:
        write_telemetry_json(telemetry_path, telemetry)
        write_summary_json(summary_path, summary)
    except OSError as exc:
        return telemetry, summary, f"failed to persist match artifacts: {exc}"
    return telemetry, summary, None


def write_mock_round_state(round_state_dir: Path, *, tick: int, p0_resource: float, p1_resource: float) -> None:
    round_state_dir.mkdir(parents=True, exist_ok=True)
    (round_state_dir / f"round_{tick:06d}.log").write_text(
        "\n".join(
            [
                f"ROUND_TICK: {tick}",
                "GAMEOVER: false",
                f"current time {tick} p0 player 0({p0_resource}) p1 player 1({p1_resource})",
                "=== Dynamic Prompt ===",
                "Map size: 8x8",
                f"Turn: {tick}",
                "Feature locations:",
                "(1,1) Ally Base Unit {HP=10, resources=0}",
                "(6,6) Enemy Base Unit {HP=10, resources=0}",
                "======================",
                "",
            ]
        ),
        encoding="utf-8",
    )


def safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_") or "value"


def relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


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
