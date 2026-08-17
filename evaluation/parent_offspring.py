"""Direct parent-vs-offspring MicroRTS evaluation for AOS credit only."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eagle.candidate import Candidate
from evaluation.game_performance import GamePerformanceConfig
from evaluation.match_matrix import MatrixOpponent, build_match_matrix, canonical_evaluation_maps
from evaluation.microrts_runner import MatchResult, hash_class_directory, hash_file, run_microrts_match


COMPARISON_PARENT_CLASS = "ai.eagle.ComparisonParentAgent"
PARENT_CLASSES_PROPERTY = "eagle.comparison.parent.classes"


@dataclass(frozen=True)
class ParentOffspringResult:
    """Compact AOS-owned summary; detailed matches remain match-owned."""

    offspring_id: str
    comparison_parent_id: str
    maps: tuple[str, ...]
    rounds: tuple[int, ...]
    sides: tuple[str, ...]
    total_matches: int
    wins: int
    draws: int
    losses: int
    errors: int
    valid_matches: int
    reward: float
    match_artifact_root: str | None = None
    offspring_source_hash: str | None = None
    offspring_class_hash: str | None = None
    comparison_parent_class_hash: str | None = None
    matches: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "maps": list(self.maps),
            "rounds": list(self.rounds),
            "sides": list(self.sides),
            "total_matches": self.total_matches,
            "valid_matches": self.valid_matches,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "errors": self.errors,
            "match_artifact_root": self.match_artifact_root,
            "offspring_source_hash": self.offspring_source_hash,
            "offspring_class_hash": self.offspring_class_hash,
            "comparison_parent_class_hash": self.comparison_parent_class_hash,
            "matches": [dict(item) for item in self.matches],
        }


def head_to_head_reward(*, wins: int, draws: int, losses: int) -> float:
    """Return offspring match points in ``[0, 1]`` over valid games."""

    for name, value in (("wins", wins), ("draws", draws), ("losses", losses)):
        if value < 0:
            raise ValueError(f"{name} must not be negative")
    valid = wins + draws + losses
    return 0.0 if valid == 0 else (wins + 0.5 * draws) / valid


def evaluate_parent_vs_offspring(
    offspring: Candidate,
    comparison_parent: Candidate,
    *,
    config: Any,
    classes_dir: Path,
    match_artifacts_dir: Path,
    mock: bool,
) -> ParentOffspringResult:
    """Run the configured maps/rounds/sides with the offspring as both p0 and p1.

    Both candidate class directories are reused. ``ComparisonParentAgent``
    isolates the parent's existing ``ai.generated.CandidateAgent`` bytecode so
    both same-named generated classes can coexist in one MicroRTS process.
    """

    offspring_classes = classes_dir / offspring.id
    parent_classes = classes_dir / comparison_parent.id
    specifications = build_match_matrix(
        (MatrixOpponent(comparison_parent.id),),
        canonical_evaluation_maps(config.evaluation_maps),
        rounds_per_map=config.rounds_per_map,
        swap_player_sides=config.swap_player_sides,
        round_seeds=config.resolved_match_seeds,
    )
    source_path = Path(offspring.generated_java_path) if offspring.generated_java_path else None
    source_hash = hash_file(source_path) if source_path is not None and source_path.is_file() else None
    offspring_class_hash = hash_class_directory(offspring_classes)
    parent_class_hash = hash_class_directory(parent_classes)
    results: list[MatchResult] = []
    references: list[dict[str, Any]] = []
    for specification in specifications:
        try:
            result = run_microrts_match(
                microrts_dir=config.microrts_dir,
                classes_dir=offspring_classes,
                agent_class="ai.generated.CandidateAgent",
                opponent=COMPARISON_PARENT_CLASS,
                tick_limit=config.tick_limit,
                match_index=specification.match_index,
                match_artifacts_dir=match_artifacts_dir,
                scoring_config=GamePerformanceConfig(
                    result_win_score=config.result_win_score,
                    result_draw_score=config.result_draw_score,
                    result_loss_score=config.result_loss_score,
                    material_scale=config.material_scale,
                    resource_scale=config.resource_scale,
                    unit_values=dict(config.unit_material_values),
                ),
                mock=mock,
                mock_score=1.0,
                seed=specification.seed,
                timeout_seconds=config.match_timeout_seconds,
                map_path=specification.map_path,
                candidate_id=offspring.id,
                generation=offspring.generation,
                candidate_player=specification.candidate_player,
                generation_index=offspring.generation,
                source_hash=source_hash,
                class_hash=offspring_class_hash,
                artifact_mode=config.match_artifact_mode,
                map_id=specification.map_id,
                round_index=specification.round_index,
                opponent_source_generation=comparison_parent.generation,
                opponent_source_candidate_id=comparison_parent.id,
                java_system_properties={PARENT_CLASSES_PROPERTY: str(parent_classes.resolve())},
            )
        except (RuntimeError, OSError, ValueError) as exc:
            result = MatchResult(
                ok=False,
                score=0.0,
                command=[],
                match_index=specification.match_index,
                generation=offspring.generation,
                seed=specification.seed,
                opponent=COMPARISON_PARENT_CLASS,
                candidate_player=specification.candidate_player,
                map_path=specification.map_path,
                map_id=specification.map_id,
                round_index=specification.round_index,
                status="failed",
                failure_category="parent_offspring_match_failure",
                failure_reason=str(exc),
                opponent_source_generation=comparison_parent.generation,
                opponent_source_candidate_id=comparison_parent.id,
            )
        results.append(result)
        references.append({
            "match_index": specification.match_index,
            "map": specification.map_path,
            "round": specification.round_index,
            "seed": specification.seed,
            "offspring_player": specification.candidate_player,
            "comparison_parent_player": specification.opponent_player,
            "status": "completed" if result.ok else "error",
            "artifact_path": f"matches/match_{specification.match_index:02d}",
        })

    wins = sum(result.ok and result.winner == result.candidate_player for result in results)
    losses = sum(result.ok and result.winner == 1 - result.candidate_player for result in results)
    draws = sum(result.ok and result.winner not in {0, 1} for result in results)
    valid = wins + draws + losses
    errors = len(results) - valid
    return ParentOffspringResult(
        offspring_id=offspring.id,
        comparison_parent_id=comparison_parent.id,
        maps=tuple(config.evaluation_maps),
        rounds=tuple(config.resolved_match_seeds),
        sides=("offspring_p0_parent_p1", "parent_p0_offspring_p1"),
        total_matches=len(specifications),
        wins=wins,
        draws=draws,
        losses=losses,
        errors=errors,
        valid_matches=valid,
        reward=head_to_head_reward(wins=wins, draws=draws, losses=losses),
        match_artifact_root=str(match_artifacts_dir),
        offspring_source_hash=source_hash,
        offspring_class_hash=offspring_class_hash,
        comparison_parent_class_hash=parent_class_hash,
        matches=tuple(references),
    )
