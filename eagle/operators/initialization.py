"""Generation-zero policy construction and its candidate-owned LLM evidence."""

from __future__ import annotations

import hashlib
import json
import string
import time
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from eagle.artifacts import write_candidate_inputs, write_json
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.execution import llm_worker_slot, parallel_map
from eagle.evaluation.determinism import derive_candidate_id, derive_seed
from eagle.generation.framework_slots import (
    genome_sha256,
    load_framework_bundle,
    sample_initial_genome,
    validate_genome,
)
from eagle.llm import LLMCallLogger, generate_seeded, parse_json_object_response, truncate_prompt
from eagle.prompts import load_prompt
from eagle.timing import utc_now
from eagle.strategy_dsl import (
    STRATEGY_DSL_JSON_SCHEMA,
    normalize_strategy_dsl,
    validate_strategy_dsl,
    worker_rush_policy,
)


LLM_GENERATED_POLICIES = "llm_generated_policies"
INITIAL_POLICY_SCHEMA_VERSION = "eagle-initial-policy-generation-v1"
INITIAL_POLICY_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"strategy_prompt": STRATEGY_DSL_JSON_SCHEMA},
    "required": ["strategy_prompt"],
}
MICRORTS_GAMEPLAY_CONTRACT = load_prompt("microrts_gameplay_contract")
INITIAL_POLICY_VARIANTS = tuple(
    line.removeprefix("- ").strip()
    for line in load_prompt("initial_policy_variants").splitlines()
    if line.strip()
)
FRAMEWORK_INITIAL_STRATEGIES = tuple(
    line.strip() for line in load_prompt("framework_initial_strategies").splitlines() if line.strip()
)


class InitialPolicyBackend(Protocol):
    """Transport used for one policy-only population-initialization request."""

    def generate(self, prompt: str) -> str:
        """Return one raw JSON response containing ``strategy_prompt``."""


class MockInitialPolicyBackend:
    """Deterministic policy generator for mock searches and tests."""

    model = "mock"
    base_url = "mock://initial-policy"

    def __init__(self) -> None:
        self.requests: list[str] = []

    def generate(self, prompt: str) -> str:
        raise ValueError("Mock initial policy generation requires an explicit task seed.")

    def generate_seeded(self, prompt: str, seed: int) -> str:
        self.requests.append(prompt)
        return json.dumps({"strategy_prompt": worker_rush_policy(2 + seed % 999_999)})


