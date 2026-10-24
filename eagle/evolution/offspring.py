"""Offspring assignment, mutation, materialization, and evidence helpers."""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.determinism import derive_candidate_id, derive_seed
from eagle.execution import LLM_WORKERS, llm_worker_slot, parallel_map
from eagle.generation.framework_slots import load_framework_bundle, validate_genome
from eagle.operators.adaptive import (
    OPERATOR_TO_MUTATION,
    ReflectionOperatorController,
)
from eagle.operators.context import ReflectionContext, build_reflection_context
from eagle.operators.crossover import CrossoverContext, crossover
from eagle.operators.framework_slots import (
    crossover_framework_slots,
    mutate_framework_slot,
)
from eagle.operators.selection import select_parent
from eagle.operators.strategy import select_strategy_mutation_intent
from eagle.strategy_dsl import normalize_strategy_dsl
from eagle.timing import utc_now


@dataclass(frozen=True)
class OffspringPlan:
    """One fully assigned child before its mutation LLM call is made."""

    candidate: Candidate
    context_index: int
    mutation_name: str | None = None
    mutation: Any | None = None
    mutation_context: ReflectionContext | None = None
    mutation_intent: str | None = None
    parent_selection_duration: float = 0.0
    operator_id: str | None = None
    eligible_operator_ids: tuple[str, ...] = ()
    comparison_parent_id: str | None = None
    operator_mode: str | None = None
    probability_before: float | None = None


def plan_offspring(
    population: list[Candidate], *, config: ExperimentConfig, generation: int,
    rng: random.Random, mutations: dict[str, Any],
    operator_controller: ReflectionOperatorController, artifact_root: Path | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
) -> list[OffspringPlan]:
    """Collect canonical offspring plans for callers that need a complete batch."""

    return list(iter_offspring_plans(
        population, config=config, generation=generation, rng=rng,
        mutations=mutations, operator_controller=operator_controller,
        artifact_root=artifact_root, error_memory=error_memory,
    ))


