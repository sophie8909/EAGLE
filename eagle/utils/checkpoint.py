"""Serialize, store, and reload algorithm checkpoint state on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eagle.evolution.component.individual import Individual
from .profiler import write_jsonl


def serialize_individual(individual: Individual) -> dict[str, Any]:
    """Convert one runtime individual into a JSON-safe checkpoint record."""
    payload: dict[str, Any] = {
        "id": getattr(individual, "id", None),
        "game_rule": individual.game_rule,
        "component_indices": dict(getattr(individual, "component_indices", {}) or {}),
        "fitness": list(individual.fitness) if isinstance(individual.fitness, (list, tuple)) else individual.fitness,
        "rendered_prompt": getattr(individual, "rendered_prompt", ""),
        "evaluation_mode": getattr(individual, "evaluation_mode", None),
        "metadata": dict(getattr(individual, "metadata", {}) or {}),
        "training_examples": list(getattr(individual, "training_examples", []) or []),
    }

    operator_profile = getattr(individual, "operator_profile", None)
    if isinstance(operator_profile, dict):
        payload["operator_profile"] = dict(operator_profile)

    mutation_metadata = getattr(individual, "mutation_metadata", None)
    if isinstance(mutation_metadata, dict):
        payload["mutation_metadata"] = dict(mutation_metadata)

    reflection_metadata = getattr(individual, "reflection_metadata", None)
    if isinstance(reflection_metadata, dict):
        payload["reflection_metadata"] = dict(reflection_metadata)

    last_round_evaluation = getattr(individual, "last_round_evaluation", None)
    if isinstance(last_round_evaluation, dict):
        payload["last_round_evaluation"] = dict(last_round_evaluation)

    last_gameplay_evaluation = getattr(individual, "last_gameplay_evaluation", None)
    if isinstance(last_gameplay_evaluation, dict):
        payload["last_gameplay_evaluation"] = dict(last_gameplay_evaluation)

    last_surrogate_evaluation = getattr(individual, "last_surrogate_evaluation", None)
    if isinstance(last_surrogate_evaluation, dict):
        payload["last_surrogate_evaluation"] = dict(last_surrogate_evaluation)

    for attr in ("pareto_rank", "crowding_distance", "ea_llm_call_time", "surrogate_score", "gameplay_score"):
        if hasattr(individual, attr):
            payload[attr] = getattr(individual, attr)

    return payload


def deserialize_individual(payload: dict[str, Any]) -> Individual:
    """Restore one individual from a checkpoint record."""
    individual = Individual(
        id=payload.get("id"),
        game_rule=payload.get("game_rule", 0),
        component_indices=dict(payload.get("component_indices") or {}),
    )

    fitness = payload.get("fitness")
    if fitness is not None:
        individual.fitness = fitness
    individual.rendered_prompt = str(payload.get("rendered_prompt") or "")
    individual.evaluation_mode = payload.get("evaluation_mode")
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        individual.metadata = dict(metadata)
    training_examples = payload.get("training_examples")
    if isinstance(training_examples, list):
        individual.training_examples = [dict(example) for example in training_examples if isinstance(example, dict)]

    operator_profile = payload.get("operator_profile")
    if isinstance(operator_profile, dict):
        individual.operator_profile = dict(operator_profile)

    mutation_metadata = payload.get("mutation_metadata")
    if isinstance(mutation_metadata, dict):
        individual.mutation_metadata = dict(mutation_metadata)

    reflection_metadata = payload.get("reflection_metadata")
    if isinstance(reflection_metadata, dict):
        individual.reflection_metadata = dict(reflection_metadata)

    last_round_evaluation = payload.get("last_round_evaluation")
    if isinstance(last_round_evaluation, dict):
        individual.last_round_evaluation = dict(last_round_evaluation)

    last_gameplay_evaluation = payload.get("last_gameplay_evaluation")
    if isinstance(last_gameplay_evaluation, dict):
        individual.last_gameplay_evaluation = dict(last_gameplay_evaluation)

    last_surrogate_evaluation = payload.get("last_surrogate_evaluation")
    if isinstance(last_surrogate_evaluation, dict):
        individual.last_surrogate_evaluation = dict(last_surrogate_evaluation)

    for attr in ("pareto_rank", "crowding_distance", "ea_llm_call_time", "surrogate_score", "gameplay_score"):
        if attr in payload:
            setattr(individual, attr, payload[attr])

    return individual


class CheckpointManager:
    """Persist and restore EA runtime state from the run log directory."""

    def __init__(self, log_dir: Path):
        """Bind the checkpoint manager to one experiment log directory."""
        self.log_dir = Path(log_dir)
        self.state_path = self.log_dir / "run_state.json"
        self.event_log_path = self.log_dir / "checkpoints.jsonl"

    def load_state(self) -> dict[str, Any] | None:
        """Load the latest point-in-time checkpoint if one exists."""
        if self.state_path.exists():
            with self.state_path.open("r", encoding="utf-8") as f:
                return json.load(f)

        if not self.event_log_path.exists():
            return None

        last_record: dict[str, Any] | None = None
        with self.event_log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                last_record = json.loads(line)
        return last_record

    def save_state(self, state: dict[str, Any]) -> None:
        """Rewrite the latest run state and append the same snapshot as an event."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        write_jsonl(state, self.event_log_path)
