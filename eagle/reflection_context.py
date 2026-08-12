"""Typed, bounded-in-memory evidence for EAGLE reflection stages.

Evaluation owns the canonical result objects.  This module maps those objects
to the small mutation-specific envelope consumed by prompt formatters; it does
not read run artifacts or recalculate objectives.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from .candidate import Candidate


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _bounded_unique(values: object, *, limit: int = 8, width: int = 400) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        text = text[:width]
        if text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


@dataclass(frozen=True)
class CandidateReflectionSummary:
    candidate_id: str = ""
    strategy_prompt: str = ""
    code_generation_prompt: str = ""
    generated_code: str = ""
    status: str = "unknown"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ObjectiveSummary:
    game_performance: float | None = None
    code_quality: float | None = None
    other_objectives: tuple[tuple[str, float], ...] = ()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            expected = {
                key: value
                for key, value in {
                    "game_performance": self.game_performance,
                    "code_quality": self.code_quality,
                    **dict(self.other_objectives),
                }.items()
                if value is not None and key in other
            }
            expected.update({
                key: value
                for key, value in {
                    "game_performance": self.game_performance,
                    "code_quality": self.code_quality,
                }.items()
                if value is not None and key in other
            })
            return expected == other
        if not isinstance(other, ObjectiveSummary):
            return NotImplemented
        return (
            self.game_performance,
            self.code_quality,
            self.other_objectives,
        ) == (other.game_performance, other.code_quality, other.other_objectives)

    def to_dict(self) -> dict[str, object]:
        return {
            "game_performance": self.game_performance,
            "code_quality": self.code_quality,
            "other_objectives": dict(self.other_objectives),
        }


@dataclass(frozen=True)
class MapReflectionResult:
    map_name: str = "unknown"
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    p0_result: dict[str, object] = field(default_factory=dict)
    p1_result: dict[str, object] = field(default_factory=dict)
    average_score: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GameplayDiagnostics:
    average_unit_difference: float | None = None
    average_resource_difference: float | None = None
    survival_summary: dict[str, object] = field(default_factory=dict)
    dominant_failure_pattern: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OpponentReflectionSummary:
    opponent_name: str = "unknown"
    opponent_id: str = "unknown"
    weight: float = 1.0
    weighted_score: float | None = None
    raw_score: float | None = None
    wins: int = 0
    losses: int = 0
    draws: int = 0
    p0_wins: int = 0
    p0_losses: int = 0
    p1_wins: int = 0
    p1_losses: int = 0
    map_results: tuple[MapReflectionResult, ...] = ()
    gameplay_diagnostics: GameplayDiagnostics = field(default_factory=GameplayDiagnostics)
    completed_match_count: int = 0
    expected_match_count: int = 0
    missing_match_count: int = 0
    status: str = "unknown"
    failure: dict[str, str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "opponent_name": self.opponent_name,
            "opponent_id": self.opponent_id,
            "weight": self.weight,
            "weighted_score": self.weighted_score,
            "raw_score": self.raw_score,
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "p0_wins": self.p0_wins,
            "p0_losses": self.p0_losses,
            "p1_wins": self.p1_wins,
            "p1_losses": self.p1_losses,
            "map_results": [item.to_dict() for item in self.map_results],
            "gameplay_diagnostics": self.gameplay_diagnostics.to_dict(),
            "completed_match_count": self.completed_match_count,
            "expected_match_count": self.expected_match_count,
            "missing_match_count": self.missing_match_count,
            "status": self.status,
            "failure": self.failure,
        }


@dataclass(frozen=True)
class CodeDiagnostics:
    code_quality: float | None = None
    generation_failure: str | None = None
    validation_failure: str | None = None
    compile_success: bool | None = None
    compile_errors: tuple[str, ...] = ()
    compile_warnings: tuple[str, ...] = ()
    missing_functions: tuple[str, ...] = ()
    invalid_functions: tuple[str, ...] = ()
    function_coverage: float | None = None
    strategy_alignment_score: float | None = None
    strategy_alignment_feedback: str | None = None
    complexity_penalty: float | None = None
    cyclomatic_complexity: int | None = None
    maximum_nesting_depth: int | None = None
    logical_loc: int | None = None
    longest_function_loc: int | None = None
    cyclomatic_penalty: float | None = None
    nesting_penalty: float | None = None
    logical_loc_penalty: float | None = None
    longest_function_penalty: float | None = None
    metric_version: str | None = None
    measured_source: str | None = None
    runtime_failure: str | None = None
    recurring_errors: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["recurring_errors"] = [dict(item) for item in self.recurring_errors]
        return payload


@dataclass(frozen=True)
class EvolutionContext:
    generation_index: int = 0
    parent_candidate_ids: tuple[str, ...] = ()
    mutation_operator: str | None = None
    parent_objectives: tuple[tuple[str, dict[str, float]], ...] = ()
    candidate_rank_or_selection_metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "generation_index": self.generation_index,
            "parent_candidate_ids": list(self.parent_candidate_ids),
            "mutation_operator": self.mutation_operator,
            "parent_objectives": {key: dict(value) for key, value in self.parent_objectives},
            "candidate_rank_or_selection_metadata": dict(self.candidate_rank_or_selection_metadata),
        }


@dataclass(frozen=True)
class ReflectionContext:
    """Minimal structured context, with deprecated fields for old callers."""

    candidate: CandidateReflectionSummary = field(default_factory=CandidateReflectionSummary)
    objectives: ObjectiveSummary | dict[str, float] = field(default_factory=ObjectiveSummary)
    opponents: tuple[OpponentReflectionSummary, ...] = ()
    code_diagnostics: CodeDiagnostics = field(default_factory=CodeDiagnostics)
    evolution: EvolutionContext = field(default_factory=EvolutionContext)
    previous_reflection: str | None = None
    commentary_aggregation: dict[str, object] = field(default_factory=dict)
    representative_commentaries: tuple[dict[str, object], ...] = ()
    priority_strategy_changes: tuple[dict[str, object], ...] = ()
    behaviors_to_preserve: tuple[dict[str, object], ...] = ()
    parent_comparison: dict[str, object] = field(default_factory=dict)

    # Compatibility fields are intentionally not used by new runtime code.
    generation: int = 0
    index: int = 0
    candidate_id: str = ""
    evaluation_status: str = "unknown"
    failure_stage: str | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    game_evidence: dict[str, object] | None = None
    code_quality_evidence: dict[str, object] | None = None
    generation_evidence: dict[str, object] | None = None
    aggregate_game_performance: float | None = None
    game_performance: float | None = None
    opponent_results: tuple[object, ...] = ()
    strongest_opponent: object | None = None
    weakest_opponent: object | None = None
    score_mean: float | None = None
    score_min: float | None = None
    score_max: float | None = None
    score_stddev: float | None = None
    player_resource: float | None = None
    enemy_resource: float | None = None
    resource_breakdown: dict[str, object] | None = None
    performance_breakdown: dict[str, object] | None = None
    temporal_summary: dict[str, object] | None = None
    match_summary: dict[str, object] | None = None
    per_match_results: tuple[dict[str, object], ...] = ()
    wins: int | None = None
    draws: int | None = None
    losses: int | None = None
    final_player_resources: dict[str, object] | None = None
    final_enemy_resources: dict[str, object] | None = None
    final_resource_difference: object | None = None
    unit_material_statistics: dict[str, object] | None = None
    survival_statistics: dict[str, object] | None = None
    round_state_summary: dict[str, object] | None = None
    behavior_summary: dict[str, object] | None = None
    opponent: str = "ai.abstraction.LightRush"
    latest_child_java: str = ""
    raw_generation_response: str = ""
    validation_result: dict[str, object] | None = None
    compilation_result: dict[str, object] | None = None
    integration_result: dict[str, object] | None = None
    runtime_result: dict[str, object] | None = None
    completed_match_count: int | None = None
    function_capability_score: float | None = None
    strategy_alignment_score: float | None = None
    compilation_score: float | None = None
    compiler_errors: tuple[str, ...] = ()
    compiler_warnings: tuple[str, ...] = ()
    strategy_region_score: float | None = None
    strategy_region_validation: dict[str, object] | None = None
    static_quality_score: float | None = None
    static_metrics: dict[str, object] | None = None
    compile_success: bool | None = None
    validation_success: bool | None = None
    runtime_success: bool | None = None
    error_category: str = ""
    error_message: str = ""
    target_module: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.objectives, dict):
            object.__setattr__(self, "objectives", _objective_summary(self.objectives))
        if self.aggregate_game_performance is None and self.game_performance is not None:
            object.__setattr__(self, "aggregate_game_performance", self.game_performance)
        if self.game_performance is None and self.aggregate_game_performance is not None:
            object.__setattr__(self, "game_performance", self.aggregate_game_performance)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "objectives": self.objectives.to_dict(),
            "opponents": [item.to_dict() for item in self.opponents],
            "code_diagnostics": self.code_diagnostics.to_dict(),
            "evolution": self.evolution.to_dict(),
            "previous_reflection": self.previous_reflection,
            "commentary_aggregation": dict(self.commentary_aggregation),
            "representative_commentaries": [dict(item) for item in self.representative_commentaries],
            "priority_strategy_changes": [dict(item) for item in self.priority_strategy_changes],
            "behaviors_to_preserve": [dict(item) for item in self.behaviors_to_preserve],
            "parent_comparison": dict(self.parent_comparison),
            "schema_version": "reflection-context-v2",
        }


def _objective_summary(values: Mapping[str, object]) -> ObjectiveSummary:
    numeric = {str(key): float(value) for key, value in values.items() if _number(value) is not None}
    other = tuple(sorted((key, value) for key, value in numeric.items() if key not in {"game_performance", "code_quality"}))
    return ObjectiveSummary(numeric.get("game_performance"), numeric.get("code_quality"), other)


def _result_stats(rows: list[dict[str, object]]) -> dict[str, object]:
    scores = [_number(row.get("performance")) for row in rows]
    scores = [item for item in scores if item is not None]
    wins = sum(row.get("winner") == row.get("candidate_player") for row in rows)
    losses = sum(
        row.get("winner") in (0, 1) and row.get("winner") != row.get("candidate_player")
        for row in rows
    )
    draws = max(0, len(rows) - wins - losses)
    return {
        "games": len(rows),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "average_score": None if not scores else round(sum(scores) / len(scores), 6),
    }


def _map_results(rows: list[dict[str, object]]) -> tuple[MapReflectionResult, ...]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        name = str(row.get("map_id") or row.get("map") or "unknown")
        grouped.setdefault(name, []).append(row)
    result: list[MapReflectionResult] = []
    for name, map_rows in grouped.items():
        p0 = [row for row in map_rows if row.get("candidate_player") == 0]
        p1 = [row for row in map_rows if row.get("candidate_player") == 1]
        stats = _result_stats(map_rows)
        result.append(MapReflectionResult(name, stats["games"], stats["wins"], stats["losses"], stats["draws"], _result_stats(p0), _result_stats(p1), stats["average_score"]))
    return tuple(result)


def _gameplay_diagnostics(rows: list[dict[str, object]], payload: Mapping[str, object]) -> GameplayDiagnostics:
    breakdowns = [row.get("performance_breakdown") for row in rows if isinstance(row.get("performance_breakdown"), dict)]
    resource_values = [_number(row.get("weighted_resource_difference")) for row in rows]
    resource_values = [item for item in resource_values if item is not None]
    material_values = [_number(item.get("mean_material_difference")) for item in breakdowns]
    material_values = [item for item in material_values if item is not None]
    survival_values = [_number(item.get("survival_ratio")) for item in breakdowns]
    survival_values = [item for item in survival_values if item is not None]
    unit_difference = None
    player_units = _number(payload.get("player_units"))
    enemy_units = _number(payload.get("enemy_units"))
    if player_units is not None and enemy_units is not None:
        unit_difference = round(player_units - enemy_units, 6)
    return GameplayDiagnostics(
        average_unit_difference=unit_difference,
        average_resource_difference=None if not resource_values else round(sum(resource_values) / len(resource_values), 6),
        survival_summary={
            "average_survival_ratio": None if not survival_values else round(sum(survival_values) / len(survival_values), 6),
            "completed_games": len(rows),
        },
        dominant_failure_pattern=(
            str((payload.get("failure") or {}).get("category"))
            if isinstance(payload.get("failure"), dict) and payload.get("failure", {}).get("category")
            else None
        ),
    )


def _opponent_summaries(game: Mapping[str, object]) -> tuple[OpponentReflectionSummary, ...]:
    rows = [item for item in (game.get("match_results") or game.get("matches") or ()) if isinstance(item, dict)]
    by_opponent: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_opponent.setdefault(str(row.get("opponent_id") or row.get("opponent_name") or "unknown"), []).append(row)
    summaries: list[OpponentReflectionSummary] = []
    for raw in game.get("opponent_results") or ():
        if not isinstance(raw, dict):
            continue
        opponent_id = str(raw.get("opponent_id") or "unknown")
        opponent_rows = by_opponent.get(opponent_id, [])
        summaries.append(
            OpponentReflectionSummary(
                opponent_name=str(raw.get("opponent_name") or opponent_id),
                opponent_id=opponent_id,
                weight=float(raw.get("weight") or 0.0),
                weighted_score=_number(raw.get("weighted_contribution")),
                raw_score=_number(raw.get("raw_match_score", raw.get("score"))),
                wins=int(raw.get("wins") or 0),
                losses=int(raw.get("losses") or 0),
                draws=int(raw.get("draws") or 0),
                p0_wins=sum(row.get("winner") == 0 and row.get("candidate_player") == 0 for row in opponent_rows),
                p0_losses=sum(row.get("winner") == 1 and row.get("candidate_player") == 0 for row in opponent_rows),
                p1_wins=sum(row.get("winner") == 1 and row.get("candidate_player") == 1 for row in opponent_rows),
                p1_losses=sum(row.get("winner") == 0 and row.get("candidate_player") == 1 for row in opponent_rows),
                map_results=_map_results(opponent_rows),
                gameplay_diagnostics=_gameplay_diagnostics(opponent_rows, raw),
                completed_match_count=int(raw.get("completed_match_count") or 0),
                expected_match_count=int(raw.get("expected_match_count") or 0),
                missing_match_count=int(raw.get("missing_match_count") or 0),
                status=str(raw.get("status") or "unknown"),
                failure=raw.get("failure") if isinstance(raw.get("failure"), dict) else None,
            )
        )
    return tuple(summaries)


def _diagnostics(candidate: Candidate, evidence: Mapping[str, object], quality: Mapping[str, object], generation: Mapping[str, object], error_memory: tuple[dict[str, object], ...]) -> CodeDiagnostics:
    validation = generation.get("validation") if isinstance(generation.get("validation"), dict) else {}
    compilation = evidence.get("compilation") if isinstance(evidence.get("compilation"), dict) else {}
    quality_breakdown = quality.get("code_quality_breakdown") if isinstance(quality.get("code_quality_breakdown"), dict) else quality
    alignment = quality.get("strategy_alignment") if isinstance(quality.get("strategy_alignment"), dict) else {}
    failed_checks = validation.get("failed_checks") or validation.get("blocked_checks") or ()
    failed_text = [item.get("message") or item.get("reason") or item.get("name") for item in failed_checks if isinstance(item, dict)]
    missing = tuple(item for item in _bounded_unique(failed_text) if "method" in item.lower() or "callable" in item.lower() or "missing" in item.lower())
    invalid = tuple(item for item in _bounded_unique(failed_text) if "invalid" in item.lower() or "forbidden" in item.lower())
    compile_errors = _bounded_unique(tuple(quality_breakdown.get("compiler_errors") or ()) + tuple(item.get("message") for item in compilation.get("diagnostics") or () if isinstance(item, dict) and item.get("severity") == "error"))
    compile_warnings = _bounded_unique(tuple(quality_breakdown.get("compiler_warnings") or ()) + tuple(item.get("message") for item in compilation.get("diagnostics") or () if isinstance(item, dict) and item.get("severity") == "warning"))
    failure_stage = str(evidence.get("failure_stage") or candidate.failure_stage or "")
    failure_reason = str(evidence.get("failure_reason") or candidate.failure_reason or "") or None
    validation_failure = failure_reason if failure_stage == "validation" else ("; ".join(_bounded_unique(failed_text))[:800] or None)
    generation_failure = failure_reason if failure_stage == "generation" else None
    runtime_failure = failure_reason if failure_stage in {"runtime", "integration"} else None
    alignment_reason = alignment.get("reason") or alignment.get("feedback")
    return CodeDiagnostics(
        code_quality=_number(quality_breakdown.get("code_quality")),
        generation_failure=generation_failure,
        validation_failure=validation_failure,
        compile_success=(compilation.get("ok") if "ok" in compilation else None),
        compile_errors=compile_errors,
        compile_warnings=compile_warnings,
        missing_functions=missing,
        invalid_functions=invalid,
        function_coverage=_number(quality_breakdown.get("function_score")),
        strategy_alignment_score=_number(quality_breakdown.get("strategy_alignment_score")),
        strategy_alignment_feedback=None if alignment_reason is None else str(alignment_reason)[:800],
        complexity_penalty=_number(quality_breakdown.get("complexity_penalty")),
        cyclomatic_complexity=_int_or_none(quality_breakdown.get("cyclomatic_complexity")),
        maximum_nesting_depth=_int_or_none(quality_breakdown.get("maximum_nesting_depth")),
        logical_loc=_int_or_none(quality_breakdown.get("logical_loc")),
        longest_function_loc=_int_or_none(quality_breakdown.get("longest_function_loc")),
        cyclomatic_penalty=_number(quality_breakdown.get("cyclomatic_penalty")),
        nesting_penalty=_number(quality_breakdown.get("nesting_penalty")),
        logical_loc_penalty=_number(quality_breakdown.get("logical_loc_penalty")),
        longest_function_penalty=_number(quality_breakdown.get("longest_function_penalty")),
        metric_version=(str(quality_breakdown.get("metric_version")) if quality_breakdown.get("metric_version") else None),
        measured_source=(str(quality_breakdown.get("measured_source")) if quality_breakdown.get("measured_source") else None),
        runtime_failure=runtime_failure,
        recurring_errors=error_memory[:3],
    )


def _parent_comparison(candidate: Candidate, references: Mapping[str, "Candidate"] | None) -> dict[str, object]:
    if not references:
        return {"available": False, "reason": "No parent or generation-best candidate evidence was supplied."}
    child_game = candidate.game_eval_result or {}
    child_config = child_game.get("evaluation_configuration") if isinstance(child_game, dict) else None
    child_rows = child_game.get("match_results") if isinstance(child_game, dict) else None
    if not isinstance(child_config, dict) or not isinstance(child_rows, list):
        return {"available": False, "reason": "Equivalent comparison requires persisted match configuration and summaries."}
    output: dict[str, object] = {"available": False, "matched_pairs": [], "improved": [], "regressed": []}
    for label, parent in sorted(references.items()):
        parent_game = parent.game_eval_result or {}
        if parent_game.get("evaluation_configuration") != child_config:
            continue
        parent_rows = parent_game.get("match_results")
        if not isinstance(parent_rows, list):
            continue
        parent_by_key = {_comparison_key(row): row for row in parent_rows if isinstance(row, dict)}
        for child_row in child_rows:
            if not isinstance(child_row, dict):
                continue
            parent_row = parent_by_key.get(_comparison_key(child_row))
            if parent_row is None:
                continue
            child_score = _numeric(child_row.get("performance"))
            parent_score = _numeric(parent_row.get("performance"))
            if child_score is None or parent_score is None:
                continue
            pair = {
                "reference": label,
                "parent_candidate_id": parent.id,
                "child_candidate_id": candidate.id,
                "opponent": child_row.get("opponent_id"),
                "map": child_row.get("map_id") or child_row.get("map"),
                "candidate_side": f"p{child_row.get('candidate_player')}",
                "parent_match_id": f"match_{parent_row.get('match_index', -1):02d}",
                "child_match_id": f"match_{child_row.get('match_index', -1):02d}",
                "delta": round(child_score - parent_score, 6),
                "status": "improved" if child_score > parent_score else "regressed" if child_score < parent_score else "unchanged",
                "relevant_ticks": [],
            }
            output["matched_pairs"].append(pair)
            if pair["status"] == "improved":
                output["improved"].append(pair)
            elif pair["status"] == "regressed":
                output["regressed"].append(pair)
    output["available"] = bool(output["matched_pairs"])
    if not output["available"]:
        output["reason"] = "No equivalent matches were available under the same evaluation configuration."
    return output


def _comparison_key(row: Mapping[str, object]) -> tuple[object, object, object]:
    return (row.get("opponent_id"), row.get("map_id") or row.get("map"), row.get("candidate_player"))


def _numeric(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_reflection_context(
    candidate: Candidate,
    *,
    generation: int,
    index: int,
    reflection_type: str | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
    evolution_candidate: Candidate | None = None,
    parent_objectives: Mapping[str, Mapping[str, object]] | None = None,
    reference_candidates: Mapping[str, Candidate] | None = None,
) -> ReflectionContext:
    evidence = candidate.metadata.get("reflection_evidence") or {}
    game = candidate.game_eval_result or (evidence.get("game") if isinstance(evidence.get("game"), dict) else {}) or {}
    quality = (
        candidate.code_quality_result
        or (evidence.get("code_quality_payload") if isinstance(evidence.get("code_quality_payload"), dict) else {})
        or (evidence.get("code_quality") if isinstance(evidence.get("code_quality"), dict) else {})
        or {}
    )
    generation_evidence = evidence.get("generation") if isinstance(evidence.get("generation"), dict) else {}
    objectives = candidate.fitness_objectives or evidence.get("objectives") or {}
    aggregate_game_performance = _number(game.get("game_performance"))
    if aggregate_game_performance is None:
        aggregate_game_performance = _number(game.get("objective"))
    if aggregate_game_performance is None:
        aggregate_game_performance = _number(objectives.get("game_performance")) if isinstance(objectives, Mapping) else None
    history = candidate.metadata.get("reflection_history") or ()
    previous: str | None = None
    for item in reversed(history if isinstance(history, (list, tuple)) else ()):
        if not isinstance(item, dict):
            continue
        if reflection_type and item.get("reflection_type") != reflection_type:
            continue
        previous = str(item.get("analysis_summary") or item.get("revised_prompt") or "")[:2400] or None
        break
    selected_candidate = evolution_candidate or candidate
    parent_payload = parent_objectives or {}
    parent_objective_items = tuple(
        (str(key), {str(name): float(value) for name, value in values.items() if _number(value) is not None})
        for key, values in sorted(parent_payload.items())
    )
    context = ReflectionContext(
        candidate=CandidateReflectionSummary(
            candidate.id,
            candidate.strategy_prompt,
            candidate.generation_prompt,
            candidate.generated_java or str(generation_evidence.get("assembled_java") or generation_evidence.get("extracted_code") or ""),
            candidate.status,
        ),
        objectives=_objective_summary({**objectives, "game_performance": aggregate_game_performance}),
        opponents=_opponent_summaries(game),
        code_diagnostics=_diagnostics(candidate, evidence, quality, generation_evidence, error_memory),
        evolution=EvolutionContext(
            generation_index=generation,
            parent_candidate_ids=tuple(selected_candidate.parent_ids),
            mutation_operator=selected_candidate.mutation_type or selected_candidate.operator,
            parent_objectives=parent_objective_items,
            candidate_rank_or_selection_metadata={
                key: value
                for key, value in selected_candidate.metadata.items()
                if key in {"lexicase_case", "lexicase_case_order", "selection_role"}
            },
        ),
        previous_reflection=previous,
        commentary_aggregation=(game.get("commentary_aggregation") if isinstance(game.get("commentary_aggregation"), dict) else {}),
        priority_strategy_changes=tuple(item for item in ((game.get("commentary_aggregation") or {}).get("priority_strategy_changes") or ()) if isinstance(item, dict)),
        behaviors_to_preserve=tuple(item for item in ((game.get("commentary_aggregation") or {}).get("behaviors_to_preserve") or ()) if isinstance(item, dict)),
        parent_comparison=_parent_comparison(candidate, reference_candidates),
        per_match_results=tuple(
            item for item in (game.get("match_results") or game.get("matches") or ())
            if isinstance(item, dict)
        ),
        wins=int(game.get("wins") or 0),
        draws=int(game.get("draws") or 0),
        losses=int(game.get("losses") or 0),
    )
    aggregation = context.commentary_aggregation
    representatives: list[dict[str, object]] = []
    for opponent in aggregation.get("opponent_summaries", ()) if isinstance(aggregation, dict) else ():
        if not isinstance(opponent, dict):
            continue
        for item in opponent.get("representative_matches", ()) or ():
            if isinstance(item, dict):
                representatives.append({"opponent": opponent.get("opponent"), **item})
    object.__setattr__(context, "representative_commentaries", tuple(representatives[:8]))
    # Read compatibility aliases keep older callers/resume code observable
    # while all new prompt formatting uses the structured fields above.
    object.__setattr__(context, "generation", generation)
    object.__setattr__(context, "index", index)
    object.__setattr__(context, "candidate_id", candidate.id)
    object.__setattr__(context, "evaluation_status", candidate.status)
    object.__setattr__(context, "failure_stage", evidence.get("failure_stage") or candidate.failure_stage)
    object.__setattr__(context, "failure_category", evidence.get("failure_category") or candidate.metadata.get("failure_category"))
    object.__setattr__(context, "failure_reason", evidence.get("failure_reason") or candidate.failure_reason)
    object.__setattr__(context, "error_category", str(evidence.get("failure_category") or candidate.metadata.get("failure_category") or ""))
    object.__setattr__(context, "error_message", str(evidence.get("failure_reason") or candidate.failure_reason or ""))
    object.__setattr__(context, "game_evidence", dict(game))
    object.__setattr__(context, "code_quality_evidence", dict(quality))
    object.__setattr__(context, "generation_evidence", dict(generation_evidence))
    object.__setattr__(context, "aggregate_game_performance", context.objectives.game_performance)
    object.__setattr__(context, "game_performance", context.objectives.game_performance)
    object.__setattr__(context, "latest_child_java", context.candidate.generated_code)
    object.__setattr__(context, "raw_generation_response", str(generation_evidence.get("raw_response") or ""))
    object.__setattr__(context, "validation_result", generation_evidence.get("validation") if isinstance(generation_evidence.get("validation"), dict) else None)
    object.__setattr__(context, "compilation_result", evidence.get("compilation") if isinstance(evidence.get("compilation"), dict) else None)
    object.__setattr__(context, "integration_result", evidence.get("integration") if isinstance(evidence.get("integration"), dict) else None)
    object.__setattr__(context, "runtime_result", dict(game))
    object.__setattr__(context, "completed_match_count", int(game.get("completed_match_count") or 0) if game else None)
    object.__setattr__(context, "function_capability_score", context.code_diagnostics.function_coverage)
    object.__setattr__(context, "strategy_alignment_score", context.code_diagnostics.strategy_alignment_score)
    object.__setattr__(context, "compiler_errors", context.code_diagnostics.compile_errors)
    object.__setattr__(context, "compiler_warnings", context.code_diagnostics.compile_warnings)
    return context


def coerce_structured_context(context: ReflectionContext, candidate: Candidate) -> ReflectionContext:
    """Translate old direct-construction fixtures into the new structured view."""
    legacy_fields_present = any(
        value is not None
        for value in (
            context.match_summary,
            context.game_evidence,
            context.validation_result,
            context.compilation_result,
            context.integration_result,
        )
    ) or bool(context.generation or context.index or context.candidate_id)
    if context.candidate.candidate_id or context.opponents or context.evolution.generation_index or not legacy_fields_present:
        return context
    objectives = context.objectives.to_dict() if isinstance(context.objectives, ObjectiveSummary) else context.objectives
    game_performance = _number(objectives.get("game_performance"))
    if game_performance is None:
        game_performance = context.aggregate_game_performance
    quality = context.code_quality_evidence or {}
    diagnostics = CodeDiagnostics(
        validation_failure=context.error_message if context.error_category == "validation" else None,
        compile_success=context.compile_success,
        compile_errors=_bounded_unique(context.compiler_errors),
        compile_warnings=_bounded_unique(context.compiler_warnings),
        function_coverage=context.function_capability_score,
        strategy_alignment_score=context.strategy_alignment_score,
        runtime_failure=context.error_message if context.error_category == "runtime" else None,
    )
    return ReflectionContext(
        candidate=CandidateReflectionSummary(context.candidate_id or candidate.id, candidate.strategy_prompt, candidate.generation_prompt, context.latest_child_java or candidate.generated_java, context.evaluation_status),
        objectives=ObjectiveSummary(game_performance, _number(objectives.get("code_quality"))),
        opponents=(),
        code_diagnostics=diagnostics,
        evolution=EvolutionContext(context.generation, tuple(candidate.parent_ids), candidate.mutation_type or candidate.operator),
        previous_reflection=context.previous_reflection,
    )