def iter_offspring_plans(
    population: list[Candidate], *, config: ExperimentConfig, generation: int,
    rng: random.Random, mutations: dict[str, Any],
    operator_controller: ReflectionOperatorController, artifact_root: Path | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
) -> Iterator[OffspringPlan]:
    """Yield source-gated plans in canonical order while later gates are running.

    ``rng`` is accepted for embedded callers; its history cannot alter the EA.
    """

    del rng  # Streams use task identities, not call history.
    if config.java_materialization_mode == "framework_slots":
        yield from _iter_framework_slot_offspring(
            population,
            config=config,
            generation=generation,
            mutations=mutations,
        )
        return
    deterministic = config.java_materialization_mode == "deterministic_dsl"
    if not deterministic and "code" not in mutations:
        raise ValueError("Reproduction requires the independent Code Reflection gate.")
    population = sorted(population, key=lambda candidate: candidate.id)
    plans: list[OffspringPlan] = []
    generation_best = max(
        (item for item in population if item.game_eval_result),
        key=lambda item: (
            float((item.game_eval_result or {}).get("game_performance", float("-inf"))),
            item.id,
        ),
        default=None,
    )
    assignments = []
    for context_index in range(config.population_size):
        parent_a_rng = random.Random(derive_seed(config.random_seed, "evolution", generation, context_index, "parent_a"))
        parent_b_rng = random.Random(derive_seed(config.random_seed, "evolution", generation, context_index, "parent_b"))
        crossover_rng = random.Random(derive_seed(config.random_seed, "evolution", generation, context_index, "crossover"))
        parent_selection_started = time.monotonic()
        parent_a = select_parent(
            population,
            parent_a_rng,
            selection_mode=config.algorithm,
            fitness_tolerance=config.fitness_tie_tolerance,
        )
        parent_b = select_parent(
            population,
            parent_b_rng,
            selection_mode=config.algorithm,
            fitness_tolerance=config.fitness_tie_tolerance,
            semantic_reference=parent_a,
        )
        parent_selection_duration = max(0.0, time.monotonic() - parent_selection_started)
        use_crossover = len(population) > 1 and crossover_rng.random() < config.crossover_rate
        assignments.append((context_index, parent_a, parent_b, parent_selection_duration,
                            use_crossover, crossover_rng))

    def check_sources(assignment):
        context_index, parent_a, parent_b, parent_selection_duration, use_crossover, _ = assignment
        checked = []
        healthy_check_timings = []
        blocked = None
        check_timing = {}
        gate_sources = () if deterministic else (
            (("source", parent_a), ("donor", parent_b)) if use_crossover else (("source", parent_a),)
        )
        for role, source in gate_sources:
            gate_child = replace(
                source,
                id=derive_candidate_id(config.random_seed, generation=generation, index=context_index,
                                       role="code_gate_" + role, parent_ids=(source.id,)),
                generation=generation, parent_ids=(source.id,), source_candidate_ids=(source.id,),
                strategy_parent_id=source.id, generation_prompt_parent_id=source.id,
                java_parent_id=source.id, inherited_java=source.generated_java or source.inherited_java,
                generated_java="", generated_java_path=None, metadata={}, timing={}, artifacts={}, operator="code_check",
                mutation_type="code", mutation_intent=None, parent_strategy_niche=None, niche_changed=None,
                status="pending", compile_status="pending",
                game_eval_result={}, code_quality_result={}, fitness_objectives={}, semantic_signature={},
                failure_stage=None, failure_reason=None,
            )
            gate_context = mutation_context_from_candidate(
                source, generation=generation, index=context_index, reflection_type="code",
                error_memory=error_memory, evolution_candidate=gate_child,
            )
            if artifact_root is not None:
                write_candidate_inputs(artifact_root, gate_child)
                write_candidate_snapshot(artifact_root, gate_child)
            gate_child = mutations["code"].mutate(
                gate_child, gate_context,
                artifact_dir=None if artifact_root is None else artifact_root / gate_child.id,
            )
            if artifact_root is not None:
                write_candidate_snapshot(artifact_root, gate_child)
            gate_record = dict(gate_child.metadata.get("mutation") or {})
            healthy = (gate_record.get("reflection_status") == "success"
                       and gate_record.get("revision_required") is False
                       and gate_record.get("revision_status") == "not_required")
            checked.append({"source_candidate_id": source.id, "gate_candidate_id": gate_child.id,
                            "healthy": healthy, "reflection_status": gate_record.get("reflection_status"),
                            "revision_required": gate_record.get("revision_required"),
                            "artifact_path": f"../{gate_child.id}/mutation/code_reflection"})
            if healthy:
                healthy_check_timings.append({"gate_candidate_id": gate_child.id,
                                              **(gate_child.timing.get("code_reflector_llm") or {})})
            check_timing = {
                "duration_seconds": sum(float(item.get("duration_seconds") or 0.0)
                                        for item in healthy_check_timings),
                "checks": list(healthy_check_timings),
            }
            if not healthy:
                gate_child = replace(gate_child, operator="mutation", mutation_type="code",
                                     generated_java=source.generated_java or source.inherited_java,
                                     metadata={**gate_child.metadata, "pre_crossover_code_checks": checked},
                                     timing={**gate_child.timing, "pre_crossover_code_checks_llm": check_timing})
                if artifact_root is not None:
                    write_candidate_inputs(artifact_root, gate_child)
                    write_candidate_snapshot(artifact_root, gate_child)
                blocked = OffspringPlan(candidate=gate_child, context_index=context_index,
                                        mutation_name="code", mutation=mutations["code"],
                                        mutation_context=gate_context,
                                        parent_selection_duration=parent_selection_duration)
                break
        return checked, check_timing, blocked

    def check_indexed(assignment):
        with llm_worker_slot(assignment[0]):
            return check_sources(assignment)

    executor = ThreadPoolExecutor(max_workers=LLM_WORKERS, thread_name_prefix="eagle-gate")
    try:
        gate_results = executor.map(check_indexed, assignments)
        for assignment, (checked, check_timing, blocked) in zip(assignments, gate_results, strict=True):
            context_index, parent_a, parent_b, parent_selection_duration, use_crossover, crossover_rng = assignment
            if blocked is not None:
                plans.append(blocked)
                yield blocked
                continue
            mutation_rng = random.Random(derive_seed(config.random_seed, "evolution", generation, context_index, "mutation"))
            operator_rng = random.Random(derive_seed(config.random_seed, "evolution", generation, context_index, "operator"))
            intent_rng = random.Random(derive_seed(config.random_seed, "evolution", generation, context_index, "intent"))
            if use_crossover:
                crossover_started_at = utc_now()
                crossover_started = time.monotonic()
                child = crossover(parent_a, parent_b, CrossoverContext(
                    generation=generation,
                    index=context_index,
                    rng=crossover_rng,
                    inherit_java=config.candidate_java_mode == "inherited_genotype",
                    strategy_only=deterministic,
                    random_seed=config.random_seed,
                ))
                crossover_duration = max(0.0, time.monotonic() - crossover_started)
                child = replace(child, timing={
                    **child.timing,
                    "crossover": {
                        "operation_type": "crossover",
                        "started_at": crossover_started_at,
                        "finished_at": utc_now(),
                        "generation_only_duration_seconds": crossover_duration,
                        "parent_selection_duration_seconds": parent_selection_duration,
                        "status": "success",
                        "error": None,
                    },
                })
            else:
                child = Candidate(
                    id=(
                        derive_candidate_id(
                            config.random_seed,
                            generation=generation,
                            index=context_index,
                            role="copy",
                            parent_ids=(parent_a.id,),
                        )
                    ),
                    generation=generation,
                    parent_ids=(parent_a.id,),
                    strategy_prompt=normalize_strategy_dsl(
                        parent_a.strategy_prompt, max_chars=config.max_prompt_chars,
                    ),
                    strategy_signature=dict(parent_a.strategy_signature),
                    strategy_niche=parent_a.strategy_niche,
                    candidate_java_mode=config.candidate_java_mode,
                    java_materialization_mode=config.java_materialization_mode,
                    java_compiler_version=config.java_compiler_version if deterministic else None,
                    generation_prompt="" if deterministic else parent_a.generation_prompt,
                    operator="copy",
                    strategy_parent_id=parent_a.id,
                    generation_prompt_parent_id=None if deterministic else parent_a.id,
                    inherited_java=(
                        parent_a.generated_java or parent_a.inherited_java
                        if config.candidate_java_mode == "inherited_genotype" else ""
                    ),
                    java_parent_id=(
                        parent_a.id
                        if config.candidate_java_mode == "inherited_genotype" else None
                    ),
                    source_candidate_ids=(parent_a.id,),
                )
            if not deterministic:
                child = replace(child, metadata={**child.metadata, "pre_crossover_code_checks": checked},
                                timing={**child.timing, "pre_crossover_code_checks_llm": check_timing})
            progress_prefix = (
                f"[gen {generation} cand {context_index + 1}/{config.population_size}] "
                f"{child.id}"
            )
            mutation_name: str | None = None
            mutation = None
            mutation_context: ReflectionContext | None = None
            mutation_intent: str | None = None
            operator_used: str | None = None
            eligible_operators: tuple[str, ...] = ()
            feedback_parent: Candidate | None = None
            if mutation_rng.random() < config.mutation_rate and config.reflection_operator_settings.enabled_operators:
                eligible_operators = config.reflection_operator_settings.enabled_operators
                operator_used = operator_controller.select_operator(
                    operator_rng,
                    eligible=eligible_operators,
                )
                mutation_name = OPERATOR_TO_MUTATION[operator_used]
                mutation = mutations[mutation_name]
                # Reflection evidence must describe the evaluated source of the
                # gene being mutated.  This avoids reviewing one parent's Java as
                # if it had been produced by the other parent's translation gene.
                feedback_parent = mutation_evidence_parent(
                    child,
                    mutation_name=mutation_name,
                    candidate_java_mode=config.candidate_java_mode,
                    parents=(parent_a, parent_b),
                )
                if mutation_name == "strategy":
                    mutation_intent = select_strategy_mutation_intent(rng=intent_rng)
                    child = replace(
                        child,
                        mutation_intent=mutation_intent,
                        parent_strategy_niche=feedback_parent.strategy_niche,
                    )
                parent_objectives = {
                    parent.id: dict(parent.fitness_objectives)
                    for parent in (parent_a, parent_b)
                }
                reference_candidates = {parent.id: parent for parent in (parent_a, parent_b)}
                if generation_best is not None:
                    reference_candidates["generation_best"] = generation_best
                mutation_context = mutation_context_from_candidate(
                    feedback_parent,
                    generation=generation,
                    index=context_index,
                    reflection_type=mutation_name,
                    error_memory=error_memory,
                    evolution_candidate=child,
                    parent_objectives=parent_objectives,
                    reference_candidates=reference_candidates,
                )
            plans.append(OffspringPlan(
                candidate=child,
                context_index=context_index,
                mutation_name=mutation_name,
                mutation=mutation,
                mutation_context=mutation_context,
                mutation_intent=mutation_intent,
                parent_selection_duration=parent_selection_duration,
                operator_id=operator_used,
                eligible_operator_ids=tuple(eligible_operators),
                comparison_parent_id=None if feedback_parent is None else feedback_parent.id,
                operator_mode=(
                    None if operator_used is None else operator_controller.mode.value
                ),
                probability_before=(
                    None
                    if operator_used is None
                    else operator_controller.probability(operator_used)
                ),
            ))
            yield plans[-1]
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    assignments = ", ".join(
        f"{plan.context_index + 1}:{plan.candidate.operator}/{plan.mutation_name or 'none'}"
        for plan in plans
    )
    print(
        f"[gen {generation}] stage=offspring_plan status=completed assignments={assignments}",
        flush=True,
    )


