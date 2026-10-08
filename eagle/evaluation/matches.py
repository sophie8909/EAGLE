"""Deterministic evaluation matrix dispatch and scoring configuration."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.game_performance import GamePerformanceConfig
from eagle.evaluation.determinism import derive_match_seed
from eagle.evaluation.match_matrix import (
    MatrixOpponent,
    MatchSpecification,
    build_match_matrix,
    canonical_evaluation_maps,
)
from eagle.evaluation.runtime_evaluation import (
    MatchResult,
    hash_class_directory,
    hash_file,
    run_microrts_match,
)
from eagle.generation.java_agent_generator import GeneratedJavaAgent

from .opponents import _opponent_display_name, _resolved_static_evaluation_opponents
from .records import EvaluationOpponent


def evaluate_matches(
    *,
    candidate: Candidate,
    agent: GeneratedJavaAgent,
    config: ExperimentConfig,
    classes_dir: Path,
    match_artifacts_dir: Path | None,
    mock: bool,
    ordinal: int,
    opponent_pool: tuple[EvaluationOpponent, ...] | None = None,
) -> tuple[list[MatchResult], str | None]:
    """Run the complete evaluation matrix against one immutable opponent pool."""
    match_results: list[MatchResult] = []
    source_hash = hash_file(agent.source_path)
    candidate_classes_dir = classes_dir / candidate.id
    class_hash = hash_class_directory(candidate_classes_dir)
    first_error: str | None = None
    try:
        opponents = list(opponent_pool) if opponent_pool is not None else list(
            _resolved_static_evaluation_opponents(config, mock=mock, classes_dir=classes_dir)
        )
        matrix_opponents = tuple(
            MatrixOpponent(
                item.opponent_id,
                item.weight,
            )
            for item in opponents
        )
        specifications = build_match_matrix(
            matrix_opponents,
            canonical_evaluation_maps(
                config.evaluation_maps,
                tick_limits=config.resolved_evaluation_map_tick_limits,
            ),
            rounds_per_map=config.rounds_per_map,
            swap_player_sides=config.swap_player_sides,
        )
        if not opponents:
            return match_results, (
                "self-play opponent pool is empty"
            )
        opponent_by_id = {item.opponent_id: item for item in opponents}
        scoring_config = scoring_config_from_experiment(config)

        def run_specification(specification: MatchSpecification) -> MatchResult:
            opponent = opponent_by_id[specification.opponent_id]
            match_seed = derive_match_seed(
                config.random_seed,
                candidate_id=candidate.id,
                opponent_id=opponent.opponent_id,
                map_id=specification.map_id,
                round_index=specification.round_index,
                candidate_player=specification.candidate_player,
                match_index=specification.match_index,
            )
            try:
                result = run_microrts_match(
                    microrts_dir=config.microrts_dir, classes_dir=candidate_classes_dir,
                    agent_class=agent.qualified_class_name, opponent=opponent.class_name,
                    opponent_id=opponent.opponent_id,
                    opponent_name=(
                        opponent.display_name
                        or _opponent_display_name(opponent.opponent_id)
                    ),
                    tick_limit=specification.tick_limit, match_index=specification.match_index,
                    match_artifacts_dir=match_artifacts_dir,
                    scoring_config=scoring_config, mock=mock,
                    mock_score=config.mock_score_base + config.mock_score_step * (
                        ordinal + specification.match_index
                    ),
                    timeout_seconds=config.match_timeout_seconds,
                    map_path=specification.map_path, candidate_id=candidate.id,
                    generation=candidate.generation,
                    candidate_player=specification.candidate_player,
                    generation_index=candidate.generation,
                    source_hash=source_hash, class_hash=class_hash,
                    extra_classpath_entries=opponent.classpath_entries,
                    artifact_mode=config.match_artifact_mode,
                    map_id=specification.map_id,
                    round_index=specification.round_index,
                    opponent_weight=specification.opponent_weight,
                    opponent_source_generation=opponent.source_generation,
                    opponent_source_candidate_id=opponent.source_candidate_id,
                    match_seed=match_seed,
                )
            except (RuntimeError, OSError) as exc:
                result = MatchResult(
                    ok=False,
                    score=0.0,
                    command=[],
                    match_index=specification.match_index,
                    generation=candidate.generation,
                    opponent=opponent.class_name,
                    candidate_player=specification.candidate_player,
                    map_path=specification.map_path,
                    map_id=specification.map_id,
                    round_index=specification.round_index,
                    status="failed",
                    failure_category="runtime_match_failure",
                    failure_reason=str(exc),
                    match_seed=match_seed,
                )
            return replace(
                result,
                generation=candidate.generation,
                opponent_id=opponent.opponent_id,
                opponent_name=(
                    opponent.display_name
                    or _opponent_display_name(opponent.opponent_id)
                ),
                map_id=specification.map_id,
                round_index=specification.round_index,
                opponent_weight=specification.opponent_weight,
                opponent_source_generation=opponent.source_generation,
                opponent_source_candidate_id=opponent.source_candidate_id,
            )

        worker_count = min(config.match_workers, len(specifications))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="eagle-match",
        ) as executor:
            for result in executor.map(run_specification, specifications):
                match_results.append(result)
                if not result.ok and first_error is None:
                    first_error = match_error_message(result)
    except (RuntimeError, OSError) as exc:
        return match_results, str(exc)
    expected_matches = config.fixed_matches_per_opponent * len(opponents)
    if len(match_results) != expected_matches:
        return match_results, f"partial evaluation: completed {len(match_results)} of {expected_matches} matches"
    return match_results, first_error


def scoring_config_from_experiment(config: ExperimentConfig) -> GamePerformanceConfig:
    return GamePerformanceConfig(
        result_win_score=config.result_win_score,
        result_draw_score=config.result_draw_score,
        result_loss_score=config.result_loss_score,
        material_scale=config.material_scale,
        resource_scale=config.resource_scale,
        unit_values=dict(config.unit_material_values),
    )


def match_error_message(result: MatchResult) -> str:
    stderr = (result.stderr or "").strip()
    if result.failure_reason:
        return result.failure_reason
    if stderr:
        return stderr.splitlines()[0]
    return f"match returned {result.returncode}"
