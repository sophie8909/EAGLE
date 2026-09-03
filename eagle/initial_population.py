"""Generation-zero policy construction and its candidate-owned LLM evidence."""

from __future__ import annotations

import hashlib
import json
import string
import time
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .artifacts import write_candidate_inputs, write_json
from .candidate import Candidate
from .config import ExperimentConfig
from .llm import LLMCallLogger, truncate_prompt
from .prompts import normalize_prompt
from .timing import utc_now


LLM_GENERATED_POLICIES = "llm_generated_policies"
INITIAL_POLICY_SCHEMA_VERSION = "eagle-initial-policy-generation-v1"


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
        self.requests.append(prompt)
        sample = len(self.requests)
        return json.dumps(
            {
                "strategy_prompt": (
                    f"Use mock RTS strategy variant {sample}: maintain economy, "
                    "produce a mixed army, and attack the nearest enemy structure."
                )
            }
        )


def initialize_population(
    config: ExperimentConfig,
    *,
    policy_backend: InitialPolicyBackend | None = None,
    candidates_dir: Path | None = None,
    timing_logger: LLMCallLogger | None = None,
) -> list[Candidate]:
    """Build generation zero under the configured population contract."""

    inherited_java = (
        config.initial_java_seed_path.read_text(encoding="utf-8")
        if config.candidate_java_mode == "inherited_genotype"
        else ""
    )
    if config.initial_population_mode != LLM_GENERATED_POLICIES:
        seed_prompts = config.seed_prompts
        if config.candidate_java_mode == "inherited_genotype" and len(seed_prompts) == 1:
            seed_prompts = tuple(seed_prompts[0] for _ in range(config.population_size))
        return [
            Candidate(
                generation=0,
                strategy_prompt=prompt,
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
            generation=0,
            strategy_prompt=prompt,
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
            generation=0,
            generation_prompt=config.generation_prompt,
            inherited_java=inherited_java,
            operator="seed",
            metadata={
                "seed_index": index,
                "initial_policy_source": "llm_generated",
                "initial_policy_sample_index": index - len(configured) + 1,
            },
        )
        for index in range(len(configured), config.population_size)
    ]

    # Persist every identity, lineage record, and known genotype component before
    # the first external request. Failed initialization therefore remains auditable.
    for candidate in (*configured, *drafts):
        write_candidate_inputs(candidates_dir, candidate)

    population = list(configured)
    selected_prompts = [candidate.strategy_prompt for candidate in configured]
    for draft in drafts:
        strategy_prompt = _generate_initial_policy(
            draft,
            config=config,
            backend=policy_backend,
            candidates_dir=candidates_dir,
            selected_prompts=selected_prompts,
            timing_logger=timing_logger,
        )
        candidate = replace(draft, strategy_prompt=strategy_prompt)
        write_candidate_inputs(candidates_dir, candidate)
        population.append(candidate)
        selected_prompts.append(strategy_prompt)
    return population


def generation_zero_uses_fixed_java(config: ExperimentConfig) -> bool:
    """Return whether generation zero bypasses the Java Generator."""

    return (
        config.candidate_java_mode == "generated_phenotype"
        or config.initial_population_mode == LLM_GENERATED_POLICIES
    )


def _generate_initial_policy(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: InitialPolicyBackend,
    candidates_dir: Path,
    selected_prompts: list[str],
    timing_logger: LLMCallLogger | None,
) -> str:
    root = candidates_dir / candidate.id / "initialization" / "policy_generation"
    attempts_root = root / "attempts"
    root.mkdir(parents=True, exist_ok=True)
    selected_attempt: int | None = None
    final_prompt = ""
    failure_reason: str | None = None

    for attempt in range(1, config.initial_policy_max_attempts + 1):
        request = _render_initial_policy_request(
            config,
            sample_index=int(candidate.metadata["initial_policy_sample_index"]),
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
        try:
            raw = backend.generate(request)
            # Raw output is durable before JSON parsing or semantic validation.
            (attempt_dir / "response_raw.txt").write_text(raw, encoding="utf-8")
            parsed = json.loads(raw)
            if (
                not isinstance(parsed, dict)
                or set(parsed) != {"strategy_prompt"}
                or not isinstance(parsed.get("strategy_prompt"), str)
            ):
                raise ValueError(
                    "response must contain exactly one string field: strategy_prompt"
                )
            final_prompt = normalize_prompt(
                parsed["strategy_prompt"],
                max_chars=config.max_prompt_chars,
                max_lines=config.max_prompt_lines,
            )
            if not final_prompt:
                raise ValueError("strategy_prompt must not be empty")
            if final_prompt in selected_prompts:
                raise ValueError("strategy_prompt duplicates an existing population policy")
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
        )
        if selected_attempt is not None:
            break

    write_json(
        root / "result.json",
        {
            "schema_version": INITIAL_POLICY_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "sample_index": candidate.metadata["initial_policy_sample_index"],
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
    selected_prompts: list[str],
    prior_error: str,
) -> str:
    selected = "\n\n---\n\n".join(selected_prompts) or "none"
    request = string.Template(config.initial_policy_generation_prompt).substitute(
        sample_index=sample_index,
        population_size=config.population_size,
        existing_strategy_prompts=selected,
        prior_error=prior_error,
    )
    return truncate_prompt(request)


def _record_policy_timing(
    logger: LLMCallLogger | None,
    *,
    backend: InitialPolicyBackend,
    candidate: Candidate,
    attempt: int,
    timing: dict[str, object],
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
            "failure_category": (
                "initial_policy_generation" if timing["status"] != "success" else None
            ),
            "transport_attempt": 1,
        },
    )