def _iter_framework_slot_offspring(
    population: list[Candidate],
    *,
    config: ExperimentConfig,
    generation: int,
    mutations: dict[str, Any],
) -> Iterator[OffspringPlan]:
    """Plan typed-slot variation, optionally routing Coach before crossover."""

    if config.framework_bundle_path is None or config.framework_bundle_sha256 is None:
        raise ValueError("framework_slots reproduction requires a validated bundle.")
    bundle = load_framework_bundle(
        config.framework_bundle_path,
        expected_sha256=config.framework_bundle_sha256,
    )
    population = sorted(population, key=lambda candidate: candidate.id)
    for parent in population:
        if parent.java_materialization_mode != "framework_slots":
            raise ValueError("framework_slots reproduction requires framework parents.")
        if parent.framework_bundle_sha256 != config.framework_bundle_sha256:
            raise ValueError(
                f"Parent {parent.id} framework bundle hash does not match the run bundle."
            )
        validate_genome(bundle, parent.control_genome)

    framework_coach = config.framework_evolution_mode == "llm_coach"
    route_probability = config.framework_coach_offspring_probability
    if framework_coach and (route_probability is None or route_probability > 0) and "strategy" not in mutations:
        raise ValueError("framework llm_coach reproduction requires the Strategy Coach.")
    plans: list[OffspringPlan] = []
    for context_index in range(config.population_size):
        parent_a_rng = random.Random(
            derive_seed(config.random_seed, "evolution", generation, context_index, "parent_a")
        )
        parent_b_rng = random.Random(
            derive_seed(config.random_seed, "evolution", generation, context_index, "parent_b")
        )
        crossover_rng = random.Random(
            derive_seed(config.random_seed, "evolution", generation, context_index, "crossover")
        )
        selection_started = time.monotonic()
        parent_a = select_parent(
            population,
            parent_a_rng,
            selection_mode=config.algorithm,
            fitness_tolerance=config.fitness_tie_tolerance,
        )
        coach_route = False
        if framework_coach and route_probability is not None:
            route_rng = random.Random(
                derive_seed(config.random_seed, "evolution", generation, context_index, "framework_offspring_route")
            )
            coach_route = route_rng.random() < route_probability
        parent_b = None
        if not coach_route:
            parent_b = select_parent(
                population,
                parent_b_rng,
                selection_mode=config.algorithm,
                fitness_tolerance=config.fitness_tie_tolerance,
                semantic_reference=parent_a,
            )
        parent_selection_duration = max(0.0, time.monotonic() - selection_started)
        use_crossover = not coach_route and len(population) > 1 and crossover_rng.random() < config.crossover_rate

        operation_started_at = utc_now()
        operation_started = time.monotonic()
        if use_crossover:
            assert parent_b is not None
            crossed = crossover_framework_slots(
                bundle,
                parent_a.control_genome,
                parent_b.control_genome,
                parent_a_id=parent_a.id,
                parent_b_id=parent_b.id,
                random_seed=config.random_seed,
                generation=generation,
                child_index=context_index,
            )
            parent_ids = tuple(dict.fromkeys((parent_a.id, parent_b.id)))
            source_candidate_ids = crossed.source_parent_ids
            genome = crossed.genome
            slot_parent_ids = crossed.slot_parent_ids
            operator = "crossover"
            role = "crossover"
        else:
            genome = validate_genome(bundle, parent_a.control_genome)
            slot_parent_ids = {slot.slot_id: parent_a.id for slot in bundle.slots}
            parent_ids = (parent_a.id,)
            source_candidate_ids = (parent_a.id,)
            operator = "copy"
            role = "copy"
        operation_duration = max(0.0, time.monotonic() - operation_started)

        mutation_rng = random.Random(
            derive_seed(config.random_seed, "evolution", generation, context_index, "mutation")
        )
        mutation_record: dict[str, Any] | None = None
        mutation_timing: dict[str, Any] | None = None
        mutation_type: str | None = None
        use_mutation = mutation_rng.random() < config.mutation_rate
        # An explicit route replaces reproduction; omitted probability keeps old runs compatible.
        use_coach_mutation = coach_route or (framework_coach and route_probability is None and use_mutation)
        if use_mutation and not use_coach_mutation:
            mutation_started_at = utc_now()
            mutation_started = time.monotonic()
            mutated = mutate_framework_slot(
                bundle,
                genome,
                random_seed=config.random_seed,
                generation=generation,
                child_index=context_index,
                slot_parent_ids=slot_parent_ids,
            )
            genome = mutated.genome
            slot_parent_ids = mutated.slot_parent_ids
            source_candidate_ids = mutated.source_parent_ids
            mutation_type = "slot" if mutated.applied else None
            mutation_record = {
                "operation": "framework_slot_mutation",
                "applied": mutated.applied,
                "slot_id": mutated.mutated_slot_id,
                "previous_value": mutated.previous_value,
                "new_value": mutated.new_value,
            }
            mutation_timing = {
                "operation_type": "framework_slot_mutation",
                "started_at": mutation_started_at,
                "finished_at": utc_now(),
                "generation_only_duration_seconds": max(
                    0.0, time.monotonic() - mutation_started
                ),
                "status": "success" if mutated.applied else "skipped",
                "error": None,
            }

        candidate_id = derive_candidate_id(
            config.random_seed,
            generation=generation,
            index=context_index,
            role=role,
            parent_ids=parent_ids,
        )
        timing = {
            operator: {
                "operation_type": operator,
                "started_at": operation_started_at,
                "finished_at": utc_now(),
                "generation_only_duration_seconds": operation_duration,
                "parent_selection_duration_seconds": parent_selection_duration,
                "status": "success",
                "error": None,
            }
        }
        if mutation_timing is not None:
            timing["mutation"] = mutation_timing
        metadata: dict[str, Any] = {"framework_id": bundle.framework_id}
        if route_probability is not None:
            metadata["framework_reproduction_route"] = "coach" if coach_route else "traditional"
        if mutation_record is not None:
            metadata["mutation"] = mutation_record
        child = Candidate(
            id=candidate_id,
            generation=generation,
            parent_ids=parent_ids,
            candidate_java_mode=config.candidate_java_mode,
            java_materialization_mode="framework_slots",
            java_compiler_version=config.java_compiler_version,
            control_genome=genome,
            strategy_description=parent_a.strategy_description,
            slot_parent_ids=slot_parent_ids,
            framework_bundle_sha256=config.framework_bundle_sha256,
            generation_prompt="",
            operator=operator,
            mutation_type=mutation_type,
            source_candidate_ids=source_candidate_ids,
            timing=timing,
            metadata=metadata,
        )
        mutation_context = None
        if use_coach_mutation:
            mutation_context = mutation_context_from_candidate(
                parent_a, generation=generation, index=context_index,
                reflection_type="strategy", evolution_candidate=child,
            )
            mutation_context = replace(
                mutation_context,
                parent_comparison={
                    **mutation_context.parent_comparison,
                    "framework_control_genome": dict(parent_a.control_genome),
                },
            )
        plans.append(
            OffspringPlan(
                candidate=child,
                context_index=context_index,
                parent_selection_duration=parent_selection_duration,
                mutation_name="strategy" if mutation_context is not None else None,
                mutation=mutations.get("strategy") if mutation_context is not None else None,
                mutation_context=mutation_context,
                comparison_parent_id=parent_a.id if mutation_context is not None else None,
            )
        )

        yield plans[-1]

    assignments = ", ".join(
        f"{plan.context_index + 1}:{plan.candidate.operator}/"
        f"{plan.candidate.mutation_type or 'none'}"
        for plan in plans
    )
    print(
        f"[gen {generation}] stage=offspring_plan status=completed assignments={assignments}",
        flush=True,
    )


