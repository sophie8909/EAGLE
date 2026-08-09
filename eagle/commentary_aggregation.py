"""Deterministic candidate-level aggregation of per-match commentaries."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable


def aggregate_commentaries(match_results: Iterable[Any], commentary_results: Iterable[Any], *, candidate_id: str = "") -> dict[str, Any]:
    results = list(match_results)
    comments = {item.match_id: item for item in commentary_results}
    groups: dict[str, list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
    global_strengths: Counter[str] = Counter()
    global_weaknesses: Counter[str] = Counter()
    global_causes: Counter[str] = Counter()
    global_recommendations: Counter[str] = Counter()
    commented = 0
    failed = 0
    for result in results:
        match_id = _match_id(result)
        item = comments.get(match_id)
        commentary = None if item is None else item.commentary
        if isinstance(commentary, dict):
            commented += 1
            _count_descriptions(global_strengths, commentary.get("candidate_strengths"))
            _count_descriptions(global_weaknesses, commentary.get("candidate_weaknesses"))
            _count_descriptions(global_causes, commentary.get("decisive_causes"))
            _count_descriptions(global_recommendations, commentary.get("strategy_recommendations"), key="recommendation")
            groups[_opponent(result)].append((result, commentary))
        else:
            failed += 1
            groups[_opponent(result)]
    opponent_summaries = []
    for opponent in sorted(groups):
        rows = groups[opponent]
        strengths, weaknesses, causes, recommendations = Counter(), Counter(), Counter(), Counter()
        maps: set[str] = set()
        wins = losses = draws = 0
        p0 = {"wins": 0, "losses": 0, "draws": 0}
        p1 = {"wins": 0, "losses": 0, "draws": 0}
        representative = []
        for result, comment in rows:
            maps.add(str(getattr(result, "map_id", None) or getattr(result, "map_path", "unknown")))
            side = int(getattr(result, "candidate_player", 0))
            outcome = _outcome(result)
            if outcome == "win":
                wins += 1
                (p0 if side == 0 else p1)["wins"] += 1
            elif outcome == "loss":
                losses += 1
                (p0 if side == 0 else p1)["losses"] += 1
            else:
                draws += 1
                (p0 if side == 0 else p1)["draws"] += 1
            if comment:
                _count_descriptions(strengths, comment.get("candidate_strengths"))
                _count_descriptions(weaknesses, comment.get("candidate_weaknesses"))
                _count_descriptions(causes, comment.get("decisive_causes"))
                _count_descriptions(recommendations, comment.get("strategy_recommendations"), key="recommendation")
                representative.append({
                    "match_id": _match_id(result),
                    "map": getattr(result, "map_id", None) or getattr(result, "map_path", None),
                    "candidate_side": f"p{side}",
                    "result": outcome,
                    "decisive_causes": _compact_evidence(comment.get("decisive_causes")),
                    "turning_points": _compact_evidence(comment.get("turning_points")),
                    "recommendations": _compact_evidence(comment.get("strategy_recommendations")),
                    "tick_references": sorted(set(_ticks(comment))),
                })
        representative.sort(key=lambda item: (item["result"] != "loss", item["match_id"]))
        opponent_summaries.append({
            "opponent": opponent,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "maps": sorted(maps),
            "p0_summary": p0,
            "p1_summary": p1,
            "recurring_strengths": _ranked(strengths),
            "recurring_weaknesses": _ranked(weaknesses),
            "recurring_decisive_causes": _ranked(causes),
            "representative_matches": representative[:3],
            "priority_recommendations": _ranked(recommendations),
        })
    priority = _ranked(global_recommendations) or _ranked(global_weaknesses)
    preserve = _ranked(global_strengths)
    return {
        "schema_version": "candidate-commentary-aggregation-v1",
        "candidate_id": candidate_id,
        "match_count": len(results),
        "commented_match_count": commented,
        "failed_commentary_count": failed,
        "opponent_summaries": opponent_summaries,
        "global_strengths": _ranked(global_strengths),
        "global_weaknesses": _ranked(global_weaknesses),
        "conflicting_observations": [],
        "priority_strategy_changes": priority,
        "behaviors_to_preserve": preserve,
        "unavailable_commentary": [
            {"match_id": _match_id(result), "status": comments.get(_match_id(result)).status if comments.get(_match_id(result)) else "missing"}
            for result in results if _match_id(result) not in comments or comments[_match_id(result)].commentary is None
        ],
    }


def _count_descriptions(counter: Counter[str], values: object, *, key: str = "description") -> None:
    if not isinstance(values, list):
        return
    for value in values:
        if isinstance(value, dict):
            text = value.get(key) or value.get("description") or value.get("why_it_mattered")
        else:
            text = value
        if isinstance(text, str) and text.strip():
            counter[text.strip()] += 1


def _ranked(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"text": text, "count": count} for text, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def _compact_evidence(values: object) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values[:3]:
        if isinstance(value, dict):
            result.append({key: value[key] for key in ("rank", "description", "why_it_mattered", "evidence", "evidence_ticks", "priority", "recommendation", "supported_by_ticks", "applicable_condition") if key in value})
    return result


def _ticks(value: object) -> list[int]:
    ticks: list[int] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"tick", "evidence_ticks", "supported_by_ticks"}:
                if isinstance(item, list):
                    ticks.extend(int(v) for v in item if isinstance(v, (int, float)))
                elif isinstance(item, (int, float)):
                    ticks.append(int(item))
            else:
                ticks.extend(_ticks(item))
    elif isinstance(value, list):
        for item in value:
            ticks.extend(_ticks(item))
    return ticks


def _match_id(result: Any) -> str:
    match_dir = getattr(result, "match_dir", None)
    return str(match_dir).split("/")[-1] if match_dir else f"match_{getattr(result, 'match_index', -1):02d}"


def _opponent(result: Any) -> str:
    return str(getattr(result, "opponent_id", None) or getattr(result, "opponent_name", None) or getattr(result, "opponent", "unknown"))


def _outcome(result: Any) -> str:
    winner = getattr(result, "winner", None)
    side = getattr(result, "candidate_player", 0)
    if winner == side:
        return "win"
    if winner in (0, 1):
        return "loss"
    return "draw"