def initialize_population(
    config: ExperimentConfig,
    *,
    policy_backend: InitialPolicyBackend | None = None,
    candidates_dir: Path | None = None,
    timing_logger: LLMCallLogger | None = None,
) -> list[Candidate]:
    """Build generation zero under the configured population contract."""

    if config.java_materialization_mode == "framework_slots":
        if config.framework_bundle_path is None or config.framework_bundle_sha256 is None:
            raise ValueError("framework_slots initialization requires a validated bundle.")
        bundle = load_framework_bundle(
            config.framework_bundle_path,
            expected_sha256=config.framework_bundle_sha256,
        )
        periodic_reflection = config.framework_evolution_mode in {
            "reflection", "option_reflection",
        }
        if periodic_reflection and config.population_size > len(FRAMEWORK_INITIAL_STRATEGIES):
            raise ValueError("Add distinct framework initial strategies for the requested population size.")
        if periodic_reflection and len({
            " ".join(description.split()).casefold()
            for description in FRAMEWORK_INITIAL_STRATEGIES[:config.population_size]
        }) != config.population_size:
            raise ValueError("Initial framework strategy descriptions must be distinct.")
        configured_initial_genomes = tuple(
            validate_genome(bundle, dict(genome))
            for genome in config.framework_initial_genomes
        )

        def initial_genome(index: int) -> tuple[dict[str, object], dict[str, object]]:
            if index < len(configured_initial_genomes):
                genome = configured_initial_genomes[index]
                return genome, {
                    "initial_genome_source": "configured_frozen",
                    "initial_genome_config_index": index,
                    "initial_genome_sha256": genome_sha256(bundle, genome),
                }
            return sample_initial_genome(
                bundle,
                random_seed=config.random_seed,
                sample_index=index,
            ), {"initial_genome_sample_index": index}

        population: list[Candidate] = []
        for index in range(config.population_size):
            control_genome, genome_metadata = initial_genome(index)
            population.append(Candidate(
                id=derive_candidate_id(
                    config.random_seed,
                    generation=0,
                    index=index,
                    role="initial",
                ),
                generation=0,
                candidate_java_mode=config.candidate_java_mode,
                java_materialization_mode="framework_slots",
                java_compiler_version=config.java_compiler_version,
                control_genome=control_genome,
                slot_parent_ids={},
                framework_bundle_sha256=config.framework_bundle_sha256,
                generation_prompt="",
                strategy_description=(
                    FRAMEWORK_INITIAL_STRATEGIES[index]
                    if periodic_reflection else ""
                ),
                operator="seed",
                metadata={
                    "seed_index": index,
                    "framework_id": bundle.framework_id,
                    **genome_metadata,
                },
            ))
        direct_gpt_count = config.framework_gpt_initial_candidates
        if config.framework_evolution_mode == "llm_coach" or direct_gpt_count:
            from eagle.operators.framework_coach import select_initial_framework_genome

            if policy_backend is None or candidates_dir is None:
                raise ValueError(
                    "framework initial GPT/Coach selection requires a backend and artifact directory."
                )

            selection_count = (
                config.population_size
                if config.framework_evolution_mode == "llm_coach"
                else direct_gpt_count
            )
            selection_model = (
                config.llm_model
                if config.framework_evolution_mode == "llm_coach"
                else config.framework_model
            )

            def select_genome(candidate: Candidate) -> Candidate:
                write_candidate_inputs(candidates_dir, candidate)
                selected = select_initial_framework_genome(
                    candidate, bundle, policy_backend,
                    artifact_dir=candidates_dir / candidate.id,
                    timing_logger=timing_logger,
                    max_attempts=config.initial_policy_max_attempts,
                    model_identity=selection_model,
                    selection_seed=config.random_seed,
                )
                if config.framework_evolution_mode == "local":
                    selection_metadata = dict(
                        selected.metadata.get("framework_coach_selection", {})
                    )
                    return replace(
                        selected,
                        metadata={
                            **selected.metadata,
                            "framework_coach_selection": {
                                **selection_metadata,
                                "provider": "direct_openai_gpt",
                                "model": config.framework_model,
                            },
                        },
                    )
                return selected

            population = (
                parallel_map(select_genome, population[:selection_count])
                + population[selection_count:]
            )
        return population

    inherited_java = (
        config.initial_java_seed_path.read_text(encoding="utf-8")
        if config.candidate_java_mode == "inherited_genotype"
        else ""
    )
    if config.initial_population_mode != LLM_GENERATED_POLICIES:
        seed_prompts = config.seed_prompts
        if (config.candidate_java_mode == "inherited_genotype" or config.java_materialization_mode == "deterministic_dsl") and len(seed_prompts) == 1:
            seed_prompts = tuple(seed_prompts[0] for _ in range(config.population_size))
        return [
            Candidate(
                id=(
                    derive_candidate_id(
                        config.random_seed,
                        generation=0,
                        index=index,
                        role="initial",
                    )
                ),
                generation=0,
                strategy_prompt=prompt,
                candidate_java_mode=config.candidate_java_mode,
                java_materialization_mode=config.java_materialization_mode,
                java_compiler_version=config.java_compiler_version if config.java_materialization_mode == "deterministic_dsl" else None,
                generation_prompt=config.generation_prompt,
                inherited_java=inherited_java,
                operator="seed",
                metadata={
                    "seed_index": (
                        0 if config.candidate_java_mode == "inherited_genotype" else index
                    ),
                    **(
                        {"replicate_index": index}
                        if config.candidate_java_mode == "inherited_genotype"
                        else {}
                    ),
                },
            )
            for index, prompt in enumerate(seed_prompts[: config.population_size])
        ]

    if policy_backend is None or candidates_dir is None:
        raise ValueError(
            "llm_generated_policies initialization requires a policy backend and candidates_dir."
        )

    configured = [
        Candidate(
            id=(
                derive_candidate_id(
                    config.random_seed,
                    generation=0,
                    index=index,
                    role="initial",
                )
            ),
            generation=0,
            strategy_prompt=prompt,
            candidate_java_mode=config.candidate_java_mode,
            java_materialization_mode=config.java_materialization_mode,
            java_compiler_version=config.java_compiler_version if config.java_materialization_mode == "deterministic_dsl" else None,
            generation_prompt=config.generation_prompt,
            inherited_java=inherited_java,
            operator="seed",
            metadata={
                "seed_index": index,
                "initial_policy_source": "configured_seed",
            },
        )
        for index, prompt in enumerate(config.seed_prompts)
    ]
    drafts = [
        Candidate(
            id=(
                derive_candidate_id(
                    config.random_seed,
                    generation=0,
                    index=index,
                    role="initial",
                )
            ),
            generation=0,
            candidate_java_mode=config.candidate_java_mode,
            java_materialization_mode=config.java_materialization_mode,
            java_compiler_version=config.java_compiler_version if config.java_materialization_mode == "deterministic_dsl" else None,
            generation_prompt=config.generation_prompt,
            inherited_java=inherited_java,
            operator="seed",
            metadata={
                "seed_index": index,
                "initial_policy_source": "llm_generated",
                "initial_policy_sample_index": index - len(configured) + 1,
                "initial_policy_diversity_directive": _initial_policy_diversity_directive(
                    index - len(configured) + 1
                ),
            },
        )
        for index in range(len(configured), config.population_size)
    ]

    # Persist every identity, lineage record, and known genotype component before
    # the first external request. Failed initialization therefore remains auditable.
    for candidate in (*configured, *drafts):
        write_candidate_inputs(candidates_dir, candidate)

    selected_prompts = [candidate.strategy_prompt for candidate in configured]
    snapshot = list(selected_prompts)
    generated = parallel_map(lambda draft: _generate_initial_policy(
        draft, config=config, backend=policy_backend, candidates_dir=candidates_dir,
        selected_prompts=snapshot, timing_logger=timing_logger,
    ), drafts)
    population = list(configured)
    for task_index, (draft, strategy_prompt) in enumerate(
        zip(drafts, generated, strict=True)
    ):
        if strategy_prompt in selected_prompts:
            root = candidates_dir / draft.id / "initialization" / "policy_generation"
            summary = json.loads((root / "result.json").read_text(encoding="utf-8"))
            attempt_dir = root / summary["selected_attempt_artifact"]
            rejected = json.loads((attempt_dir / "result.json").read_text(encoding="utf-8"))
            reason = "strategy_prompt duplicates an earlier parallel population policy"
            rejected.update(selected=False, population_decision={
                "status": "rejected_duplicate",
                "reason": reason,
                "duplicate_of_candidate_id": next(
                    candidate.id for candidate in population
                    if candidate.strategy_prompt == strategy_prompt
                ),
            })
            write_json(attempt_dir / "result.json", rejected)
            with llm_worker_slot(task_index):
                strategy_prompt = _generate_initial_policy(
                    draft, config=config, backend=policy_backend, candidates_dir=candidates_dir,
                    selected_prompts=selected_prompts, timing_logger=timing_logger,
                    start_attempt=summary["final_attempt"] + 1, prior_error=reason,
                )
        candidate = replace(draft, strategy_prompt=strategy_prompt)
        write_candidate_inputs(candidates_dir, candidate)
        population.append(candidate)
        selected_prompts.append(strategy_prompt)
    return population