def apply_offspring_mutations(
    plans: list[OffspringPlan],
    *,
    artifact_root: Path | None = None,
) -> list[OffspringPlan]:
    """Run independent candidate operations and retain canonical result order."""

    return parallel_map(
        lambda plan: apply_offspring_mutation(plan, artifact_root=artifact_root, total_count=len(plans)),
        plans,
    )


def apply_offspring_mutation(
    plan: OffspringPlan,
    *,
    artifact_root: Path | None = None,
    total_count: int | None = None,
) -> OffspringPlan:
    """Run one candidate reflection/rewrite in the caller worker slot."""

    child = plan.candidate
    progress_prefix = (
        f"[gen {child.generation} cand {plan.context_index + 1}/{total_count or plan.context_index + 1}] "
        f"{child.id}"
    )
    if plan.mutation is None or plan.mutation_name is None or plan.mutation_name == "code":
        print(
            f"{progress_prefix} stage=mutation status=skipped operator=none",
            flush=True,
        )
        return plan
    assert plan.mutation_context is not None
    print(
        f"{progress_prefix} stage=mutation status=started operator={plan.mutation_name}",
        flush=True,
    )
    mutation_started_at = utc_now()
    mutation_started = time.monotonic()
    if plan.mutation_name == "strategy":
        child = plan.mutation.mutate(
            child,
            plan.mutation_context,
            artifact_dir=(artifact_root / child.id) if artifact_root is not None else None,
            mutation_intent=plan.mutation_intent,
        )
    else:
        child = plan.mutation.mutate(
            child,
            plan.mutation_context,
            artifact_dir=(artifact_root / child.id) if artifact_root is not None else None,
        )
    mutation_record = child.metadata.get("mutation") or {}
    mutation_applied = bool(mutation_record.get("applied"))
    framework_selected = (
        child.java_materialization_mode == "framework_slots"
        and mutation_record.get("reflection_status") == "success"
        and child.failure_stage is None
    )
    code_diagnosed = (
        plan.mutation_name == "code"
        and mutation_record.get("reflection_status") == "success"
    )
    mutation_error = (
        mutation_record.get("reflection_error")
        or mutation_record.get("rewrite_error")
        or mutation_record.get("revision_error")
    )
    child = replace(child, timing={
        **child.timing,
        "mutation": {
            "operation_type": "mutation",
            "phase": "reflection_and_prompt_rewrite",
            "started_at": mutation_started_at,
            "finished_at": utc_now(),
            "generation_only_duration_seconds": max(0.0, time.monotonic() - mutation_started),
            "parent_selection_duration_seconds": plan.parent_selection_duration,
            "status": "success" if mutation_applied or code_diagnosed or framework_selected else "failed",
            "error": mutation_error,
        },
    })
    child = replace(child, metadata={
        **child.metadata,
        "aos": {
            "generation": child.generation,
            "comparison_parent_id": plan.comparison_parent_id,
            "offspring_id": child.id,
            "operator": plan.mutation_name,
            "operator_id": plan.operator_id,
            "mode": plan.operator_mode,
            "probability_before": plan.probability_before,
            "eligible_operator_ids": list(plan.eligible_operator_ids),
        },
    })
    mutation_status = "completed" if mutation_applied or code_diagnosed or framework_selected else "failed"
    pending_suffix = (
        " materialization=pending"
        if mutation_record.get("revision_status") == "pending"
        else ""
    )
    mutation_error_detail = (
        f" error={str(mutation_error).replace(chr(10), ' ')[:300]}"
        if mutation_error
        else ""
    )
    print(
        f"{progress_prefix} stage=mutation status={mutation_status} "
        f"operator={plan.mutation_name} applied={str(mutation_applied).lower()}"
        f"{pending_suffix}{mutation_error_detail}",
        flush=True,
    )
    return replace(plan, candidate=child)


