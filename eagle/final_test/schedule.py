"""Deterministic champion/map/side/seed scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import FinalTestConfig
from .selection import SelectedCandidate


@dataclass(frozen=True)
class FinalTestMatch:
    match_index: int
    candidate_id: str
    opponent_id: str
    map_id: str
    map_path: str
    max_cycles: int
    candidate_player: int
    seed: int

    @property
    def artifact_relative_path(self) -> Path:
        return (
            Path("matches")
            / self.candidate_id
            / self.opponent_id
            / self.map_id
            / f"player_{self.candidate_player}"
            / f"seed_{self.seed}"
        )


def build_schedule(
    candidates: tuple[SelectedCandidate, ...],
    config: FinalTestConfig,
) -> tuple[FinalTestMatch, ...]:
    """Build one stable Cartesian product; every candidate plays both sides."""

    schedule: list[FinalTestMatch] = []
    for candidate in candidates:
        for opponent_id in config.opponent_ids:
            for map_config in config.maps:
                for side in config.player_sides:
                    for seed in config.seeds:
                        schedule.append(
                            FinalTestMatch(
                                match_index=len(schedule),
                                candidate_id=candidate.candidate_id,
                                opponent_id=opponent_id,
                                map_id=map_config.map_id,
                                map_path=map_config.path,
                                max_cycles=map_config.max_cycles,
                                candidate_player=side,
                                seed=seed,
                            )
                        )
    expected = exact_match_count(len(candidates), config)
    if len(schedule) != expected:
        raise AssertionError(f"Schedule contains {len(schedule)} matches; expected {expected}.")
    return tuple(schedule)


def exact_match_count(candidate_count: int, config: FinalTestConfig) -> int:
    return (
        candidate_count
        * len(config.opponent_ids)
        * len(config.maps)
        * len(config.player_sides)
        * config.matches_per_opponent_map_side
    )