def generation_zero_uses_fixed_java(config: ExperimentConfig) -> bool:
    """Return whether generation zero bypasses the Java Generator."""

    return config.java_materialization_mode == "llm" and config.candidate_java_mode == "generated_phenotype"


def _generate_initial_policy(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: InitialPolicyBackend,
    candidates_dir: Path,
    selected_prompts: list[str],
    timing_logger: LLMCallLogger | None,
    start_attempt: int = 1,
    prior_error: str | None = None,
) -> str:
    root = candidates_dir / candidate.id / "initialization" / "policy_generation"
    attempts_root = root / "attempts"
    root.mkdir(parents=True, exist_ok=True)
    selected_attempt: int | None = None
    final_prompt = ""
    failure_reason = prior_error
    attempt = start_attempt - 1

    for attempt in range(start_attempt, config.initial_policy_max_attempts + 1):
        request = _render_initial_policy_request(
            config,
            sample_index=int(candidate.metadata["initial_policy_sample_index"]),
            diversity_directive=str(
                candidate.metadata["initial_policy_diversity_directive"]
            ),
            selected_prompts=selected_prompts,
            prior_error=failure_reason or "none",
        )
        attempt_dir = attempts_root / f"attempt_{attempt:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        (attempt_dir / "request.txt").write_text(request, encoding="utf-8")
        (attempt_dir / "response_raw.txt").write_text("", encoding="utf-8")
        started_at = utc_now()
        started = time.monotonic()
        raw = ""
        status = "failed"
        request_sha256 = hashlib.sha256(request.encode("utf-8")).hexdigest()
        request_seed = derive_seed(
            config.random_seed, "initial_policy_generation", candidate.generation, candidate.id, attempt
        ) & 0x7FFF_FFFF
        try:
            raw = generate_seeded(backend, request, request_seed)
            # Raw output is durable before JSON parsing or semantic validation.
            (attempt_dir / "response_raw.txt").write_text(raw, encoding="utf-8")
            parsed = parse_json_object_response(raw)
            if not isinstance(parsed, dict) or set(parsed) != {"strategy_prompt"}:
                raise ValueError("response must contain exactly one field: strategy_prompt")
            strategy_source = parsed["strategy_prompt"]
            if not isinstance(strategy_source, (str, dict)):
                raise ValueError("strategy_prompt must be a JSON object or serialized JSON string")
            if isinstance(strategy_source, str):
                if len(strategy_source) > config.max_prompt_chars:
                    raise ValueError("strategy DSL exceeds size limit")
                try:
                    # Local models sometimes emit literal newlines inside the
                    # nested DSL JSON string. Reuse the tolerant JSON boundary
                    # before applying the normative DSL validator.
                    strategy_source = parse_json_object_response(strategy_source)
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            final_prompt = normalize_strategy_dsl(
                strategy_source,
                max_chars=config.max_prompt_chars,
            )
            if final_prompt in selected_prompts:
                raise ValueError("strategy_prompt duplicates an existing population policy")
            if "reference_agent" in validate_strategy_dsl(final_prompt):
                raise ValueError(
                    "reference_agent is reserved for checked-in configured seeds"
                )
            status = "success"
            failure_reason = None
            selected_attempt = attempt
        except Exception as exc:  # retain backend, parse, and validation failures alike
            failure_reason = f"{type(exc).__name__}: {exc}"

        finished_at = utc_now()
        duration = max(0.0, time.monotonic() - started)
        timing = {
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration,
            "status": status,
            "error": failure_reason,
        }
        write_json(attempt_dir / "timing.json", timing)
        write_json(
            attempt_dir / "result.json",
            {
                "schema_version": INITIAL_POLICY_SCHEMA_VERSION,
                "attempt": attempt,
                "status": status,
                "error": failure_reason,
                "selected": selected_attempt == attempt,
                "backend": type(backend).__name__,
                "model": str(getattr(backend, "model", "unknown")),
                "endpoint": str(getattr(backend, "base_url", "unknown")),
                "temperature": float(
                    getattr(backend, "temperature", config.initial_policy_temperature)
                ),
                "sampling_seed": request_seed,
                "request_sha256": request_sha256,
                "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            },
        )
        _record_policy_timing(
            timing_logger,
            backend=backend,
            candidate=candidate,
            attempt=attempt,
            timing=timing,
            request_seed=request_seed,
        )
        if selected_attempt is not None:
            break

    write_json(
        root / "result.json",
        {
            "schema_version": INITIAL_POLICY_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "sample_index": candidate.metadata["initial_policy_sample_index"],
            "diversity_directive": candidate.metadata[
                "initial_policy_diversity_directive"
            ],
            "status": "success" if selected_attempt is not None else "failed",
            "max_attempts": config.initial_policy_max_attempts,
            "selected_attempt": selected_attempt,
            "final_attempt": attempt,
            "selected_attempt_artifact": (
                None
                if selected_attempt is None
                else f"attempts/attempt_{selected_attempt:03d}"
            ),
            "prompt_source": str(config.initial_policy_generation_prompt_file.resolve()),
            "strategy_prompt_artifact": "../../genotype/policy_prompt.txt",
            "error": failure_reason,
        },
    )
    if selected_attempt is None:
        raise RuntimeError(
            f"Initial policy generation failed for {candidate.id}: {failure_reason}"
        )
    return final_prompt


def _render_initial_policy_request(
    config: ExperimentConfig,
    *,
    sample_index: int,
    diversity_directive: str,
    selected_prompts: list[str],
    prior_error: str,
) -> str:
    selected = "\n\n---\n\n".join(selected_prompts) or "none"
    request = string.Template(config.initial_policy_generation_prompt).substitute(
        gameplay_contract=MICRORTS_GAMEPLAY_CONTRACT + "\n" + load_prompt("strategy_dsl_reference"),
        sample_index=sample_index,
        population_size=config.population_size,
        diversity_directive=diversity_directive,
        existing_strategy_prompts=selected,
        prior_error=prior_error,
    )
    return truncate_prompt(request)


def _initial_policy_diversity_directive(sample_index: int) -> str:
    """Return a stable strategy identity for one LLM-generated seed slot."""

    if sample_index < 1:
        raise ValueError("initial policy sample_index must be positive")
    if sample_index <= len(INITIAL_POLICY_VARIANTS):
        return INITIAL_POLICY_VARIANTS[sample_index - 1]
    return (
        f"Novel strategic identity {sample_index}: choose a coherent strategy that is "
        "materially different from every listed identity and existing policy."
    )


def _record_policy_timing(
    logger: LLMCallLogger | None,
    *,
    backend: InitialPolicyBackend,
    candidate: Candidate,
    attempt: int,
    timing: dict[str, object],
    request_seed: int,
) -> None:
    if logger is None:
        return
    logger.write_timing_event(
        request_correlation_id=(
            f"{logger.run_id or 'run'}:{candidate.id}:initial_policy:{attempt:03d}"
        ),
        stage="initial_policy_generation",
        status=str(timing["status"]),
        model=str(getattr(backend, "model", "unknown")),
        candidate_id=candidate.id,
        generation=0,
        started_at=str(timing["started_at"]),
        finished_at=str(timing["finished_at"]),
        duration_seconds=float(timing["duration_seconds"]),
        metadata={
            "operation_type": "initialization",
            "endpoint": str(getattr(backend, "base_url", "unknown")),
            "sampling_seed": request_seed,
            "failure_category": (
                "initial_policy_generation" if timing["status"] != "success" else None
            ),
            "transport_attempt": 1,
        },
    )