def materialize_code_reflections(
    plans: list[OffspringPlan],
    *,
    artifact_root: Path | None = None,
) -> list[OffspringPlan]:
    """Run independent candidate operations and retain canonical result order."""

    return parallel_map(
        lambda plan: materialize_code_reflection(plan, artifact_root=artifact_root, total_count=len(plans)),
        plans,
    )


def materialize_code_reflection(
    plan: OffspringPlan,
    *,
    artifact_root: Path | None = None,
    total_count: int | None = None,
) -> OffspringPlan:
    """Run one deferred Code revision in the caller worker slot."""

    child = plan.candidate
    if plan.mutation_name != "code" or plan.mutation is None:
        return plan
    assert plan.mutation_context is not None
    print(
        f"[gen {child.generation} cand {plan.context_index + 1}/{total_count or plan.context_index + 1}] "
        f"{child.id} stage=materialization status=started operator=code",
        flush=True,
    )
    child = plan.mutation.materialize(
        child,
        plan.mutation_context,
        artifact_dir=(artifact_root / child.id) if artifact_root is not None else None,
    )
    revision_status = (child.metadata.get("mutation") or {}).get("revision_status")
    print(
        f"[gen {child.generation} cand {plan.context_index + 1}/{total_count or plan.context_index + 1}] "
        f"{child.id} stage=materialization status=completed operator=code "
        f"revision_status={revision_status}",
        flush=True,
    )
    return replace(plan, candidate=child)


