"""Candidate representation for evolved EAGLE individuals."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from eagle.opponent_cases import LEXICASE_CASES, FAILED_OPPONENT_SCORE
from eagle.prompts import load_prompt
from eagle.strategy_dsl import VERSION as STRATEGY_POLICY_FORMAT, normalize_strategy_dsl


ACTION_API_GUIDE = load_prompt("action_api_guide")
DEFAULT_GENERATION_PROMPT = load_prompt("initial_generation")

LINEAGE_SCHEMA_VERSION = "3.0"
CANDIDATE_SNAPSHOT_SCHEMA_VERSION = "eagle-candidate-v5"
FRAMEWORK_SLOTS_MATERIALIZATION_VERSION = "eagle-framework-slots-v1"
FRAMEWORK_SLOTS_CANDIDATE_SCHEMA_VERSION = "eagle-candidate-v8"
FRAMEWORK_SLOTS_LINEAGE_SCHEMA_VERSION = "4.0"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def has_completed_evaluation(candidate: "Candidate") -> bool:
    """Return whether a candidate completed evaluation without a failure."""

    return (
        candidate.status in {"evaluated", "complete"}
        and candidate.failure_stage is None
        and candidate.failure_reason is None
    )


@dataclass(frozen=True)
class Candidate:
    """One evolutionary individual that generates one complete Java agent."""

    id: str = ""
    generation: int = 0
    parent_ids: tuple[str, ...] = ()
    # The default ``generated_phenotype`` mode has the original two prompt
    # genes.  ``inherited_genotype`` additionally carries the complete Java
    # input chosen before generation; it is deliberately separate from the
    # generated phenotype below so failures do not erase inherited state.
    strategy_prompt: str = '{"rules":[],"version":"eagle-strategy-dsl-v1"}'
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
    candidate_java_mode: str = "generated_phenotype"
    java_materialization_mode: str = "llm"
    java_compiler_version: str | None = None
    # ``framework_slots`` candidates evolve only this structured control
    # genome. Each framework version remains immutable run input, while each
    # slot records independent component provenance.
    control_genome: dict[str, Any] = field(default_factory=dict)
    slot_parent_ids: dict[str, str] = field(default_factory=dict)
    framework_bundle_sha256: str | None = None
    inherited_java: str = ""
    java_parent_id: str | None = None
    generated_java: str = ""
    generated_java_path: str | None = None
    operator: str = "seed"
    mutation_type: str | None = None
    strategy_parent_id: str | None = None
    generation_prompt_parent_id: str | None = None
    source_candidate_ids: tuple[str, ...] = ()
    compile_status: str = "pending"
    game_eval_result: dict[str, Any] = field(default_factory=dict)
    code_quality_result: dict[str, Any] = field(default_factory=dict)
    fitness_objectives: dict[str, float] = field(default_factory=dict)
    # Executable full-agent behavior over the fixed MicroRTS probe suite.
    # ``strategy_signature`` below remains policy-text metadata and must not be
    # used as a behavioral substitute.
    semantic_signature: dict[str, Any] = field(default_factory=dict)
    strategy_signature: dict[str, Any] = field(default_factory=dict)
    strategy_niche: str = "unknown"
    mutation_intent: str | None = None
    parent_strategy_niche: str | None = None
    niche_changed: bool | None = None
    status: str = "pending"
    failure_stage: str | None = None
    failure_reason: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    strategy_description: str = ""

    def __post_init__(self) -> None:
        """Require an identity before a candidate can enter any pipeline."""

        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError(
                "Candidate requires an explicit non-empty id; "
                "EA factories must derive stable candidate identities."
            )
        if not isinstance(self.strategy_description, str):
            raise ValueError("Candidate strategy_description must be a string.")
        if self.java_materialization_mode == "framework_slots":
            if self.candidate_java_mode != "generated_phenotype":
                raise ValueError(
                    "framework_slots requires candidate_java_mode=generated_phenotype."
                )
            if self.java_compiler_version is None:
                object.__setattr__(
                    self,
                    "java_compiler_version",
                    FRAMEWORK_SLOTS_MATERIALIZATION_VERSION,
                )
            elif self.java_compiler_version != FRAMEWORK_SLOTS_MATERIALIZATION_VERSION:
                raise ValueError(
                    "Unsupported framework_slots materialization version: "
                    f"{self.java_compiler_version!r}."
                )
            if not isinstance(self.control_genome, dict):
                raise ValueError("framework_slots control_genome must be a mapping.")
            if any(not isinstance(slot_id, str) or not slot_id for slot_id in self.control_genome):
                raise ValueError(
                    "framework_slots control_genome slot IDs must be non-empty strings."
                )
            try:
                json.dumps(self.control_genome, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "framework_slots control_genome must contain finite JSON values."
                ) from exc
            if not isinstance(self.slot_parent_ids, dict) or any(
                not isinstance(slot_id, str)
                or not slot_id
                or not isinstance(parent_id, str)
                or not parent_id
                for slot_id, parent_id in self.slot_parent_ids.items()
            ):
                raise ValueError(
                    "framework_slots slot_parent_ids must map non-empty slot IDs "
                    "to non-empty candidate IDs."
                )
            unknown_slots = set(self.slot_parent_ids).difference(self.control_genome)
            if unknown_slots:
                raise ValueError(
                    "framework_slots slot_parent_ids reference unknown control_genome "
                    f"slots: {sorted(unknown_slots)}."
                )
            if not isinstance(self.framework_bundle_sha256, str) or not _SHA256_PATTERN.fullmatch(
                self.framework_bundle_sha256
            ):
                raise ValueError(
                    "framework_slots framework_bundle_sha256 must be a lowercase "
                    "64-character SHA-256 digest."
                )

    @property
    def active_genotype_components(self) -> tuple[str, ...]:
        if self.java_materialization_mode == "framework_slots":
            return ("control_genome",)
        if self.java_materialization_mode == "deterministic_dsl":
            return ("strategy_prompt",)
        return ("strategy_prompt", "generation_prompt", *(("inherited_java",) if self.candidate_java_mode == "inherited_genotype" else ()))

    def materialization_to_json_dict(self) -> dict[str, Any]:
        payload = {
            "candidate_java_mode": self.candidate_java_mode,
            "java_materialization_mode": self.java_materialization_mode,
            "java_compiler_version": self.java_compiler_version,
            "active_genotype_components": list(self.active_genotype_components),
        }
        if self.java_materialization_mode == "framework_slots":
            payload["framework_bundle_sha256"] = self.framework_bundle_sha256
        return payload

    @property
    def candidate_schema_version(self) -> str:
        if self.java_materialization_mode == "framework_slots":
            return FRAMEWORK_SLOTS_CANDIDATE_SCHEMA_VERSION
        if self.java_materialization_mode == "deterministic_dsl":
            return "eagle-candidate-v7"
        return CANDIDATE_SNAPSHOT_SCHEMA_VERSION

    def objective_vector(self) -> tuple[float, ...]:
        """Return the fixed opponent cases used by lexicase selection."""

        cases = tuple(self.game_eval_result.get("fitness_case_ids") or LEXICASE_CASES)
        return tuple(float(self.fitness_objectives.get(case, FAILED_OPPONENT_SCORE)) for case in cases)

    def generation_input(
        self,
        *,
        class_name: str = "",
        module_name: str = "controller",
        agent_template_path: object | None = None,
    ) -> str:
        """Build one request for a complete single-file Java agent."""
        if self.java_materialization_mode in {"deterministic_dsl", "framework_slots"}:
            raise ValueError(
                f"{self.java_materialization_mode} candidates do not have a Java "
                "generation request."
            )
        from eagle.generation.agent_template import JavaTemplatePaths, load_java_template

        # The default mode starts from the checked-in scaffold without parent
        # Java.  A candidate with inherited Java uses the explicitly separate
        # third-component generator resource.
        current_source = load_java_template(
            JavaTemplatePaths()
            if agent_template_path is None
            else JavaTemplatePaths(agent_template_path)
        )
        from eagle.prompts import render_prompt

        values = {
            "policy_prompt": normalize_strategy_dsl(self.strategy_prompt),
            "strategy_dsl_reference": load_prompt("strategy_dsl_reference"),
            "action_api_guide": ACTION_API_GUIDE,
            "code_generation_prompt": self.generation_prompt.strip(),
            "java_scaffold": current_source,
        }
        if self.inherited_java:
            return render_prompt(
                "java_generation_inherited",
                {**values, "inherited_java": self.inherited_java},
            )
        return render_prompt("java_generation", values)

    def to_json_dict(self) -> dict[str, Any]:
        """Return the compact, resumable candidate snapshot.

        Raw match output, telemetry, and mutation LLM envelopes live in their
        canonical per-stage files.  Keeping them out of population snapshots
        prevents one verbose match log from being copied across every run-level
        artifact and recursively deep-copied by ``dataclasses.asdict``.
        """

        payload = {
            "candidate_schema_version": self.candidate_schema_version,
            "strategy_policy_format": STRATEGY_POLICY_FORMAT,
            **self.materialization_to_json_dict(),
            "id": self.id,
            "candidate_id": self.id,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "strategy_prompt": self.strategy_prompt,
            "strategy_description": self.strategy_description,
            "generation_prompt": self.generation_prompt,
            "generated_java": self.generated_java,
            "generated_java_path": self.generated_java_path,
            "operator": self.operator,
            "mutation_type": self.mutation_type,
            "strategy_parent_id": self.strategy_parent_id,
            "generation_prompt_parent_id": self.generation_prompt_parent_id if "generation_prompt" in self.active_genotype_components else None,
            "source_candidate_ids": list(self.resolved_source_candidate_ids()),
            "compile_status": self.compile_status,
            "game_eval_result": dict(self.game_eval_result),
            "code_quality_result": dict(self.code_quality_result),
            "fitness_objectives": dict(self.fitness_objectives),
            "semantic_signature": dict(self.semantic_signature),
            "strategy_signature": dict(self.strategy_signature),
            "strategy_niche": self.strategy_niche,
            "mutation_intent": self.mutation_intent,
            "parent_strategy_niche": self.parent_strategy_niche,
            "niche_changed": self.niche_changed,
            "status": self.status,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "artifacts": dict(self.artifacts),
            "timing": dict(self.timing),
            "metadata": compact_candidate_metadata(self.metadata),
        }
        if self.java_materialization_mode == "llm" and (self.inherited_java or self.java_parent_id is not None):
            # The complete component is stored only at the genotype artifact
            # path. Snapshots retain provenance, not duplicate source bodies.
            payload["java_parent_id"] = self.java_parent_id
        if self.java_materialization_mode == "framework_slots":
            for key in (
                "strategy_policy_format",
                "strategy_prompt",
                "generation_prompt",
                "strategy_parent_id",
                "generation_prompt_parent_id",
            ):
                payload.pop(key, None)
            payload.update(
                control_genome={
                    slot_id: self.control_genome[slot_id]
                    for slot_id in sorted(self.control_genome)
                },
                slot_parent_ids={
                    slot_id: self.slot_parent_ids[slot_id]
                    for slot_id in sorted(self.slot_parent_ids)
                },
                framework_bundle_sha256=self.framework_bundle_sha256,
            )
        return payload

    def to_individual_dict(self) -> dict[str, Any]:
        """Return the small candidate index used by offline inspection."""

        payload = self.to_json_dict()
        payload.pop("game_eval_result", None)
        payload.pop("code_quality_result", None)
        payload.pop("metadata", None)
        return payload

    def to_summary_dict(self) -> dict[str, Any]:
        """Return fitness and timing data for run-level summaries."""

        payload = {
            "candidate_schema_version": self.candidate_schema_version,
            "strategy_policy_format": STRATEGY_POLICY_FORMAT,
            **self.materialization_to_json_dict(),
            "candidate_id": self.id,
            "strategy_description": self.strategy_description,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "operator": self.operator,
            "mutation_type": self.mutation_type,
            "strategy_signature": dict(self.strategy_signature),
            "strategy_niche": self.strategy_niche,
            "mutation_intent": self.mutation_intent,
            "parent_strategy_niche": self.parent_strategy_niche,
            "niche_changed": self.niche_changed,
            "status": self.status,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "fitness_objectives": dict(self.fitness_objectives),
            "semantic_signature": dict(self.semantic_signature),
            "timing": dict(self.timing),
            "artifacts": dict(self.artifacts),
        }
        if self.java_materialization_mode == "framework_slots":
            payload.pop("strategy_policy_format", None)
        return payload

    def resolved_source_candidate_ids(self) -> tuple[str, ...]:
        """Return stable contributing candidate IDs without inspecting component text."""

        if self.java_materialization_mode == "framework_slots":
            ordered = tuple(
                self.slot_parent_ids[slot_id]
                for slot_id in sorted(self.slot_parent_ids)
            )
        else:
            ordered = (
                *self.source_candidate_ids,
                self.strategy_parent_id,
                self.generation_prompt_parent_id if "generation_prompt" in self.active_genotype_components else None,
                self.java_parent_id if self.java_materialization_mode == "llm" else None,
            )
        unique: list[str] = []
        for candidate_id in ordered:
            if candidate_id is not None and candidate_id not in unique:
                unique.append(candidate_id)
        return tuple(unique)

    def lineage_to_json_dict(self) -> dict[str, Any]:
        """Serialize canonical first-class lineage independent of generic metadata."""

        payload = {
            "lineage_schema_version": (
                FRAMEWORK_SLOTS_LINEAGE_SCHEMA_VERSION
                if self.java_materialization_mode == "framework_slots"
                else LINEAGE_SCHEMA_VERSION
            ),
            **self.materialization_to_json_dict(),
            "candidate_id": self.id,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "operator": self.operator,
            "mutation_type": self.mutation_type,
            "source_candidate_ids": list(self.resolved_source_candidate_ids()),
        }
        if self.java_materialization_mode == "framework_slots":
            payload["slot_parent_ids"] = {
                slot_id: self.slot_parent_ids[slot_id]
                for slot_id in sorted(self.slot_parent_ids)
            }
        else:
            payload.update(
                strategy_parent_id=self.strategy_parent_id,
                generation_prompt_parent_id=(
                    self.generation_prompt_parent_id
                    if "generation_prompt" in self.active_genotype_components
                    else None
                ),
            )
        if self.java_materialization_mode == "llm" and (self.inherited_java or self.java_parent_id is not None):
            payload["java_parent_id"] = self.java_parent_id
        return payload


def compact_mutation_record(record: dict[str, Any]) -> dict[str, Any]:
    """Keep mutation routing/status in memory; raw evidence stays on disk."""

    keys = (
        "schema_version",
        "reflection_schema_version",
        "candidate_id",
        "feedback_candidate_id",
        "operation",
        "applied",
        "type",
        "compliance_status",
        "requested_rewrite_fields",
        "objectives",
        "evaluation_status",
        "token_counts",
        "model",
        "reflection_operation",
        "rewrite_operation",
        "revision_operation",
        "reflection_attempts",
        "rewrite_attempts",
        "revision_attempts",
        "reflection_status",
        "rewrite_status",
        "revision_status",
        "strategy_rewrite_status",
        "code_rewrite_status",
        "reflection_error",
        "rewrite_error",
        "revision_error",
        "reflection_model",
        "revision_model",
        "reflection_conclusion",
        "revision_required",
        "parent_java_sha256",
        "reflected_java_sha256",
        "java_changed",
        "mutation_intent",
        "parent_strategy_niche",
        "child_strategy_niche",
        "niche_changed",
        "prompt_metadata",
        "reflection_history",
    )
    return {key: record[key] for key in keys if key in record}


def compact_candidate_metadata(
    metadata: dict[str, Any],
    *,
    preserve_unpersisted_mutation: bool = False,
) -> dict[str, Any]:
    """Return only metadata required by selection, mutation, and resume."""

    compact: dict[str, Any] = {}
    for key in (
        "pre_crossover_code_checks",
        "seed_index",
        "replicate_index",
        "initial_policy_source",
        "initial_policy_sample_index",
        "framework_reproduction_route",
        "experimental_parent_evaluation",
        "failure_category",
        "failure_reason",
    ):
        if key in metadata:
            compact[key] = metadata[key]
    framework_selection = metadata.get("framework_coach_selection")
    if isinstance(framework_selection, dict):
        compact["framework_coach_selection"] = {
            key: framework_selection[key]
            for key in ("schema_version", "stage", "framework_bundle_sha256", "parent_candidate_id", "changed_slot_ids")
            if key in framework_selection
        }
    aos = metadata.get("aos")
    if isinstance(aos, dict):
        compact["aos"] = dict(aos)
    history = metadata.get("reflection_history")
    if isinstance(history, list):
        compact["reflection_history"] = [dict(item) for item in history[-1:] if isinstance(item, dict)]
    evidence = metadata.get("reflection_evidence")
    if isinstance(evidence, dict):
        compact["reflection_evidence"] = dict(evidence)
    mutation = metadata.get("mutation")
    if isinstance(mutation, dict):
        # Production mutation stages persist the full record first and place a
        # compact record in memory. Embedded callers without an artifact root
        # must carry the full record until write_candidate_artifacts can save it.
        compact["mutation"] = (
            dict(mutation)
            if preserve_unpersisted_mutation and "evidence" in mutation
            else compact_mutation_record(mutation)
        )
    return compact
