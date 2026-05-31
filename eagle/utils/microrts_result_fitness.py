"""Shared MicroRTS result parsing for gameplay fitness values."""

from __future__ import annotations

from typing import Any


SNAPSHOT_FIELDS = (
    "resources",
    "base_count",
    "barracks_count",
    "worker_count",
    "light_count",
    "heavy_count",
    "ranged_count",
)


def microrts_result_fitness(
    result_json: dict[str, Any] | None = None,
    *,
    match_score: Any = None,
    simulation_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert one MicroRTS result payload into canonical fitness values."""
    result = result_json if isinstance(result_json, dict) else {}
    match = _match_score_dict(match_score)
    meta = simulation_meta if isinstance(simulation_meta, dict) else {}
    target_side = _target_side(result, meta)
    win_score = _win_score(result, meta, match, target_side)
    score = _resource_score(result, match, target_side)
    ally, enemy = _snapshots(result, target_side)
    return {
        "win_score": win_score,
        "raw_resource_advantage_score": score,
        "score": score,
        "result": _result_from_win_score(win_score),
        "target_side": target_side,
        "ally": ally,
        "enemy": enemy,
    }


def microrts_raw_metrics(
    result_json: dict[str, Any] | None = None,
    *,
    simulation_meta: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Return raw p0/p1 MicroRTS scoreboard and material metrics."""
    result = result_json if isinstance(result_json, dict) else {}
    meta = simulation_meta if isinstance(simulation_meta, dict) else {}
    target_side = _target_side(result, meta)
    p0, p1 = _raw_players(result, target_side)
    scoreboard = result.get("final_scoreboard") if isinstance(result.get("final_scoreboard"), dict) else {}
    p0_units = _unit_count(p0)
    p1_units = _unit_count(p1)
    p0_resources = _safe_float(_first_present(p0, "resource_total", "player_resources", "resources", "resource"))
    p1_resources = _safe_float(_first_present(p1, "resource_total", "player_resources", "resources", "resource"))
    return {
        "p0_units": p0_units,
        "p1_units": p1_units,
        "p0_eval": _safe_float(_first_present(scoreboard, "p0_eval", "p0", "0")),
        "p1_eval": _safe_float(_first_present(scoreboard, "p1_eval", "p1", "1")),
        "p0_resource_total": p0_resources,
        "p1_resource_total": p1_resources,
        "resource_total": p0_resources - p1_resources,
        "material_total": p0_units - p1_units,
    }


def normalize_player_snapshot(snapshot: Any) -> dict[str, int]:
    """Normalize one raw player snapshot to final-test raw fields."""
    if not isinstance(snapshot, dict):
        snapshot = {}
    unit_types = snapshot.get("unit_types", {}) if isinstance(snapshot.get("unit_types"), dict) else {}
    return {
        "resources": _safe_int(snapshot, "resource_total", "player_resources", "resources", "resource"),
        "base_count": _safe_int(unit_types, "Base", "base_count", "base"),
        "barracks_count": _safe_int(unit_types, "Barracks", "barracks_count", "barracks"),
        "worker_count": _safe_int(unit_types, "Worker", "worker_count", "worker"),
        "light_count": _safe_int(unit_types, "Light", "light_count", "light"),
        "heavy_count": _safe_int(unit_types, "Heavy", "heavy_count", "heavy"),
        "ranged_count": _safe_int(unit_types, "Ranged", "ranged_count", "ranged"),
    }


def _target_side(result: dict[str, Any], meta: dict[str, Any]) -> str:
    for source in (
        result,
        result.get("summary") if isinstance(result.get("summary"), dict) else {},
        meta,
        dict(meta.get("parsed_log") or {}).get("summary", {}) if isinstance(meta.get("parsed_log"), dict) else {},
    ):
        if isinstance(source, dict):
            for key in ("target_side", "eagle_side", "ally_side"):
                if source.get(key) is not None:
                    return str(source.get(key))
    # MicroRTS launches EAGLE as AI1, which is p0 unless result metadata says otherwise.
    return "0"


def _win_score(result: dict[str, Any], meta: dict[str, Any], match: dict[str, Any], target_side: str) -> float:
    if result.get("win_score") is not None:
        return _safe_float(result.get("win_score"))
    result_label = str(result.get("result") or "").strip().lower()
    if result_label == "win":
        return 1.0
    if result_label == "loss":
        return -1.0
    if result_label == "draw":
        return 0.0
    if "win" in result:
        return 1.0 if bool(result.get("win")) else -1.0
    winner = result.get("winner")
    if winner is None:
        summary = dict(meta.get("parsed_log") or {}).get("summary", {}) if isinstance(meta.get("parsed_log"), dict) else {}
        winner = summary.get("winner") if isinstance(summary, dict) else None
    winner_text = str(winner).strip().lower()
    if winner is not None and winner_text not in {"", "-1", "none", "null", "draw"}:
        return 1.0 if str(winner) == str(target_side) else -1.0
    if match.get("win_score") is not None:
        return _safe_float(match.get("win_score"))
    if winner is None or winner_text in {"", "-1", "none", "null", "draw"}:
        return 0.0
    return 0.0


def _resource_score(result: dict[str, Any], match: dict[str, Any], target_side: str) -> float:
    scoreboard = result.get("final_scoreboard")
    if isinstance(scoreboard, dict):
        p0_eval = _first_float(scoreboard, "p0_eval", "p0", "0")
        p1_eval = _first_float(scoreboard, "p1_eval", "p1", "1")
        if p0_eval is not None and p1_eval is not None:
            return p1_eval - p0_eval if target_side == "1" else p0_eval - p1_eval
    for key in ("raw_resource_advantage_score", "score", "resource_advantage_score"):
        if match.get(key) is not None:
            return _safe_float(match.get(key))
    return 0.0


def _snapshots(result: dict[str, Any], target_side: str) -> tuple[dict[str, int], dict[str, int]]:
    players = result.get("players")
    if isinstance(players, dict):
        p0 = players.get("p0") or {}
        p1 = players.get("p1") or {}
        if target_side == "1":
            return normalize_player_snapshot(p1), normalize_player_snapshot(p0)
        return normalize_player_snapshot(p0), normalize_player_snapshot(p1)
    return normalize_player_snapshot(result.get("ally")), normalize_player_snapshot(result.get("enemy"))


def _raw_players(result: dict[str, Any], target_side: str) -> tuple[dict[str, Any], dict[str, Any]]:
    players = result.get("players")
    if isinstance(players, dict):
        return dict(players.get("p0") or {}), dict(players.get("p1") or {})
    ally = result.get("ally") if isinstance(result.get("ally"), dict) else {}
    enemy = result.get("enemy") if isinstance(result.get("enemy"), dict) else {}
    if target_side == "1":
        return dict(enemy), dict(ally)
    return dict(ally), dict(enemy)


def _unit_count(snapshot: dict[str, Any]) -> float:
    unit_types = snapshot.get("unit_types") if isinstance(snapshot.get("unit_types"), dict) else snapshot
    return sum(
        _safe_float(_first_present(unit_types, java_name, field_name))
        for java_name, field_name in (
            ("Base", "base_count"),
            ("Barracks", "barracks_count"),
            ("Worker", "worker_count"),
            ("Light", "light_count"),
            ("Heavy", "heavy_count"),
            ("Ranged", "ranged_count"),
        )
    )


def _match_score_dict(match_score: Any) -> dict[str, Any]:
    if isinstance(match_score, dict):
        return match_score
    if isinstance(match_score, (list, tuple)):
        return {
            "win_score": match_score[0] if len(match_score) > 0 else 0.0,
            "raw_resource_advantage_score": match_score[1] if len(match_score) > 1 else 0.0,
        }
    return {}


def _result_from_win_score(win_score: float) -> str:
    if win_score == 1.0:
        return "Win"
    if win_score == -1.0:
        return "Loss"
    return "Draw"


def _first_float(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in mapping:
            return _safe_float(mapping.get(key))
    return None


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if isinstance(mapping, dict) and key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return 0.0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(mapping: dict[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            value = mapping.get(key)
            if value is not None:
                return int(value)
        except (TypeError, ValueError, AttributeError):
            continue
    return 0
