"""Canonical post-integration MicroRTS match execution.

This module owns one bounded process invocation and one lossless artifact directory
per match.  It is re-exported by :mod:`evaluation.microrts_runner` so the
standalone Phase 3 integration adapter remains unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .game_performance import (
    GamePerformanceBreakdown,
    GamePerformanceConfig,
    MatchTelemetry,
    build_match_telemetry,
    write_summary_json,
    write_telemetry_json,
)


DEFAULT_MAP_PATH = "maps/8x8/basesWorkers8x8.xml"
RUNTIME_FAILURE_CATEGORIES = {
    "runtime_exception",
    "illegal_action",
    "timeout",
    "deadlock",
    "crash",
    "invalid_match_result",
    "partial_evaluation",
    "missing_result",
}


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
    round_state_path: str | None = None
    telemetry_path: str | None = None
    summary_path: str | None = None
    persistence_error: str | None = None
    candidate_id: str | None = None
    match_index: int = -1
    candidate_player: int = 0
    opponent: str = "ai.abstraction.LightRush"
    map_path: str = DEFAULT_MAP_PATH
    seed: int | None = None
    max_cycles: int = 0
    source_hash: str | None = None
    class_hash: str | None = None
    status: str = "success"
    failure_category: str | None = None
    failure_reason: str | None = None
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    timeout_seconds: float | None = None
    match_dir: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        telemetry = self.telemetry
        material_trace = []
        if telemetry is not None:
            material_trace = [
                {
                    "tick": item.tick,
                    "player_material": item.player_total_unit_value,
                    "enemy_material": item.enemy_total_unit_value,
                }
                for item in telemetry.ticks
            ]
        return {
            "candidate_id": self.candidate_id,
            "match_index": self.match_index,
            "candidate_player": self.candidate_player,
            "opponent": self.opponent,
            "map": self.map_path,
            "seed": self.seed,
            "max_cycles": self.max_cycles,
            "source_hash": self.source_hash,
            "class_hash": self.class_hash,
            "status": self.status,
            "ok": self.ok,
            "failure_category": self.failure_category,
            "failure_reason": self.failure_reason,
            "winner": self.winner,
            "result": self.raw_result.get("result"),
            "final_tick": self.final_cycle,
            "player_final_resources": self.player0_resource,
            "enemy_final_resources": self.player1_resource,
            "final_resource_difference": (
                None
                if self.player0_resource is None or self.player1_resource is None
                else self.player0_resource - self.player1_resource
            ),
            "unit_material_trace": material_trace,
            "survival": None if self.performance_breakdown is None else self.performance_breakdown.survival_score,
            "telemetry": None if telemetry is None else telemetry.to_json_dict(),
            "performance_breakdown": (
                None if self.performance_breakdown is None else self.performance_breakdown.to_json_dict()
            ),
            "score": self.score,
            "return_code": self.returncode,
            "duration_seconds": self.duration_seconds,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": self.command,
            "replay_path": self.replay_path,
            "round_state_path": self.round_state_path,
            "telemetry_path": self.telemetry_path,
            "performance_breakdown_path": self.summary_path,
            "persistence_error": self.persistence_error,
            "timing": {
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_seconds": self.duration_seconds,
                "process_started_at": self.started_at,
                "process_finished_at": self.finished_at,
                "timeout_seconds": self.timeout_seconds,
                "status": self.status,
            },
        }


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
    seed: int | None = None,
    timeout_seconds: float = 120.0,
    map_path: str = DEFAULT_MAP_PATH,
    candidate_id: str | None = None,
    source_hash: str | None = None,
    class_hash: str | None = None,
    candidate_player: int = 0,
    extra_classpath_entries: Iterable[Path] = (),
    match_output_dir: Path | None = None,
) -> MatchResult:
    """Run one bounded match and persist its independent evidence immediately."""

    microrts_dir = microrts_dir.resolve()
    classes_dir = classes_dir.resolve()
    scoring_config = scoring_config or GamePerformanceConfig()
    root = (match_artifacts_dir or classes_dir).resolve()
    match_dir = (match_output_dir or match_directory(root, match_index=match_index)).resolve()
    match_dir.mkdir(parents=True, exist_ok=True)
    if candidate_player not in {0, 1}:
        raise ValueError("candidate_player must be 0 or 1.")
    round_state_dir = match_dir / "round_states"
    round_state_dir.mkdir(exist_ok=True)
    raw_result_path = match_dir / "raw_result.json"
    replay_path = match_dir / "replay.xml"
    telemetry_path = match_dir / "telemetry.json"
    breakdown_path = match_dir / "performance_breakdown.json"
    seed_value = match_index if seed is None else int(seed)
    additional_classpath = [str(Path(value).resolve()) for value in extra_classpath_entries]
    classpath = os.pathsep.join(
        [str(classes_dir), *additional_classpath, str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")]
    )
    ai1 = agent_class if candidate_player == 0 else opponent
    ai2 = opponent if candidate_player == 0 else agent_class
    command = [
        "java",
        f"-Deagle.match.seed={seed_value}",
        f"-Dmicrorts.trace.path={replay_path}",
        f"-Dmicrorts.round_state_dir={round_state_dir}",
        "-cp",
        classpath,
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
        ai1,
        "--ai2",
        ai2,
        "--result-json",
        str(raw_result_path),
    ]
    started_at = _utc_now()
    started = time.monotonic()

    if mock:
        raw_result = _mock_result(
            score=mock_score,
            tick_limit=tick_limit,
            ai1=ai1,
            ai2=ai2,
            candidate_player=candidate_player,
            seed=seed_value,
        )
        raw_result_path.write_text(json.dumps(raw_result, indent=2), encoding="utf-8")
        write_mock_round_state(round_state_dir, tick=0, p0_resource=50.0, p1_resource=50.0)
        write_mock_round_state(
            round_state_dir,
            tick=tick_limit,
            p0_resource=50.0 + (mock_score if candidate_player == 0 else 0.0),
            p1_resource=50.0 + (mock_score if candidate_player == 1 else 0.0),
        )
        replay_path.write_text("<mock-replay />\n", encoding="utf-8")
        return _finish_match(
            raw_result=raw_result,
            command=command,
            stdout=f"mock match {match_index} seed={seed_value} score={mock_score}",
            stderr="",
            returncode=0,
            started_at=started_at,
            started=started,
            timeout_seconds=timeout_seconds,
            match_dir=match_dir,
            round_state_dir=round_state_dir,
            replay_path=replay_path,
            telemetry_path=telemetry_path,
            breakdown_path=breakdown_path,
            scoring_config=scoring_config,
            candidate_id=candidate_id,
            match_index=match_index,
            opponent=opponent,
            candidate_player=candidate_player,
            map_path=map_path,
            seed=seed_value,
            tick_limit=tick_limit,
            agent_class=agent_class,
            source_hash=source_hash,
            class_hash=class_hash,
        )

    try:
        completed = subprocess.run(
            command,
            cwd=microrts_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return _finish_match(
            raw_result={},
            command=command,
            stdout=_text_output(exc.stdout),
            stderr=_text_output(exc.stderr),
            returncode=124,
            started_at=started_at,
            started=started,
            timeout_seconds=timeout_seconds,
            match_dir=match_dir,
            round_state_dir=round_state_dir,
            replay_path=replay_path,
            telemetry_path=telemetry_path,
            breakdown_path=breakdown_path,
            scoring_config=scoring_config,
            candidate_id=candidate_id,
            match_index=match_index,
            opponent=opponent,
            candidate_player=candidate_player,
            map_path=map_path,
            seed=seed_value,
            tick_limit=tick_limit,
            agent_class=agent_class,
            source_hash=source_hash,
            class_hash=class_hash,
            forced_failure=("timeout", f"match exceeded {timeout_seconds:g} second timeout"),
        )

    return _finish_match(
        raw_result=read_result_json(raw_result_path),
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        started_at=started_at,
        started=started,
        timeout_seconds=timeout_seconds,
        match_dir=match_dir,
        round_state_dir=round_state_dir,
        replay_path=replay_path,
        telemetry_path=telemetry_path,
        breakdown_path=breakdown_path,
        scoring_config=scoring_config,
        candidate_id=candidate_id,
        match_index=match_index,
        opponent=opponent,
        candidate_player=candidate_player,
        map_path=map_path,
        seed=seed_value,
        tick_limit=tick_limit,
        agent_class=agent_class,
        source_hash=source_hash,
        class_hash=class_hash,
    )


def _finish_match(
    *,
    raw_result: dict[str, Any],
    command: list[str],
    stdout: str,
    stderr: str,
    returncode: int,
    started_at: str,
    started: float,
    timeout_seconds: float,
    match_dir: Path,
    round_state_dir: Path,
    replay_path: Path,
    telemetry_path: Path,
    breakdown_path: Path,
    scoring_config: GamePerformanceConfig,
    candidate_id: str | None,
    match_index: int,
    opponent: str,
    candidate_player: int,
    map_path: str,
    seed: int,
    tick_limit: int,
    agent_class: str,
    source_hash: str | None,
    class_hash: str | None,
    forced_failure: tuple[str, str] | None = None,
) -> MatchResult:
    failure = forced_failure or classify_runtime_failure(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        raw_result=raw_result,
        tick_limit=tick_limit,
        agent_class=agent_class,
        opponent=opponent,
        candidate_player=candidate_player,
    )
    telemetry: MatchTelemetry | None = None
    persistence_error: str | None = None
    if failure is None:
        try:
            telemetry = build_match_telemetry(
                raw_result=raw_result,
                round_state_dir=round_state_dir,
                max_tick=tick_limit,
                player_index=candidate_player,
                opponent_index=1 - candidate_player,
                replay_path=str(replay_path.name),
                scoring_config=scoring_config,
            )
            write_telemetry_json(telemetry_path, telemetry)
            write_summary_json(
                breakdown_path,
                {} if telemetry.performance is None else telemetry.performance.to_json_dict(),
            )
        except (OSError, TypeError, ValueError) as exc:
            failure = ("invalid_match_result", f"telemetry construction failed: {exc}")
    if telemetry is None:
        try:
            write_summary_json(telemetry_path, {})
            write_summary_json(breakdown_path, {})
        except OSError as exc:
            persistence_error = f"failed to persist match telemetry: {exc}"

    values = final_match_values(raw_result, candidate_player=candidate_player)
    performance = None if telemetry is None else telemetry.performance
    score = 0.0 if performance is None else performance.total_performance
    duration = max(0.0, time.monotonic() - started)
    finished_at = _utc_now()
    category = None if failure is None else failure[0]
    reason = None if failure is None else failure[1]
    result = MatchResult(
        ok=failure is None,
        score=score,
        command=command,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        raw_result=raw_result,
        telemetry=telemetry,
        performance_breakdown=performance,
        replay_path=str(replay_path) if replay_path.exists() else None,
        round_state_path=str(round_state_dir) if round_state_dir.exists() else None,
        telemetry_path=str(telemetry_path),
        summary_path=str(breakdown_path),
        persistence_error=persistence_error,
        candidate_id=candidate_id,
        match_index=match_index,
        candidate_player=candidate_player,
        opponent=opponent,
        map_path=map_path,
        seed=seed,
        max_cycles=tick_limit,
        source_hash=source_hash,
        class_hash=class_hash,
        status="success" if failure is None else "failed",
        failure_category=category,
        failure_reason=reason,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        timeout_seconds=timeout_seconds,
        match_dir=str(match_dir),
        **values,
    )
    _persist_result(match_dir, result)
    return result


def classify_runtime_failure(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    raw_result: dict[str, Any],
    tick_limit: int,
    agent_class: str,
    opponent: str,
    candidate_player: int = 0,
) -> tuple[str, str] | None:
    combined = f"{stdout}\n{stderr}".lower()
    if returncode != 0:
        if "illegal action" in combined:
            return "illegal_action", _first_diagnostic(stdout, stderr, "MicroRTS rejected an illegal action.")
        if "deadlock" in combined:
            return "deadlock", _first_diagnostic(stdout, stderr, "MicroRTS match deadlocked.")
        if "exception" in combined or "error" in combined:
            return "runtime_exception", _first_diagnostic(stdout, stderr, "Candidate raised a runtime exception.")
        return "crash", _first_diagnostic(stdout, stderr, f"match process exited with code {returncode}")
    if not raw_result:
        return "missing_result", "match process completed without a result payload"
    validation_error = validate_match_result(
        raw_result,
        tick_limit=tick_limit,
        agent_class=agent_class,
        opponent=opponent,
        candidate_player=candidate_player,
    )
    if validation_error:
        return "invalid_match_result", validation_error
    return None


def validate_match_result(
    payload: dict[str, Any],
    *,
    tick_limit: int,
    agent_class: str,
    opponent: str,
    candidate_player: int = 0,
) -> str | None:
    required = ("winner", "result", "final_tick", "max_cycles", "players")
    missing = [name for name in required if name not in payload]
    if missing:
        return f"result payload is missing required fields: {', '.join(missing)}"
    winner = int_or_none(payload.get("winner"))
    if winner not in {-1, 0, 1}:
        return f"winner must be -1, 0, or 1; got {payload.get('winner')!r}"
    expected_result = "p0_win" if winner == 0 else "p1_win" if winner == 1 else (
        "timeout_draw" if bool(payload.get("tick_timeout")) else "draw"
    )
    if payload.get("result") != expected_result:
        return f"result {payload.get('result')!r} is inconsistent with winner {winner}"
    final_tick = int_or_none(payload.get("final_tick"))
    max_cycles = int_or_none(payload.get("max_cycles"))
    if final_tick is None or final_tick < 0 or final_tick > tick_limit:
        return f"final_tick must be in [0, {tick_limit}]"
    if max_cycles != tick_limit:
        return f"max_cycles must equal configured tick limit {tick_limit}"
    if candidate_player not in {0, 1}:
        return "candidate_player must be 0 or 1"
    expected_ai1 = agent_class if candidate_player == 0 else opponent
    expected_ai2 = opponent if candidate_player == 0 else agent_class
    if payload.get("ai1") not in (None, expected_ai1):
        return "result player 0 identity does not match the configured match"
    if payload.get("ai2") not in (None, expected_ai2):
        return "result player 1 identity does not match the configured match"
    players = payload.get("players")
    if not isinstance(players, dict):
        return "players must be an object"
    for side in ("p0", "p1"):
        player = players.get(side)
        if not isinstance(player, dict):
            return f"players.{side} must be an object"
        for name in ("resource_total", "material_total", "unit_types"):
            if name not in player:
                return f"players.{side}.{name} is required"
        if float_or_none(player.get("resource_total")) is None:
            return f"players.{side}.resource_total must be numeric"
        if float_or_none(player.get("material_total")) is None:
            return f"players.{side}.material_total must be numeric"
        if not isinstance(player.get("unit_types"), dict):
            return f"players.{side}.unit_types must be an object"
    return None


def _persist_result(match_dir: Path, result: MatchResult) -> None:
    try:
        (match_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (match_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        (match_dir / "result.json").write_text(
            json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        timing = result.to_json_dict()["timing"]
        (match_dir / "timing.json").write_text(json.dumps(timing, indent=2), encoding="utf-8")
    except OSError:
        # The caller receives the process/result evidence even if the filesystem fails.
        return


def _mock_result(*, score: float, tick_limit: int, ai1: str, ai2: str, candidate_player: int, seed: int) -> dict[str, Any]:
    winner = candidate_player if score >= 0 else 1 - candidate_player
    return {
        "gameover": True,
        "winner": winner,
        "result": "p0_win" if winner == 0 else "p1_win",
        "target_side": 0,
        "final_tick": tick_limit,
        "max_cycles": tick_limit,
        "tick_timeout": False,
        "termination_reason": "gameover",
        "ai1": ai1,
        "ai2": ai2,
        "match_seed": seed,
        "players": {
            "p0": {
                "unit_count": 1,
                "player_resources": 50.0 + (score if candidate_player == 0 else 0.0),
                "carried_resources": 0.0,
                "resource_total": 50.0 + (score if candidate_player == 0 else 0.0),
                "material_total": 10.0,
                "unit_types": {"Base": 1},
            },
            "p1": {
                "unit_count": 1,
                "player_resources": 50.0 + (score if candidate_player == 1 else 0.0),
                "carried_resources": 0.0,
                "resource_total": 50.0 + (score if candidate_player == 1 else 0.0),
                "material_total": 10.0,
                "unit_types": {"Base": 1},
            },
        },
        "final_scoreboard": {
            "p0_resources": 50.0 + (score if candidate_player == 0 else 0.0),
            "p1_resources": 50.0 + (score if candidate_player == 1 else 0.0),
            "p0_eval": 10.0,
            "p1_eval": 10.0,
        },
    }


def match_directory(root: Path, *, match_index: int, **_: Any) -> Path:
    return root / f"match_{match_index:02d}"


def write_mock_round_state(
    round_state_dir: Path,
    *,
    tick: int,
    p0_resource: float,
    p1_resource: float,
) -> None:
    round_state_dir.mkdir(parents=True, exist_ok=True)
    (round_state_dir / f"round_{tick:06d}.log").write_text(
        "\n".join(
            [
                f"ROUND_TICK: {tick}",
                "GAMEOVER: false",
                f"current time {tick} p0 player 0({p0_resource}) p1 player 1({p1_resource})",
                "(1,1) Ally Base Unit {HP=10, resources=0}",
                "(6,6) Enemy Base Unit {HP=10, resources=0}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def read_result_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def final_match_values(payload: dict[str, Any], *, candidate_player: int = 0) -> dict[str, float | int | None]:
    players = payload.get("players") if isinstance(payload.get("players"), dict) else {}
    p0 = players.get("p0") if isinstance(players.get("p0"), dict) else {}
    p1 = players.get("p1") if isinstance(players.get("p1"), dict) else {}
    candidate = p0 if candidate_player == 0 else p1
    opponent = p1 if candidate_player == 0 else p0
    p0_resource = float_or_none(candidate.get("resource_total"))
    p1_resource = float_or_none(opponent.get("resource_total"))
    p0_material = float_or_none(candidate.get("material_total"))
    p1_material = float_or_none(opponent.get("material_total"))
    return {
        "player0_resource": p0_resource,
        "player1_resource": p1_resource,
        "weighted_resource_difference": (
            None
            if None in (p0_resource, p1_resource, p0_material, p1_material)
            else (p0_resource + p0_material) - (p1_resource + p1_material)
        ),
        "winner": int_or_none(payload.get("winner")),
        "final_cycle": int_or_none(payload.get("final_tick")),
    }


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_class_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(file_path.relative_to(path).as_posix().encode("utf-8"))
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


def _first_diagnostic(stdout: str, stderr: str, fallback: str) -> str:
    text = (stderr or stdout).strip()
    return text.splitlines()[0] if text else fallback


def _text_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
