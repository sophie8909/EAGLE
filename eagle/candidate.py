"""Candidate representation for evolved EAGLE individuals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


ACTION_API_GUIDE = """Fixed action helpers already implemented in CandidateAgent.java:
- commandMove(Unit unit, int x, int y)
- commandHarvest(Unit worker, Unit resource, Unit base)
- commandTrain(Unit producer, UnitType unitType)
- commandBuild(Unit worker, UnitType buildingType, int x, int y)
- commandAttack(Unit attacker, Unit target)
- commandIdle(Unit unit)

Fixed lookup helpers:
- isIdleAlly(Unit unit, AgentContext context)
- nearestEnemy(Unit source, AgentContext context)
- nearestResource(Unit source, AgentContext context)
- ownBase(AgentContext context)

AgentContext exposes context.player, context.gs, and the snapshot context.units.
Known UnitType fields are resourceType, workerType, lightType, heavyType, rangedType, baseType, and barracksType."""

DEFAULT_GENERATION_PROMPT = (
    "Generate one complete, compilable CandidateAgent.java source file. "
    "Return the entire Java file from the package declaration through the final class brace. "
    "Return raw Java only: no markdown fence, JSON wrapper, explanation, placeholder, ellipsis, or omitted section. "
    "Preserve the package, class name, lifecycle methods, strategy-region comments, six action helpers, lookup helpers, and imports. "
    "Implement the marked strategy region with deterministic Java and do not call network, file, subprocess, environment, or runtime LLM APIs."
)

LINEAGE_SCHEMA_VERSION = "1.0"
CANDIDATE_SNAPSHOT_SCHEMA_VERSION = "eagle-candidate-v2"


@dataclass(frozen=True)
class Candidate:
    """One NSGA-II individual that generates one complete Java agent."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    generation: int = 0
    parent_ids: tuple[str, ...] = ()
    strategy_prompt: str = ""
    previous_code: str = ""
    generation_prompt: str = DEFAULT_GENERATION_PROMPT
    generated_java: str = ""
    generated_java_path: str | None = None
    operator: str = "seed"
    mutation_type: str | None = None
    strategy_parent_id: str | None = None
    previous_code_parent_id: str | None = None
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

    def objective_vector(self) -> tuple[float, ...]:
        if not self.fitness_objectives:
            return (0.0, 0.0)
        return (
            float(self.fitness_objectives.get("game_performance", 0.0)),
            float(self.fitness_objectives.get("code_quality", 0.0)),
        )

    def generation_input(self, *, class_name: str = "", module_name: str = "controller") -> str:
        """Build one request for a complete single-file Java agent."""
        from generation.agent_template import (
            JavaTemplatePaths,
            STRATEGY_END_MARKER,
            STRATEGY_START_MARKER,
            load_java_template,
        )

        previous_source = self.previous_code.strip()
        if (
            previous_source.startswith("package ai.generated;")
            and STRATEGY_START_MARKER in previous_source
            and STRATEGY_END_MARKER in previous_source
        ):
            current_source = previous_source
        else:
            current_source = load_java_template(JavaTemplatePaths())
        from .prompts import render_prompt

        return render_prompt(
            "java_generation",
            {
                "strategy_prompt": self.strategy_prompt.strip(),
                "action_api_guide": ACTION_API_GUIDE,
                "generation_prompt": self.generation_prompt.strip(),
                "current_source": current_source,
            },
        )

    def to_json_dict(self) -> dict[str, Any]:
        """Return the compact, resumable candidate snapshot.

        Raw match output, telemetry, and mutation LLM envelopes live in their
        canonical per-stage files.  Keeping them out of population snapshots
        prevents one verbose match log from being copied across every run-level
        artifact and recursively deep-copied by ``dataclasses.asdict``.
        """

        return {
            "candidate_schema_version": CANDIDATE_SNAPSHOT_SCHEMA_VERSION,
            "id": self.id,
            "candidate_id": self.id,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "strategy_prompt": self.strategy_prompt,
            "previous_code": self.previous_code,
            "generation_prompt": self.generation_prompt,
            "generated_java": self.generated_java,
            "generated_java_path": self.generated_java_path,
            "operator": self.operator,
            "mutation_type": self.mutation_type,
            "strategy_parent_id": self.strategy_parent_id,
            "previous_code_parent_id": self.previous_code_parent_id,
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

    def to_individual_dict(self) -> dict[str, Any]:
        """Return the small candidate index used by inspection/final test."""

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
            self.previous_code_parent_id,
            self.generation_prompt_parent_id,
        )
        unique: list[str] = []
        for candidate_id in ordered:
            if candidate_id is not None and candidate_id not in unique:
                unique.append(candidate_id)
        return tuple(unique)

    def lineage_to_json_dict(self) -> dict[str, Any]:
        """Serialize canonical first-class lineage independent of generic metadata."""

        return {
            "lineage_schema_version": LINEAGE_SCHEMA_VERSION,
            "candidate_id": self.id,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "operator": self.operator,
            "mutation_type": self.mutation_type,
            "strategy_parent_id": self.strategy_parent_id,
            "previous_code_parent_id": self.previous_code_parent_id,
            "generation_prompt_parent_id": self.generation_prompt_parent_id,
            "source_candidate_ids": list(self.resolved_source_candidate_ids()),
        }


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
        "objectives",
        "evaluation_status",
        "token_counts",
        "reflection_model",
        "reflection_profile",
        "rewrite_model",
        "rewrite_profile",
        "reflection_attempts",
        "rewrite_attempts",
        "reflection_status",
        "rewrite_status",
        "reflection_error",
        "rewrite_error",
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
    for key in ("seed_index", "failure_category", "failure_reason"):
        if key in metadata:
            compact[key] = metadata[key]
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