def create_offspring(
    population: list[Candidate], *, config: ExperimentConfig, generation: int,
    rng: random.Random, mutations: dict[str, Any],
    operator_controller: ReflectionOperatorController, artifact_root: Path | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
) -> list[Candidate]:
    """Execute assignment, mutation, and materialization for one generation."""

    plans = plan_offspring(
        population,
        config=config,
        generation=generation,
        rng=rng,
        mutations=mutations,
        operator_controller=operator_controller,
        artifact_root=artifact_root,
        error_memory=error_memory,
    )
    plans = apply_offspring_mutations(plans, artifact_root=artifact_root)
    plans = materialize_code_reflections(plans, artifact_root=artifact_root)
    return [plan.candidate for plan in plans]


def parent_for_component(parent_id: str | None, parents: tuple[Candidate, Candidate]) -> Candidate:
    for parent in parents:
        if parent.id == parent_id:
            return parent
    raise ValueError(f"Recorded component parent {parent_id!r} is not a direct parent.")


def mutation_evidence_parent(
    child: Candidate,
    *,
    mutation_name: str,
    candidate_java_mode: str,
    parents: tuple[Candidate, Candidate],
) -> Candidate:
    """Resolve the evaluated parent that owns one mutation's evidence."""

    if mutation_name == "strategy":
        parent_id = child.strategy_parent_id
    elif mutation_name in {"prompt", "code"}:
        parent_id = (
            child.java_parent_id
            if candidate_java_mode == "inherited_genotype"
            else child.generation_prompt_parent_id
        )
    else:
        raise ValueError(f"Unknown mutation name: {mutation_name!r}.")
    return parent_for_component(parent_id, parents)


def mutation_context_from_candidate(
    candidate: Candidate,
    *,
    generation: int,
    index: int,
    reflection_type: str | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
    evolution_candidate: Candidate | None = None,
    parent_objectives: dict[str, dict[str, float]] | None = None,
    reference_candidates: dict[str, Candidate] | None = None,
) -> ReflectionContext:
    return build_reflection_context(
        candidate,
        generation=generation,
        index=index,
        reflection_type=reflection_type,
        error_memory=error_memory,
        evolution_candidate=evolution_candidate,
        parent_objectives=parent_objectives,
        reference_candidates=reference_candidates,
    )
