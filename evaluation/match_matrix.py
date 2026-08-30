"""Deterministic map/round/player-side evaluation matrix construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class EvaluationMap:
    map_id: str
    path: str


@dataclass(frozen=True)
class MatrixOpponent:
    opponent_id: str
    weight: float = 1.0


@dataclass(frozen=True)
class MatchSpecification:
    match_index: int
    opponent_id: str
    opponent_weight: float
    map_id: str
    map_path: str
    round_index: int
    candidate_player: int
    opponent_player: int


def build_match_matrix(
    opponents: Iterable[MatrixOpponent],
    maps: Iterable[EvaluationMap],
    *,
    rounds_per_map: int = 3,
    swap_player_sides: bool = True,
) -> tuple[MatchSpecification, ...]:
    """Build map-major, round-major, side-paired specifications.

    The ordering is deterministic: all rounds and both sides for one map and
    opponent are emitted before moving to the next map/opponent.
    """

    maps = tuple(maps)
    opponents = tuple(opponents)
    if len(maps) != 3:
        raise ValueError("evaluation requires exactly three maps")
    if rounds_per_map != 3:
        raise ValueError("evaluation requires exactly three rounds per map")
    if not swap_player_sides:
        raise ValueError("evaluation requires candidate/opponent side swapping")
    specifications: list[MatchSpecification] = []
    match_index = 0
    for opponent in opponents:
        for evaluation_map in maps:
            for round_index in range(rounds_per_map):
                for candidate_player in (0, 1):
                    specifications.append(
                        MatchSpecification(
                            match_index=match_index,
                            opponent_id=opponent.opponent_id,
                            opponent_weight=opponent.weight,
                            map_id=evaluation_map.map_id,
                            map_path=evaluation_map.path,
                            round_index=round_index,
                            candidate_player=candidate_player,
                            opponent_player=1 - candidate_player,
                        )
                    )
                    match_index += 1
    return tuple(specifications)


def canonical_evaluation_maps(paths: Iterable[str]) -> tuple[EvaluationMap, ...]:
    paths = tuple(str(path) for path in paths)
    if len(paths) != 3:
        raise ValueError("evaluation requires exactly three maps")
    return tuple(EvaluationMap(f"map_{index}", path) for index, path in enumerate(paths, start=1))
