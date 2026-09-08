"""Candidate representation for evolved EAGLE individuals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .opponent_cases import LEXICASE_CASES, FAILED_OPPONENT_SCORE
from .prompts import load_prompt


ACTION_API_GUIDE = load_prompt("action_api_guide")
DEFAULT_GENERATION_PROMPT = load_prompt("initial_generation")

LINEAGE_SCHEMA_VERSION = "3.0"
CANDIDATE_SNAPSHOT_SCHEMA_VERSION = "eagle-candidate-v5"


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
    strategy_prompt: str = ""
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
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

    def __post_init__(self) -> None:
        """Give new candidates a sortable generation-qualified identity."""

        if not self.id:
            object.__setattr__(
                self,
                "id",
                f"gen_{self.generation:04d}_{uuid4().hex[:12]}",
            )

    def objective_vector(self) -> tuple[float, ...]:
        """Return the fixed opponent cases used by lexicase selection."""

        return tuple(float(self.fitness_objectives.get(case, FAILED_OPPONENT_SCORE)) for case in LEXICASE_CASES)

    def generation_input(
        self,
        *,
        class_name: str = "",
        module_name: str = "controller",
        agent_template_path: object | None = None,
    ) -> str:
        """Build one request for a complete single-file Java agent."""
        from generation.agent_template import JavaTemplatePaths, load_java_template

        # The default mode starts from the checked-in scaffold without parent
        # Java.  A candidate with inherited Java uses the explicitly separate
        # third-component generator resource.
        current_source = load_java_template(
            JavaTemplatePaths()
            if agent_template_path is None
            else JavaTemplatePaths(agent_template_path)
        )
        from .prompts import render_prompt

        values = {
            "policy_prompt": self.strategy_prompt.strip(),
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
            "candidate_schema_version": CANDIDATE_SNAPSHOT_SCHEMA_VERSION,
            "id": self.id,
            "candidate_id": self.id,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "strategy_prompt": self.strategy_prompt,
            "generation_prompt": self.generation_prompt,
            "generated_java": self.generated_java,
            "generated_java_path": self.generated_java_path,
            "operator": self.operator,
            "mutation_type": self.mutation_type,
            "strategy_parent_id": self.strategy_parent_id,
            "generation_prompt_parent_id": self.generation_prompt_parent_id,
            "source_candidate_ids": list(self.resolved_source_candidate_ids()),
            "compile_status": self.compile_status,
            "game_eval_result": dict(self.game_eval_result),
            "code_quality_result": dict(self.code_quality_result),
            "fitness_objectives": dict(self.fitness_objectives),
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
        if self.inherited_java or self.java_parent_id is not None:
            # The complete component is stored only at the genotype artifact
            # path. Snapshots retain provenance, not duplicate source bodies.
            payload["java_parent_id"] = self.java_parent_id
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

        return {
            "candidate_schema_version": CANDIDATE_SNAPSHOT_SCHEMA_VERSION,
            "candidate_id": self.id,
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
            "timing": dict(self.timing),
            "artifacts": dict(self.artifacts),
        }

    def resolved_source_candidate_ids(self) -> tuple[str, ...]:
        """Return stable contributing candidate IDs without inspecting component text."""

        ordered = (
            *self.source_candidate_ids,
            self.strategy_parent_id,
            self.generation_prompt_parent_id,
            self.java_parent_id,
        )
        unique: list[str] = []
        for candidate_id in ordered:
            if candidate_id is not None and candidate_id not in unique:
                unique.append(candidate_id)
        return tuple(unique)

    def lineage_to_json_dict(self) -> dict[str, Any]:
        """Serialize canonical first-class lineage independent of generic metadata."""

        payload = {
            "lineage_schema_version": LINEAGE_SCHEMA_VERSION,
            "candidate_id": self.id,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "operator": self.operator,
            "mutation_type": self.mutation_type,
            "strategy_parent_id": self.strategy_parent_id,
            "generation_prompt_parent_id": self.generation_prompt_parent_id,
            "source_candidate_ids": list(self.resolved_source_candidate_ids()),
        }
        if self.inherited_java or self.java_parent_id is not None:
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
        "seed_index",
        "replicate_index",
        "initial_policy_source",
        "initial_policy_sample_index",
        "failure_category",
        "failure_reason",
    ):
        if key in metadata:
            compact[key] = metadata[key]
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
