"""Minimal adaptive operator selection for EAGLE reflection mutations."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from .candidate import Candidate


STRATEGY_REFLECTION = "strategy_reflection"
GENERATE_CODE_REFLECTION = "generate_code_reflection"
OPERATORS = (STRATEGY_REFLECTION, GENERATE_CODE_REFLECTION)
TRANSITIONS = (
    "failed_parent_to_runnable_child",
    "runnable_parent_to_failed_child",
    "failed_parent_to_failed_child",
    "runnable_parent_to_runnable_child",
)
OPERATOR_TO_MUTATION = {
    STRATEGY_REFLECTION: "strategy",
    GENERATE_CODE_REFLECTION: "code",
}


@dataclass(frozen=True)
class AOSConfig:
    """Small, research-facing configuration surface for probability matching."""

    enabled: bool = True
    initial_probabilities: tuple[tuple[str, float], ...] = (
        (STRATEGY_REFLECTION, 0.20),
        (GENERATE_CODE_REFLECTION, 0.80),
    )
    min_probability: float = 0.10
    credit_alpha: float = 0.20
    failure_reward: float = 0.0

    @classmethod
    def from_mapping(cls, payload: object) -> "AOSConfig":
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("aos must be a mapping.")
        initial = payload.get("initial_probabilities", {})
        if not isinstance(initial, dict):
            raise ValueError("aos.initial_probabilities must be a mapping.")
        values = {
            STRATEGY_REFLECTION: float(initial.get(STRATEGY_REFLECTION, 0.20)),
            GENERATE_CODE_REFLECTION: float(initial.get(GENERATE_CODE_REFLECTION, 0.80)),
        }
        credit = payload.get("credit", {})
        if not isinstance(credit, dict):
            raise ValueError("aos.credit must be a mapping.")
        reward = payload.get("reward", {})
        if not isinstance(reward, dict):
            raise ValueError("aos.reward must be a mapping.")
        return cls(
            enabled=bool(payload.get("enabled", True)),
            initial_probabilities=tuple(values.items()),
            min_probability=float(payload.get("min_probability", 0.10)),
            credit_alpha=float(credit.get("alpha", 0.20)),
            failure_reward=float(reward.get("execution_failure", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "initial_probabilities": dict(self.initial_probabilities),
            "min_probability": self.min_probability,
            "credit": {"alpha": self.credit_alpha},
            "reward": {"execution_failure": self.failure_reward},
        }

    def validate(self) -> None:
        configured = dict(self.initial_probabilities)
        if tuple(configured) != OPERATORS:
            raise ValueError(f"aos.initial_probabilities must contain exactly {OPERATORS}.")
        if any(value < 0 for value in configured.values()):
            raise ValueError("aos initial probabilities must be non-negative.")
        if sum(configured.values()) <= 0:
            raise ValueError("aos initial probabilities must have a positive sum.")
        if not 0.0 <= self.min_probability < 0.5:
            raise ValueError("aos.min_probability must be in [0, 0.5).")
        if not 0.0 < self.credit_alpha <= 1.0:
            raise ValueError("aos.credit.alpha must be in (0, 1].")
        if self.failure_reward != 0.0:
            raise ValueError("aos.reward.execution_failure must be 0.0 for the [0, 1] contract.")


@dataclass(frozen=True)
class OperatorReward:
    operator: str
    comparison_parent_id: str
    offspring_id: str
    reward: float
    reward_source: str
    comparison_parent_runnable: bool
    offspring_runnable: bool
    generation: int = 0
    head_to_head: dict[str, Any] = field(default_factory=dict)
    transition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "offspring_id": self.offspring_id,
            "comparison_parent_id": self.comparison_parent_id,
            "operator": OPERATOR_TO_MUTATION[self.operator],
            "operator_id": self.operator,
            "reward": self.reward,
            "reward_source": self.reward_source,
            "comparison_parent_runnable": self.comparison_parent_runnable,
            "offspring_runnable": self.offspring_runnable,
            "head_to_head": dict(self.head_to_head),
            "transition": self.transition,
        }


class AdaptiveOperatorSelection:
    """Generation-level probability matching over the two reflection operators."""

    def __init__(self, config: AOSConfig, *, state: dict[str, Any] | None = None) -> None:
        config.validate()
        self.config = config
        self.probabilities = self._normalize(dict(config.initial_probabilities))
        self.credits = {operator: 0.0 for operator in OPERATORS}
        self.total_usage = {operator: 0 for operator in OPERATORS}
        self.total_reward_count = {operator: 0 for operator in OPERATORS}
        self.total_reward_sum = {operator: 0.0 for operator in OPERATORS}
        self.total_transition_counts = {transition: 0 for transition in TRANSITIONS}
        self._generation_usage = {operator: 0 for operator in OPERATORS}
        self._last_generation: dict[str, Any] = self._empty_generation_record()
        if state:
            self._restore(state)

    @classmethod
    def from_state(cls, config: AOSConfig, state: dict[str, Any] | None) -> "AdaptiveOperatorSelection":
        return cls(config, state=state)

    def select_operator(self, rng) -> str:
        """Select using the probabilities fixed for the current generation."""

        draw = rng.random()
        boundary = self.probabilities[OPERATORS[0]]
        operator = OPERATORS[0] if draw < boundary else OPERATORS[1]
        self._generation_usage[operator] += 1
        self.total_usage[operator] += 1
        return operator

    def probability(self, operator: str) -> float:
        return float(self.probabilities[operator])

    def initial_generation_record(self) -> dict[str, Any]:
        probabilities = dict(self.probabilities)
        qualities = dict(self.credits)
        return {
            "schema_version": "eagle-aos-v2",
            "selection_probabilities": probabilities,
            "post_update_probabilities": probabilities,
            "operators": self._operator_records(
                probabilities, probabilities, qualities, self._empty_generation_record()
            ),
            "transition_counts": {transition: 0 for transition in TRANSITIONS},
            "state": self.state_dict(),
        }

    def update_generation(self, rewards: list[OperatorReward]) -> dict[str, Any]:
        before = dict(self.probabilities)
        quality_before = dict(self.credits)
        grouped = {operator: [] for operator in OPERATORS}
        head_to_head = {
            operator: {"wins": 0, "draws": 0, "losses": 0, "errors": 0, "total_matches": 0}
            for operator in OPERATORS
        }
        transition_counts = {transition: 0 for transition in TRANSITIONS}
        for reward in rewards:
            if reward.operator in grouped:
                if not 0.0 <= float(reward.reward) <= 1.0:
                    raise ValueError("AOS rewards must be in [0, 1].")
                grouped[reward.operator].append(float(reward.reward))
                for key in head_to_head[reward.operator]:
                    head_to_head[reward.operator][key] += int(reward.head_to_head.get(key) or 0)
            if reward.transition in transition_counts:
                transition_counts[reward.transition] += 1
        generation_stats = self._empty_generation_record()
        for operator in OPERATORS:
            values = grouped[operator]
            generation_stats[operator] = {
                "usage_count": self._generation_usage[operator],
                "reward_count": len(values),
                "mean_reward": statistics.fmean(values) if values else None,
                "head_to_head": head_to_head[operator],
            }
            if values:
                self.credits[operator] = (
                    (1.0 - self.config.credit_alpha) * self.credits[operator]
                    + self.config.credit_alpha * statistics.fmean(values)
                )
                self.total_reward_count[operator] += len(values)
                self.total_reward_sum[operator] += sum(values)
        for transition, count in transition_counts.items():
            self.total_transition_counts[transition] += count
        if self.config.enabled:
            self.probabilities = self._probability_match(self.credits)
        after = dict(self.probabilities)
        record = {
            "schema_version": "eagle-aos-v2",
            "selection_probabilities": before,
            "post_update_probabilities": after,
            "operators": self._operator_records(before, after, quality_before, generation_stats),
            "transition_counts": transition_counts,
            "cumulative_transition_counts": dict(self.total_transition_counts),
            "state": self.state_dict(),
        }
        self._last_generation = record
        self._generation_usage = {operator: 0 for operator in OPERATORS}
        return record

    def state_dict(self) -> dict[str, Any]:
        return {
            "probabilities": dict(self.probabilities),
            "credits": dict(self.credits),
            "total_usage": dict(self.total_usage),
            "total_reward_count": dict(self.total_reward_count),
            "total_reward_sum": dict(self.total_reward_sum),
            "total_transition_counts": dict(self.total_transition_counts),
        }

    def _restore(self, state: dict[str, Any]) -> None:
        self.probabilities = self._normalize({
            operator: float((state.get("probabilities") or {}).get(operator, self.probabilities[operator]))
            for operator in OPERATORS
        })
        for attribute, default in (
            ("credits", 0.0),
            ("total_usage", 0),
            ("total_reward_count", 0),
            ("total_reward_sum", 0.0),
        ):
            values = state.get(attribute) or {}
            target = getattr(self, attribute)
            for operator in OPERATORS:
                target[operator] = type(default)(values.get(operator, default))
        transition_values = state.get("total_transition_counts") or {}
        for transition in TRANSITIONS:
            self.total_transition_counts[transition] = int(transition_values.get(transition, 0))

    def _normalize(self, values: dict[str, float]) -> dict[str, float]:
        values = {operator: max(0.0, values[operator]) for operator in OPERATORS}
        total = sum(values.values())
        if total <= 0:
            values = {operator: 1.0 for operator in OPERATORS}
            total = float(len(OPERATORS))
        normalized = {operator: values[operator] / total for operator in OPERATORS}
        floor = self.config.min_probability
        below_floor = [operator for operator in OPERATORS if normalized[operator] < floor]
        if not below_floor:
            return normalized
        fixed_total = floor * len(below_floor)
        remaining = 1.0 - fixed_total
        above_total = sum(normalized[operator] for operator in OPERATORS if operator not in below_floor)
        return {
            operator: floor if operator in below_floor else remaining * normalized[operator] / above_total
            for operator in OPERATORS
        }

    def _probability_match(self, credits: dict[str, float]) -> dict[str, float]:
        positive = {operator: max(0.0, credits[operator]) for operator in OPERATORS}
        if sum(positive.values()) <= 0:
            return self._normalize(self.probabilities)
        return self._normalize(positive)

    def _empty_generation_record(self) -> dict[str, Any]:
        return {
            operator: {
                "usage_count": 0,
                "reward_count": 0,
                "mean_reward": None,
                "head_to_head": {
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "errors": 0,
                    "total_matches": 0,
                },
            }
            for operator in OPERATORS
        }

    def _operator_records(
        self,
        before: dict[str, float],
        after: dict[str, float],
        quality_before: dict[str, float],
        generation_stats: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            operator: {
                **generation_stats[operator],
                "operator_quality_before": quality_before[operator],
                "operator_quality_after": self.credits[operator],
                "recent_credit": self.credits[operator],
                "selection_probability_before": before[operator],
                "selection_probability": after[operator],
                "cumulative_usage_count": self.total_usage[operator],
                "cumulative_reward_count": self.total_reward_count[operator],
                "cumulative_mean_reward": (
                    self.total_reward_sum[operator] / self.total_reward_count[operator]
                    if self.total_reward_count[operator] else None
                ),
            }
            for operator in OPERATORS
        }


def is_runnable(candidate: Candidate) -> bool:
    """Return true only for a candidate that completed the actual matrix."""

    if candidate.status == "failed" or candidate.failure_stage or candidate.failure_reason:
        return False
    game = candidate.game_eval_result or {}
    expected = int(game.get("expected_match_count") or 0)
    completed = int(game.get("completed_match_count") or 0)
    return bool(game) and expected > 0 and completed == expected and not int(game.get("missing_match_count") or 0)


def can_run_as_comparison_parent(candidate: Candidate) -> bool:
    """Return whether compiled parent bytecode can enter a direct match."""

    return bool(
        candidate.generated_java
        and candidate.compile_status == "success"
        and candidate.failure_stage not in {"generation", "validation", "compilation", "integration"}
    )


def calculate_operator_reward(
    parent: Candidate,
    child: Candidate,
    *,
    operator: str,
    config: AOSConfig,
    head_to_head: dict[str, Any] | None = None,
) -> OperatorReward:
    """Assign execution-first credit, then direct parent-match credit."""

    parent_runnable = is_runnable(parent)
    child_runnable = is_runnable(child)
    transition = f"{'runnable' if parent_runnable else 'failed'}_parent_to_{'runnable' if child_runnable else 'failed'}_child"
    if not child_runnable:
        return OperatorReward(
            operator=operator,
            comparison_parent_id=parent.id,
            offspring_id=child.id,
            reward=config.failure_reward,
            reward_source="execution_failure",
            comparison_parent_runnable=parent_runnable,
            offspring_runnable=False,
            generation=child.generation,
            head_to_head={} if head_to_head is None else {
                key: value for key, value in head_to_head.items() if key != "reward"
            },
            transition=transition,
        )
    if head_to_head is not None and "reward" in head_to_head:
        reward = float(head_to_head.get("reward", 0.0))
        if not 0.0 <= reward <= 1.0:
            raise ValueError("Head-to-head reward must be in [0, 1].")
        return OperatorReward(
            operator=operator,
            comparison_parent_id=parent.id,
            offspring_id=child.id,
            reward=reward,
            reward_source="parent_vs_offspring",
            comparison_parent_runnable=parent_runnable,
            offspring_runnable=True,
            generation=child.generation,
            head_to_head={key: value for key, value in head_to_head.items() if key != "reward"},
            transition=transition,
        )
    if not can_run_as_comparison_parent(parent):
        return OperatorReward(
            operator=operator,
            comparison_parent_id=parent.id,
            offspring_id=child.id,
            reward=1.0,
            reward_source="comparison_parent_execution_failure",
            comparison_parent_runnable=False,
            offspring_runnable=True,
            generation=child.generation,
            head_to_head={} if head_to_head is None else dict(head_to_head),
            transition=transition,
        )
    raise ValueError("Runnable offspring and comparison parent require head-to-head evidence.")
