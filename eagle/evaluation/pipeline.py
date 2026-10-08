"""Population and candidate evaluation orchestration."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import subprocess
import time
from pathlib import Path

from eagle.artifacts import write_candidate_artifacts, write_candidate_inputs
from eagle.candidate import Candidate, compact_candidate_metadata
from eagle.config import ExperimentConfig
from eagle.evaluation.code_quality import (
    CodeQualityBreakdown,
    StrategyRegionScoreResult,
    analyze_compilation,
    build_failure_code_quality,
    build_successful_code_quality,
    evaluate_agent_strategy_region,
)
from eagle.evaluation.compiler import CompileResult
from eagle.evaluation.determinism import derive_seed
from eagle.evaluation.game_metrics import GameMetrics, compute_game_metrics
from eagle.evaluation.microrts_runner import IntegrationResult, integrate_microrts_agent
from eagle.evaluation.objectives import build_objectives, reporting_game_performance
from eagle.evaluation.runtime_evaluation import MatchResult
from eagle.evaluation.semantic_signature import (
    ProbeMap,
    SemanticDataset,
    SemanticSignatureResult,
    ensure_semantic_dataset,
    evaluate_semantic_signature,
    unavailable_semantic_signature,
)
from eagle.generation.backend import GenerationBackend
from eagle.generation.java_agent_generator import GeneratedJavaAgent
from eagle.opponent_cases import FAILED_OPPONENT_SCORE
from eagle.timing import utc_now

from . import decoding, matches as match_module, opponents as opponent_setup
from .records import (
    BoundedGenerationResult,
    CandidateEvaluation,
    CandidateResult,
    EvaluationOpponent,
)


def evaluate_population(
    population: list[Candidate],
    *,
    generation: int,
    config: ExperimentConfig,
    backend: GenerationBackend,
    generated_agents_dir: Path,
    classes_dir: Path,
    candidates_dir: Path,
    mock: bool,
    llm_client: object | None = None,
    run_timing_path: Path | None = None,
    run_id: str | None = None,
    opponent_candidates: list[Candidate] | None = None,
) -> list[Candidate]:
    semantic_dataset: SemanticDataset | None = None
    semantic_dataset_error: str | None = None
    if config.semantic_probes_enabled and not mock:
        try:
            probe_maps = tuple(
                ProbeMap(
                    map_id=f"map_{index + 1}_{Path(path).stem}",
                    path=path,
                    tick_limit=tick_limit,
                )
                for index, (path, tick_limit) in enumerate(zip(
                    config.evaluation_maps,
                    config.resolved_evaluation_map_tick_limits,
                    strict=True,
                ))
            )
            semantic_dataset = ensure_semantic_dataset(
                microrts_dir=config.microrts_dir,
                maps=probe_maps,
                output_root=config.semantic_state_root,
                reference_agents=config.semantic_reference_agents,
                player_side=config.semantic_probe_player_side,
                phase_fractions=config.semantic_phase_fractions,
                timeout_seconds=config.semantic_probe_timeout_seconds,
                random_seed=config.random_seed,
            )
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            semantic_dataset_error = f"{type(exc).__name__}: {exc}"
    prepared: list[tuple[Candidate, BoundedGenerationResult]] = []
    for index, candidate in enumerate(population):
        print(
            f"[gen {generation} cand {index + 1}/{len(population)}] "
            f"{candidate.id} stage=generation status=started",
            flush=True,
        )
        write_candidate_inputs(candidates_dir, candidate)
        bounded_generation = decoding.decode_validate_compile_candidate(
            candidate,
            config=config,
            backend=backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            mock=mock,
            candidate_artifact_dir=candidates_dir / candidate.id,
        )
        prepared.append((candidate, bounded_generation))

    opponent_pool = None
    if config.evaluation_mode == "self_play":
        opponent_pool = opponent_setup._build_self_play_opponents(
            opponent_candidates if opponent_candidates is not None else population,
            prepared=prepared,
            config=config,
            classes_dir=classes_dir,
            mock=mock,
        )
    evaluated = []
    for index, (candidate, bounded_generation) in enumerate(prepared):
        evaluation = evaluate_candidate(
            candidate,
            config=config,
            backend=backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            match_artifacts_dir=candidates_dir / candidate.id / "matches",
            mock=mock,
            llm_client=llm_client,
            ordinal=index,
            bounded_generation=bounded_generation,
            opponent_pool=opponent_pool,
            semantic_dataset=semantic_dataset,
            semantic_dataset_error=semantic_dataset_error,
            semantic_cache_root=candidates_dir.parent / "archives" / "semantic_signature_cache",
        )
        if run_timing_path is not None:
            _append_match_timing_events(
                run_timing_path,
                run_id=run_id,
                generation=generation,
                candidate=evaluation.candidate,
                matches=evaluation.match_results,
            )
        write_candidate_artifacts(candidates_dir, evaluation)
        evaluated.append(evaluation.candidate)
        print_progress(generation=generation, index=index, population_size=len(population), evaluation=evaluation)
    return evaluated


def _append_match_timing_events(
    path: Path,
    *,
    run_id: str | None,
    generation: int,
    candidate: Candidate,
    matches: list[MatchResult],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", buffering=1) as handle:
        for result in matches:
            event = {
                "event": "match",
                "run_id": run_id,
                "generation": generation,
                "candidate_id": candidate.id,
                "candidate_generation": candidate.generation,
                "match_index": result.match_index,
                "opponent_id": result.opponent_id,
                "opponent_name": result.opponent_name,
                "map_id": result.map_id,
                "round_index": result.round_index,
                "candidate_player": result.candidate_player,
                "status": result.status,
                "ok": result.ok,
                "score": result.score,
                "winner": result.winner,
                "duration_seconds": float(result.duration_seconds or 0.0),
                "started_at": result.started_at or None,
                "finished_at": result.finished_at or None,
                "timeout_seconds": result.timeout_seconds,
                "failure_category": result.failure_category,
                "failure_reason": result.failure_reason,
                "opponent_weight": result.opponent_weight,
                "opponent_source_generation": result.opponent_source_generation,
                "opponent_source_candidate_id": result.opponent_source_candidate_id,
            }
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")


def evaluate_candidate(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: GenerationBackend,
    generated_agents_dir: Path,
    classes_dir: Path,
    mock: bool,
    llm_client: object | None = None,
    ordinal: int,
    match_artifacts_dir: Path | None = None,
    bounded_generation: BoundedGenerationResult | None = None,
    opponent_pool: tuple[EvaluationOpponent, ...] | None = None,
    semantic_dataset: SemanticDataset | None = None,
    semantic_dataset_error: str | None = None,
    semantic_cache_root: Path | None = None,
) -> CandidateEvaluation:
    """Evaluate one candidate through the canonical child pipeline.

    The stages are ordered and failure-aware: generate Java, validate it,
    compile it, integrate it with MicroRTS, run the complete match matrix,
    calculate both objectives, and return one candidate/artifact envelope.
    A failed stage stops only dependent later stages; the candidate still
    receives explicit failure scores and remains available to lexicase.
    """

    genotype_before = (
        candidate.strategy_prompt,
        candidate.generation_prompt,
        candidate.inherited_java,
    )

    # Stages 1-2 use the same bounded decoder helper as production smoke
    # checks. Only its selected (or, when exhausted, final) attempt becomes
    # the canonical phenotype and compilation evidence below.
    if bounded_generation is None:
        bounded_generation = decoding.decode_validate_compile_candidate(
            candidate,
            config=config,
            backend=backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            mock=mock,
            candidate_artifact_dir=None if match_artifacts_dir is None else match_artifacts_dir.parent,
        )
    generation = bounded_generation.generation
    initial_seed_source = bounded_generation.initial_seed_source
    source_without_generation = bounded_generation.source_without_generation
    generation_attempts = bounded_generation.attempts
    representative_attempt = bounded_generation.representative_attempt
    compile_result = bounded_generation.compile_result
    compile_error = bounded_generation.compile_error
    compilation_started_at = representative_attempt.compilation_timing.get("started_at")
    compilation_finished_at = representative_attempt.compilation_timing.get("finished_at")
    representative_compilation_duration = representative_attempt.compilation_timing.get("duration_seconds")
    compilation_duration = sum(
        float(item.compilation_timing.get("duration_seconds") or 0.0)
        for item in generation_attempts
    )
    source_provenance = None
    if initial_seed_source:
        source_path = getattr(backend, "source_path", None)
        source_provenance = {
            "kind": "checked_in_java_seed",
            "path": None if source_path is None else str(Path(source_path).resolve()),
            "sha256": (
                hashlib.sha256(generation.assembled_java.encode("utf-8")).hexdigest()
                if generation.assembled_java
                else None
            ),
        }
    elif source_without_generation:
        source_candidate_id = (
            candidate.metadata.get("self_play_fitness_refresh", {})
            .get("source_parent_id")
        )
        source_provenance = {
            "kind": "existing_candidate_phenotype",
            "source_candidate_id": source_candidate_id,
            "path": (
                None
                if not source_candidate_id
                else f"../{source_candidate_id}/phenotype/CandidateAgent.java"
            ),
            "sha256": (
                hashlib.sha256(generation.assembled_java.encode("utf-8")).hexdigest()
                if generation.assembled_java
                else None
            ),
        }
    elif candidate.mutation_type == "code" and candidate.generated_java:
        source_provenance = {
            "kind": "code_reflection",
            "path": "mutation/code_reflection/reflected_candidate.java",
            "sha256": hashlib.sha256(
                candidate.generated_java.encode("utf-8")
            ).hexdigest(),
        }
    generation_timing = {
        "stage": "generation",
        "operation": (
            "code_reflection_direct"
            if candidate.mutation_type == "code" and candidate.generated_java
            else getattr(backend, "operation", None)
        ),
        "model": getattr(backend, "model", None),
        "started_at": None if source_without_generation else generation_attempts[0].generation_timing.get("started_at"),
        "finished_at": None if source_without_generation else generation_attempts[-1].generation_timing.get("finished_at"),
        "duration_seconds": None if source_without_generation else sum(
            float(item.generation_timing.get("duration_seconds") or 0.0)
            for item in generation_attempts
        ),
        "attempts": [] if source_without_generation else [
            {
                **item.generation_timing,
                "status": "success" if item.generation.raw_llm_output else "error",
                "validation_status": item.generation.validation_result.status,
                "compilation_status": item.compilation_timing.get("status"),
                "selected": item.selected,
                "final": item.final,
            }
            for item in generation_attempts
        ],
        "max_attempts": bounded_generation.max_attempts,
        "selected_attempt": None if source_without_generation else bounded_generation.selected_attempt,
        "final_attempt": None if source_without_generation else bounded_generation.final_attempt,
        "source": source_provenance,
    }

    agent = generation.agent
    region_score = generation.strategy_region_score_result
    if region_score is None:
        region_score = evaluate_agent_strategy_region(
            "",
            error=generation.failure_reason or "Complete Java validation did not run.",
        )

    compiler = analyze_compilation(compile_result)
    integration_result: IntegrationResult | None = None
    matches: list[MatchResult] = []
    match_error: str | None = None
    evaluation_started_at: str | None = None
    evaluation_finished_at: str | None = None
    evaluation_started: float | None = None

    # Stages 3-4: integrate the class, then execute the full configured
    # opponent/map/round/side matrix. This is the sole owner of match count.
    if compiler.compile_success and agent is not None:
        integration_dir = None if match_artifacts_dir is None else match_artifacts_dir.parent / "integration"
        integration_result = integrate_microrts_agent(
            microrts_dir=config.microrts_dir,
            classes_dir=classes_dir / candidate.id,
            agent_class=agent.qualified_class_name,
            integration_artifacts_dir=integration_dir,
            seed=derive_seed(config.random_seed, "integration", candidate.id),
            mock=mock,
        )
        if integration_result.ok:
            evaluation_started_at = utc_now()
            evaluation_started = time.monotonic()
            matches, match_error = match_module.evaluate_matches(
                candidate=candidate,
                agent=agent,
                config=config,
                classes_dir=classes_dir,
                match_artifacts_dir=match_artifacts_dir,
                mock=mock,
                ordinal=ordinal,
                opponent_pool=opponent_pool,
            )
        else:
            match_error = integration_result.failure_reason or "MicroRTS integration failed."

    # Semantic probing is independent diagnostic evidence. It is deliberately
    # excluded from failure_stage and objective construction so an unavailable
    # probe never changes game fitness.
    if not config.semantic_probes_enabled:
        semantic_result = unavailable_semantic_signature("semantic probes disabled")
    elif mock:
        semantic_result = unavailable_semantic_signature(
            "mock evaluation does not fabricate executable semantic evidence"
        )
    elif semantic_dataset_error:
        semantic_result = unavailable_semantic_signature(semantic_dataset_error)
    elif semantic_dataset is None:
        semantic_result = unavailable_semantic_signature("semantic probe dataset unavailable")
    elif not compiler.compile_success or agent is None:
        semantic_result = unavailable_semantic_signature("compiled candidate agent unavailable")
    elif integration_result is None or not integration_result.ok:
        semantic_result = unavailable_semantic_signature("candidate did not pass MicroRTS integration")
    else:
        semantic_result = evaluate_semantic_signature(
            candidate_id=candidate.id,
            agent_class=agent.qualified_class_name,
            candidate_classes_dir=classes_dir / candidate.id,
            phenotype_sha256=hashlib.sha256(generation.assembled_java.encode("utf-8")).hexdigest(),
            dataset=semantic_dataset,
            microrts_dir=config.microrts_dir,
            cache_root=(
                semantic_cache_root
                if semantic_cache_root is not None
                else classes_dir.parent / "archives" / "semantic_signature_cache"
            ),
            timeout_seconds=config.semantic_probe_timeout_seconds,
            random_seed=config.random_seed,
        )

    # Stage 5: classify the first blocking failure without discarding partial
    # diagnostics or successful match records.
    failure_category: str | None = None
    failure_reason: str | None = None
    failure_stage: str | None = None
    completed_matches = sum(result.ok for result in matches)
    expected_match_count = (
        config.fixed_matches_per_opponent * len(opponent_pool)
        if opponent_pool is not None
        else config.expected_match_count
    )
    if agent is None:
        validation_failed = bool(generation.validation_result.failed_checks)
        failure_stage = generation.failure_stage or ("validation" if validation_failed else "generation")
        failure_category = generation.failure_category or f"{failure_stage}_failure"
        failure_reason = generation.failure_reason or "Java generation did not produce a valid agent."
    elif not compiler.compile_success:
        failure_category = "Java compile failure"
        failure_reason = (
            compile_error or decoding.compile_error_message(compile_result)
            if compile_result
            else compile_error or "Compilation was not run."
        )
        failure_stage = "compilation"
    elif integration_result is not None and not integration_result.ok:
        failure_category = "MicroRTS integration failure"
        failure_reason = integration_result.failure_reason
        failure_stage = "integration"
    elif match_error or completed_matches != expected_match_count:
        failed_match = next((result for result in matches if not result.ok), None)
        failure_category = (
            failed_match.failure_category
            if failed_match is not None and failed_match.failure_category
            else "partial_evaluation"
        )
        failure_reason = match_error or f"partial evaluation: completed {completed_matches} of {expected_match_count} matches"
        failure_stage = "runtime"

    # Stage 6: aggregate game telemetry and calculate one objective per fixed
    # opponent. The weighted aggregate is reporting-only and never enters
    # parent or survivor selection.
    objective_started_at = utc_now()
    objective_started = time.monotonic()
    game_metrics = compute_game_metrics(
        matches,
        fixed_opponent_weights=(
            {item.opponent_id: item.weight for item in opponent_pool}
            if opponent_pool is not None
            else dict(config.evaluation_opponents)
        ),
        expected_match_count=expected_match_count,
        expected_matches_per_opponent=config.fixed_matches_per_opponent,
        evaluation_maps=config.evaluation_maps,
    )
    if failure_stage is None:
        quality = build_successful_code_quality(
            compiler,
            strategy_regions={"candidate_generated_methods": generation.strategy_region},
            strategy_region=region_score,
        )
    else:
        quality = build_failure_code_quality(
            failure_stage,
            compiler=compiler,
            integration_pass_ratio=(
                0.0 if integration_result is None else integration_result.integration_pass_ratio
            ),
            completed_matches=completed_matches,
            strategy_regions={"candidate_generated_methods": generation.strategy_region},
            strategy_region=region_score,
        )
    opponent_case_scores = build_objectives(
        game_metrics=game_metrics,
        code_quality=quality,
        game_failure=failure_stage is not None,
        required_cases=(
            tuple(opponent.opponent_id for opponent in opponent_pool)
            if opponent_pool is not None
            else config.lexicase_case_ids
        ),
    )
    objectives = (
        {
            "game_performance": (
                FAILED_OPPONENT_SCORE
                if failure_stage is not None
                else float(game_metrics.objective)
            )
        }
        if config.evaluation_mode == "self_play"
        else opponent_case_scores
    )
    objective_finished_at = utc_now()
    objective_duration = max(0.0, time.monotonic() - objective_started)

    evaluation_duration: float | None = None
    if evaluation_started is not None:
        evaluation_finished_at = utc_now()
        evaluation_duration = max(0.0, time.monotonic() - evaluation_started)
    match_durations = [max(0.0, result.duration_seconds) for result in matches]
    quality_payload = {
        "code_quality": quality.code_quality,
        "code_quality_breakdown": quality.to_json_dict(),
        "strategy_region_validation": region_score.to_json_dict(),
    }
    game_payload = game_metrics.to_json_dict()
    game_payload["opponent_scores"] = {
        result.opponent_id: float(result.score)
        for result in game_metrics.opponent_results
    }
    game_payload["game_performance"] = (
        game_metrics.objective
        if opponent_pool is not None
        else reporting_game_performance(opponent_case_scores)
    )
    game_payload["evaluation_configuration"] = {
        "maps": list(config.evaluation_maps),
        "rounds_per_map": config.rounds_per_map,
        "swap_player_sides": config.swap_player_sides,
        "expected_match_count": expected_match_count,
        "mode": config.evaluation_mode,
    }
    game_payload["fitness_case_ids"] = (
        ["game_performance"]
        if config.evaluation_mode == "self_play"
        else list(config.lexicase_case_ids)
    )
    if opponent_pool is not None:
        context_rows = [
            {
                "slot_id": opponent.opponent_id,
                "source_candidate_id": opponent.source_candidate_id,
                "source_generation": opponent.source_generation,
            }
            for opponent in opponent_pool
        ]
        game_payload["evaluation_context_id"] = hashlib.sha256(
            json.dumps(
                context_rows,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        game_payload["evaluation_configuration"]["opponents"] = context_rows
    compact_matches = [_compact_match_result(result) for result in matches]
    # This is the hand-off consumed by the next generation's Reflection stage.
    # Keep the exact evaluated values together so mutation never reconstructs
    # evidence from legacy metadata keys or recalculates an objective.
    reflection_evidence = {
        "schema_version": "phase4-reflection-context-v1",
        "candidate_id": candidate.id,
        "objectives": dict(objectives),
        "game_performance": game_payload["game_performance"],
        "evaluation_status": "failed" if failure_category else "evaluated",
        "failure_stage": failure_stage,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
        "generation": {
            "phenotype_artifact": (
                "phenotype/CandidateAgent.java" if compiler.compile_success else None
            ),
            "failure_source_artifact": (
                None if compiler.compile_success else (
                    "generation/failed_candidate.java" if source_without_generation else
                    f"generation/attempts/attempt_{bounded_generation.final_attempt:03d}/normalized_candidate.java"
                )
            ),
            "validation": generation.validation_result.to_json_dict(),
            "strategy_region_validation": {
                key: value.to_json_dict()
                for key, value in region_score.strategy_region_validation.items()
            },
        },
        "compilation": _compact_compilation_evidence(compile_result),
        "integration": _compact_integration_evidence(integration_result),
    }
    timing = {
        **candidate.timing,
        "generation_llm": generation_timing,
        "validation_duration_seconds": sum(
            float(item.generation.validation_timing.get("duration_seconds") or 0.0)
            for item in generation_attempts
        ),
        "compilation_duration_seconds": compilation_duration or 0.0,
        "integration_duration_seconds": 0.0 if integration_result is None else integration_result.duration_seconds,
        "evaluation_duration_seconds": evaluation_duration,
        "matches_total_duration_seconds": round(sum(match_durations), 9),
        "match_durations_seconds": match_durations,
        "objective_calculation_duration_seconds": objective_duration,
        "validation": {
            **generation.validation_timing,
            "attempts": [
                {
                    "attempt": item.attempt,
                    **item.generation.validation_timing,
                }
                for item in generation_attempts
            ],
        },
        "compilation": {
            "started_at": compilation_started_at,
            "finished_at": compilation_finished_at,
            "duration_seconds": representative_compilation_duration,
            "status": "success" if compile_result is not None and compile_result.ok else ("failed" if compile_result is not None else "blocked"),
            "error": compile_error or (failure_reason if compile_result is None else None),
        },
        "integration": {
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "status": "blocked",
            "error": failure_reason or "Integration was not run because an earlier stage failed.",
        } if integration_result is None else {
            "started_at": integration_result.started_at,
            "finished_at": integration_result.finished_at,
            "duration_seconds": integration_result.duration_seconds,
            "status": integration_result.status,
            "error": integration_result.failure_reason,
        },
        "evaluation": {
            "started_at": evaluation_started_at,
            "finished_at": evaluation_finished_at,
            "duration_seconds": evaluation_duration,
            "status": (
                "blocked" if evaluation_started_at is None else "success" if failure_stage is None else "failed"
            ),
            "error": failure_reason,
        },
        "objective_calculation": {
            "started_at": objective_started_at,
            "finished_at": objective_finished_at,
            "duration_seconds": objective_duration,
            "status": "success",
            "error": None,
        },
        "semantic_probe": {
            "duration_seconds": semantic_result.duration_seconds,
            "status": semantic_result.status,
            "error": semantic_result.wrapper.get("failure_reason"),
            "cache_hit": semantic_result.wrapper.get("cache_hit"),
        },
    }
    mutation_generation = timing.get("mutation", {}).get("generation_only_duration_seconds", 0.0)
    crossover_generation = timing.get("crossover", {}).get("generation_only_duration_seconds", 0.0)
    generation_llm_duration = timing["generation_llm"].get("duration_seconds") or 0.0
    validation_duration = timing["validation_duration_seconds"]
    compilation_duration_value = timing["compilation_duration_seconds"]
    evaluation_duration_value = timing["evaluation"].get("duration_seconds") or 0.0
    operation_generation = float(mutation_generation or 0.0) + float(crossover_generation or 0.0)
    timing["mutation_generation"] = timing.get("mutation") if timing.get("mutation") else None
    timing["crossover_generation"] = timing.get("crossover") if timing.get("crossover") else None
    timing["child_generation"] = {
        "operation_type": candidate.operator,
        "started_at": (timing.get("mutation") or timing.get("crossover") or {}).get("started_at"),
        "finished_at": (timing.get("mutation") or timing.get("crossover") or {}).get("finished_at"),
        "duration_seconds": operation_generation,
    }
    timing["child_total"] = {
        "duration_seconds": operation_generation + float(generation_llm_duration) + validation_duration + compilation_duration_value + float(timing["integration"].get("duration_seconds") or 0.0) + evaluation_duration_value,
        "includes": ["mutation_generation", "crossover_generation", "generation_llm", "validation", "compilation", "integration", "evaluation"],
        "status": "failed" if failure_stage else "success",
        "failure_stage": failure_stage,
    }
    # Stage 7: rebuild the candidate with evaluated phenotype, objectives,
    # lineage, failure state, reflection evidence, and timing.
    evaluated_candidate = Candidate(
        id=candidate.id,
        generation=candidate.generation,
        parent_ids=candidate.parent_ids,
        strategy_prompt=candidate.strategy_prompt,
        generation_prompt=candidate.generation_prompt,
        inherited_java=candidate.inherited_java,
        java_parent_id=candidate.java_parent_id,
        generated_java=generation.assembled_java if compiler.compile_success else "",
        generated_java_path=(
            str(agent.source_path) if agent is not None and compiler.compile_success else None
        ),
        operator=candidate.operator,
        mutation_type=candidate.mutation_type,
        strategy_parent_id=candidate.strategy_parent_id,
        generation_prompt_parent_id=candidate.generation_prompt_parent_id,
        source_candidate_ids=candidate.source_candidate_ids,
        compile_status=compile_result.status if compile_result else "not_run",
        game_eval_result=game_payload,
        code_quality_result=quality_payload,
        fitness_objectives=objectives,
        semantic_signature=semantic_result.summary,
        strategy_signature=dict(candidate.strategy_signature),
        strategy_niche=candidate.strategy_niche,
        mutation_intent=candidate.mutation_intent,
        parent_strategy_niche=candidate.parent_strategy_niche,
        niche_changed=candidate.niche_changed,
        status="failed" if failure_category else "evaluated",
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        artifacts=candidate.artifacts,
        timing=timing,
        metadata=compact_candidate_metadata(
            {
                **candidate.metadata,
                "failure_category": failure_category,
                "failure_reason": failure_reason,
                "reflection_evidence": reflection_evidence,
            },
            preserve_unpersisted_mutation=True,
        ),
    )
    assert (
        evaluated_candidate.strategy_prompt,
        evaluated_candidate.generation_prompt,
        evaluated_candidate.inherited_java,
    ) == genotype_before
    result = CandidateResult(
        candidate_id=candidate.id,
        parent_ids=candidate.parent_ids,
        raw_llm_output=generation.raw_llm_output,
        extracted_code=generation.extracted_code,
        assembled_java=generation.assembled_java,
        strategy_region=generation.strategy_region,
        validation_result=generation.validation_result,
        strategy_region_validation={k: v.to_json_dict() for k, v in region_score.strategy_region_validation.items()},
        compile_result=compile_result,
        code_quality_breakdown=quality.to_json_dict(),
        match_result=compact_matches,
        game_metrics=game_payload,
        final_score=objectives,
        failure_category=failure_category,
        failure_reason=failure_reason,
        integration_result=integration_result,
        failure_stage=failure_stage,
    )
    return CandidateEvaluation(
        candidate=evaluated_candidate,
        result=result,
        agent=agent,
        compile_result=compile_result,
        integration_result=integration_result,
        match_results=compact_matches,
        game_metrics=game_metrics,
        strategy_consistency_result=None,
        code_quality_breakdown=quality,
        strategy_region_score_result=region_score,
        error=failure_reason,
        generation_timing=generation_timing,
        generation_attempts=generation_attempts,
        semantic_signature_result=semantic_result,
    )


def _compact_match_result(result: MatchResult) -> MatchResult:
    """Release large process/telemetry payloads after canonical persistence."""

    return replace(
        result,
        command=[],
        stdout="",
        stderr="",
        raw_result={},
        telemetry=None,
    )


def _compact_compilation_evidence(result: CompileResult | None) -> dict | None:
    if result is None:
        return None
    payload = result.to_json_dict()
    payload.pop("command", None)
    payload.pop("stdout", None)
    payload.pop("stderr", None)
    return payload


def _compact_integration_evidence(result: IntegrationResult | None) -> dict | None:
    if result is None:
        return None
    payload = result.to_json_dict()
    payload.pop("commands", None)
    payload.pop("stdout", None)
    payload.pop("stderr", None)
    return payload


def print_progress(*, generation: int, index: int, population_size: int, evaluation: CandidateEvaluation) -> None:
    candidate = evaluation.candidate
    quality = evaluation.code_quality_breakdown
    game_metrics = evaluation.game_metrics
    match_scores = [] if game_metrics is None else list(
        getattr(game_metrics, "opponent_scores", ())
        or [
            summary.get("performance")
            for summary in getattr(game_metrics, "match_summaries", ())
            if summary.get("performance") is not None
        ]
    )
    game_performance_detail = (
        f" game_performance_matches={match_scores}"
        f" aggregate_game_performance={getattr(game_metrics, 'objective', None) if game_metrics else None}"
    )
    detail = ""
    if evaluation.error:
        detail = f" error={evaluation.error}"
    elif evaluation.compile_result is not None and not evaluation.compile_result.ok:
        diagnostics = evaluation.compile_result.errors
        detail = f" compile_error={(diagnostics[0].message if diagnostics else evaluation.compile_result.returncode)}"
    print(
        f"[gen {generation} cand {index + 1}/{population_size}] "
        f"{candidate.id} status={candidate.status} "
        f"fitness_objectives={candidate.fitness_objectives} "
        f"{game_performance_detail} "
        f"code_quality_simplicity={quality.code_quality} "
        f"complexity_penalty={quality.complexity_penalty} "
        f"(cyclomatic={quality.cyclomatic_penalty}, nesting={quality.nesting_penalty}, "
        f"logical_loc={quality.logical_loc_penalty}, longest_function={quality.longest_function_penalty}){detail}",
        flush=True,
    )
