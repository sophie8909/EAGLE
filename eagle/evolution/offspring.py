"""Offspring assignment, mutation, materialization, and evidence helpers."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.operators.adaptive import (
    OPERATOR_TO_MUTATION,
    STRATEGY_REFLECTION,
    ReflectionOperatorController,
)
from eagle.operators.context import ReflectionContext, build_reflection_context
from eagle.operators.crossover import CrossoverContext, crossover
from eagle.operators.selection import select_parent
from eagle.operators.strategy import select_strategy_mutation_intent
from eagle.prompts import normalize_prompt
from eagle.timing import utc_now


@dataclass(frozen=True)
class OffspringPlan:
    """One fully assigned child before any mutation LLM call is made."""

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
    """Assign every child's parents, crossover, and mutation before LLM work."""

    del artifact_root  # Planning is pure EA state assignment.
    plans: list[OffspringPlan] = []
    generation_best = max(
        (item for item in population if item.game_eval_result),
        key=lambda item: float(
            (item.game_eval_result or {}).get("game_performance", float("-inf"))
        ),
        default=None,
    )
    while len(plans) < config.population_size:
        context_index = len(plans)
        parent_selection_started = time.monotonic()
        parent_a = select_parent(
            population,
            rng,
            selection_mode=config.algorithm,
            fitness_tolerance=config.fitness_tie_tolerance,
        )
        parent_b = select_parent(
            population,
            rng,
            selection_mode=config.algorithm,
            fitness_tolerance=config.fitness_tie_tolerance,
            semantic_reference=parent_a,
        )
        parent_selection_duration = max(0.0, time.monotonic() - parent_selection_started)
        if len(population) > 1 and rng.random() < config.crossover_rate:
            crossover_started_at = utc_now()
            crossover_started = time.monotonic()
            child = crossover(parent_a, parent_b, CrossoverContext(
                generation=generation,
                index=context_index,
                rng=rng,
                inherit_java=config.candidate_java_mode == "inherited_genotype",
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
                generation=generation,
                parent_ids=(parent_a.id,),
                strategy_prompt=normalize_prompt(
                    parent_a.strategy_prompt,
                    max_chars=config.max_prompt_chars,
                    max_lines=config.max_prompt_lines,
                ),
                strategy_signature=dict(parent_a.strategy_signature),
                strategy_niche=parent_a.strategy_niche,
                generation_prompt=parent_a.generation_prompt,
                operator="copy",
                strategy_parent_id=parent_a.id,
                generation_prompt_parent_id=parent_a.id,
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
        if rng.random() < config.mutation_rate:
            eligible_operators = (
                (STRATEGY_REFLECTION,)
                if not child.strategy_prompt.strip()
                else config.reflection_operator_settings.enabled_operators
            )
            operator_used = operator_controller.select_operator(
                rng,
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
                mutation_intent = select_strategy_mutation_intent(rng=rng)
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
    assignments = ", ".join(
        f"{plan.context_index + 1}:{plan.candidate.operator}/{plan.mutation_name or 'none'}"
        for plan in plans
    )
    print(
        f"[gen {generation}] stage=offspring_plan status=completed assignments={assignments}",
        flush=True,
    )
    return plans


def apply_offspring_mutations(
    plans: list[OffspringPlan],
    *,
    artifact_root: Path | None = None,
) -> list[OffspringPlan]:
    """Run reflection/rewrite stages after the whole generation is assigned."""

    prepared: list[OffspringPlan] = []
    for plan in plans:
        child = plan.candidate
        progress_prefix = (
            f"[gen {child.generation} cand {plan.context_index + 1}/{len(plans)}] "
            f"{child.id}"
        )
        if plan.mutation is None or plan.mutation_name is None:
            print(
                f"{progress_prefix} stage=mutation status=skipped operator=none",
                flush=True,
            )
            prepared.append(plan)
            continue
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
                "status": "success" if mutation_applied or code_diagnosed else "failed",
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
        mutation_status = "completed" if mutation_applied or code_diagnosed else "failed"
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
        prepared.append(replace(plan, candidate=child))
    return prepared


def materialize_code_reflections(
    plans: list[OffspringPlan],
    *,
    artifact_root: Path | None = None,
) -> list[OffspringPlan]:
    """Run only deferred Code Reflection revisions in the common final phase."""

    materialized: list[OffspringPlan] = []
    for plan in plans:
        child = plan.candidate
        if plan.mutation_name != "code" or plan.mutation is None:
            materialized.append(plan)
            continue
        assert plan.mutation_context is not None
        print(
            f"[gen {child.generation} cand {plan.context_index + 1}/{len(plans)}] "
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
            f"[gen {child.generation} cand {plan.context_index + 1}/{len(plans)}] "
            f"{child.id} stage=materialization status=completed operator=code "
            f"revision_status={revision_status}",
            flush=True,
        )
        materialized.append(replace(plan, candidate=child))
    return materialized


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
