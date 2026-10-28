"""Transactional framework redesign at the self-play refresh barrier."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.compiler import compile_generated_agent
from eagle.evaluation.determinism import derive_candidate_id
from eagle.generation.framework_slots import (
    FrameworkBundle, canonical_json, load_framework_bundle, render_framework,
    slot_value_at, slot_value_count, validate_genome,
)
from eagle.generation.java_agent_generator import validate_generated_java_source
from eagle.llm import LLMCallLogger
from eagle.run_artifacts import atomic_json
from eagle.timing import utc_now


OPTION_REFLECTION_SCHEMA_VERSION = "eagle-framework-option-reflection-v1"


def initialize_framework_strategies(
    *, population: list[Candidate], config: ExperimentConfig, run_dir: Path,
    client: Any, mock: bool,
) -> list[Candidate]:
    """Fill generation-zero slots from the distinct authored strategy narratives."""

    from eagle.generation.framework_reflection import MAX_REPAIR_RETRIES, select_reflected_genomes

    if mock:
        return population
    bundle = load_framework_bundle(
        config.framework_bundle_path, expected_sha256=config.framework_bundle_sha256,
    )
    evidence = [{"candidate_id": candidate.id,
                 "strategy_description": candidate.strategy_description,
                 "control_genome": candidate.control_genome,
                 "fitness_objectives": {}, "evidence_generation": 0}
                for candidate in population]
    logger = LLMCallLogger(run_dir / "llm_logs", run_id=run_dir.name,
                           timing_path=run_dir / "timing.jsonl")
    last_error = None
    for attempt in range(1, MAX_REPAIR_RETRIES + 2):
        try:
            genomes = select_reflected_genomes(
                bundle=bundle, framework_bundle_sha256=config.framework_bundle_sha256,
                previous_bundle=bundle,
                population_evidence=[{**item, "previous_selection_error": last_error} for item in evidence],
                client=client, config=config,
                artifact_dir=run_dir / "initialization" / "framework_strategy" / f"attempt_{attempt:03d}",
                timing_logger=logger, generation=0,
            )
            return [replace(candidate, control_genome=genomes[candidate.id]) for candidate in population]
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            last_error = str(exc)
    raise ValueError(f"Initial strategy-guided framework slot selection failed: {last_error}")


def validate_framework_compilation(
    bundle: FrameworkBundle,
    *,
    genomes: list[dict[str, Any]],
    config: ExperimentConfig,
    artifact_dir: Path,
    mock: bool,
) -> None:
    """Check defaults, individual options/endpoints, and every Coach genome."""

    defaults = {slot.slot_id: slot.default for slot in bundle.slots}
    probes = [defaults, *genomes]
    for slot in bundle.slots:
        indices = (
            range(slot_value_count(slot)) if slot.choices
            else (0, slot_value_count(slot) - 1)
        )
        probes.extend({**defaults, slot.slot_id: slot_value_at(slot, i)} for i in indices)
    seen: set[str] = set()
    for genome in probes:
        source = render_framework(bundle, genome).source
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        probe_dir = artifact_dir / digest
        probe_dir.mkdir(parents=True, exist_ok=True)
        source_path = probe_dir / "CandidateAgent.java"
        source_path.write_text(source, encoding="utf-8")
        validation = validate_generated_java_source(
            source, "CandidateAgent", immutable_scaffold_source=bundle.java_template,
        )
        atomic_json(probe_dir / "validation.json", validation.to_json_dict())
        if not validation.ok:
            raise ValueError(json.dumps(validation.to_json_dict(), ensure_ascii=False))
        compiled = compile_generated_agent(
            source_path, microrts_dir=config.microrts_dir,
            output_dir=probe_dir / "classes", mock=mock,
        )
        atomic_json(probe_dir / "compilation.json", compiled.to_json_dict())
        if not compiled.ok:
            raise ValueError(json.dumps(compiled.to_json_dict(), ensure_ascii=False))


def reflect_population_framework(
    *,
    population: list[Candidate],
    config: ExperimentConfig,
    run_dir: Path,
    generation: int,
    client: Any,
    mock: bool,
) -> tuple[ExperimentConfig, list[Candidate] | None]:
    """Return validated boundary replicas, optionally with a new framework version."""

    from eagle.generation.framework_reflection import (
        MAX_REPAIR_RETRIES, reflect_framework, revise_strategy_descriptions,
        select_reflected_genomes,
    )

    previous = load_framework_bundle(
        config.framework_bundle_path, expected_sha256=config.framework_bundle_sha256,
    )
    option_only = config.framework_evolution_mode == "option_reflection"
    reflection_dir = "option_reflections" if option_only else "reflections"
    root = run_dir / "framework" / reflection_dir / f"generation_{generation:04d}"
    # Replayed unfinished generations retain their original LLM evidence.
    invocation = 1
    while (root / f"invocation_{invocation:03d}").exists():
        invocation += 1
    artifact_dir = root / f"invocation_{invocation:03d}"
    population_evidence = [
        {
            "candidate_id": parent.id,
            "birth_generation": parent.generation,
            "evidence_generation": generation - 1,
            "control_genome": dict(parent.control_genome),
            "strategy_description": parent.strategy_description,
            "fitness_objectives": dict(parent.fitness_objectives),
            "game_performance": parent.game_eval_result.get("game_performance"),
            "evaluation_context_id": parent.game_eval_result.get("evaluation_context_id"),
            "status": parent.status,
            "failure_stage": parent.failure_stage,
            "failure_reason": parent.failure_reason,
        }
        for parent in population
    ]
    check_index = 0
    selected_genomes: dict[str, dict[str, Any]] = {}
    revised_strategies: dict[str, str] = {}
    timing_logger = LLMCallLogger(
        run_dir / "llm_logs", run_id=run_dir.name,
        timing_path=run_dir / "timing.jsonl",
    )

    def validate_bundle(
        bundle: FrameworkBundle, *, repair_error: str | None = None,
    ) -> None:
        nonlocal check_index, selected_genomes, revised_strategies
        check_index += 1
        proposed_digest = (
            config.framework_bundle_sha256
            if bundle.to_json_dict() == previous.to_json_dict()
            else hashlib.sha256((canonical_json(bundle.to_json_dict()) + "\n").encode("utf-8")).hexdigest()
        )
        revised_strategies = revise_strategy_descriptions(
            previous_bundle=previous, bundle=bundle, population_evidence=population_evidence,
            client=client, config=config,
            artifact_dir=artifact_dir / "strategy_revision" / f"attempt_{check_index:03d}",
            timing_logger=timing_logger, generation=generation,
            option_only=option_only, repair_error=repair_error,
        )
        selected_genomes = select_reflected_genomes(
            bundle=bundle, framework_bundle_sha256=proposed_digest,
            previous_bundle=previous, population_evidence=[
                {**item, "previous_strategy_description": item["strategy_description"],
                 "strategy_description": revised_strategies[item["candidate_id"]]}
                for item in population_evidence
            ],
            client=client, config=config,
            artifact_dir=artifact_dir / "coach" / f"attempt_{check_index:03d}",
            timing_logger=timing_logger, generation=generation,
            option_only=option_only, repair_error=repair_error,
        )
        validate_framework_compilation(
            bundle, genomes=list(selected_genomes.values()), config=config, mock=mock,
            artifact_dir=artifact_dir / "compilation" / f"attempt_{check_index:03d}",
        )

    if mock:
        # Mock search never contacts an external model, including at a refresh.
        artifact_dir.mkdir(parents=True)
        atomic_json(artifact_dir / "result.json", {
            "schema_version": (
                OPTION_REFLECTION_SCHEMA_VERSION
                if option_only else "eagle-framework-reflection-v1"
            ),
            "status": "skipped_mock", "generation": generation,
        })
        return config, None
    if option_only:
        artifact_dir.mkdir(parents=True)
        atomic_json(artifact_dir / "previous_bundle.json", previous.to_json_dict())
        atomic_json(artifact_dir / "population_evidence.json", population_evidence)
        option_attempts = []
        last_error = None
        proposed = None
        for attempt in range(1, MAX_REPAIR_RETRIES + 2):
            started_at, started = utc_now(), time.monotonic()
            try:
                validate_bundle(previous, repair_error=last_error)
                proposed = previous
                option_attempts.append({
                    "schema_version": OPTION_REFLECTION_SCHEMA_VERSION,
                    "attempt": attempt,
                    "status": "success",
                    "error": None,
                    "model": config.llm_model,
                    "backend": config.execution_mode,
                    "operation": "framework_option_reflection",
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "duration_seconds": max(0.0, time.monotonic() - started),
                })
                break
            except (ValueError, TypeError, RuntimeError, OSError) as exc:
                last_error = str(exc)
                option_attempts.append({
                    "schema_version": OPTION_REFLECTION_SCHEMA_VERSION,
                    "attempt": attempt,
                    "status": "failed",
                    "error": last_error,
                    "model": config.llm_model,
                    "backend": config.execution_mode,
                    "operation": "framework_option_reflection",
                    "started_at": started_at,
                    "finished_at": utc_now(),
                    "duration_seconds": max(0.0, time.monotonic() - started),
                })
        atomic_json(artifact_dir / "result.json", {
            "schema_version": OPTION_REFLECTION_SCHEMA_VERSION,
            "status": "success" if proposed is not None else "rollback",
            "generation": generation,
            "framework_bundle_sha256": config.framework_bundle_sha256,
            "selected_attempt": len(option_attempts) if proposed is not None else None,
            "attempts": option_attempts,
            "error": last_error if proposed is None else None,
        })
    else:
        proposed = reflect_framework(
            previous_bundle=previous, population_evidence=population_evidence,
            client=client, config=config, artifact_dir=artifact_dir,
            validate_bundle=validate_bundle,
            timing_logger=timing_logger,
            generation=generation,
        )
    if proposed is None:
        return config, None
    data = (canonical_json(proposed.to_json_dict()) + "\n").encode("utf-8")
    unchanged = proposed.to_json_dict() == previous.to_json_dict()
    digest = config.framework_bundle_sha256 if unchanged else hashlib.sha256(data).hexdigest()
    updated = config
    if not unchanged:
        version_dir = run_dir / "framework" / "versions" / digest
        bundle_path = version_dir / "bundle.json"
        if not bundle_path.exists():
            version_dir.mkdir(parents=True, exist_ok=True)
            temporary = version_dir / ".bundle.json.tmp"
            temporary.write_bytes(data)
            temporary.replace(bundle_path)
        elif bundle_path.read_bytes() != data:
            raise ValueError("Existing framework version has different bytes.")
        if not (version_dir / "reflection.json").exists():
            atomic_json(version_dir / "reflection.json", {
                "schema_version": "eagle-framework-reflection-version-v1",
                "status": "accepted",
                "parent_bundle_sha256": config.framework_bundle_sha256,
                "bundle_sha256": digest,
                "generation": generation,
                "reflection_artifact": artifact_dir.relative_to(run_dir).as_posix(),
            })
        updated = replace(
            config, framework_bundle_path=bundle_path.resolve(),
            framework_bundle_sha256=digest, framework_bundle_version=proposed.schema_version,
        )
    updated.validate()
    replicas = []
    replica_role = (
        "framework_option_reflection" if option_only else "framework_reflection"
    )
    for index, parent in enumerate(population):
        genome = validate_genome(proposed, selected_genomes[parent.id])
        replicas.append(Candidate(
            id=derive_candidate_id(
                config.random_seed, generation=generation, index=index,
                role=replica_role, parent_ids=(parent.id,),
            ),
            generation=generation, parent_ids=(parent.id,),
            java_materialization_mode="framework_slots",
            java_compiler_version=config.java_compiler_version,
            control_genome=genome,
            strategy_description=revised_strategies[parent.id],
            slot_parent_ids={slot_id: parent.id for slot_id in proposed.slot_ids},
            source_candidate_ids=(parent.id,), framework_bundle_sha256=digest,
            generation_prompt="", operator=replica_role,
            metadata={"framework_reflection": {
                "scope": "control_genome" if option_only else "framework_bundle",
                "source_parent_id": parent.id,
                "previous_bundle_sha256": config.framework_bundle_sha256,
                "slot_value_source": "framework_coach",
                "changed_slot_ids": [
                    key for key, value in genome.items()
                    if key not in parent.control_genome or parent.control_genome[key] != value
                ],
                "removed_slot_ids": sorted(set(parent.control_genome) - set(genome)),
            }},
        ))
    atomic_json(artifact_dir / "migration.json", {
        "schema_version": "eagle-framework-migration-v1", "generation": generation,
        "reflection_scope": "control_genome" if option_only else "framework_bundle",
        "previous_bundle_sha256": config.framework_bundle_sha256,
        "bundle_sha256": digest,
        "records": [
            {"source_parent_id": parent.id, "replica_id": replica.id,
             "previous_strategy_description": parent.strategy_description,
             "strategy_description": replica.strategy_description,
             "previous_control_genome": parent.control_genome,
             "control_genome": replica.control_genome, **replica.metadata["framework_reflection"]}
            for parent, replica in zip(population, replicas, strict=True)
        ],
    })
    return updated, replicas
