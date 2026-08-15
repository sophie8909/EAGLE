"""Minimal adaptive operator selection for EAGLE reflection mutations."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from .candidate import Candidate
from .opponent_cases import LEXICASE_CASES


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
    repaired_execution_reward: float = 1.0
    broke_execution_reward: float = -1.0
    still_failed_reward: float = -0.1

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
            repaired_execution_reward=float(reward.get("repaired_execution", 1.0)),
            broke_execution_reward=float(reward.get("broke_execution", -1.0)),
            still_failed_reward=float(reward.get("still_failed", -0.1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "initial_probabilities": dict(self.initial_probabilities),
            "min_probability": self.min_probability,
            "credit": {"alpha": self.credit_alpha},
            "reward": {
                "repaired_execution": self.repaired_execution_reward,
                "broke_execution": self.broke_execution_reward,
                "still_failed": self.still_failed_reward,
            },
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


@dataclass(frozen=True)
class OperatorReward:
    operator: str
    parent_candidate_id: str
    child_candidate_id: str
    reward: float
    parent_runnable: bool
    child_runnable: bool
    improved_cases: tuple[str, ...] = ()
    regressed_cases: tuple[str, ...] = ()
    unchanged_cases: tuple[str, ...] = ()
    compared_cases: int = 0
    transition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_used": self.operator,
            "parent_candidate_id": self.parent_candidate_id,
            "child_candidate_id": self.child_candidate_id,
            "operator_reward": self.reward,
            "parent_runnable": self.parent_runnable,
            "child_runnable": self.child_runnable,
            "improved_cases": list(self.improved_cases),
            "regressed_cases": list(self.regressed_cases),
            "unchanged_cases": list(self.unchanged_cases),
            "compared_cases": self.compared_cases,
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
        return {
            "schema_version": "eagle-aos-v1",
            "selection_probabilities": probabilities,
            "post_update_probabilities": probabilities,
            "operators": self._operator_records(probabilities, probabilities, self._empty_generation_record()),
            "transition_counts": {transition: 0 for transition in TRANSITIONS},
            "state": self.state_dict(),
        }

    def update_generation(self, rewards: list[OperatorReward]) -> dict[str, Any]:
        before = dict(self.probabilities)
        grouped = {operator: [] for operator in OPERATORS}
        transition_counts = {transition: 0 for transition in TRANSITIONS}
        for reward in rewards:
            if reward.operator in grouped:
                grouped[reward.operator].append(float(reward.reward))
            if reward.transition in transition_counts:
                transition_counts[reward.transition] += 1
        generation_stats = self._empty_generation_record()
        for operator in OPERATORS:
            values = grouped[operator]
            generation_stats[operator] = {
                "usage_count": self._generation_usage[operator],
                "reward_count": len(values),
                "mean_reward": statistics.fmean(values) if values else None,
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
            "schema_version": "eagle-aos-v1",
            "selection_probabilities": before,
            "post_update_probabilities": after,
            "operators": self._operator_records(before, after, generation_stats),
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
            ("total_transition_counts", 0),
        ):
            values = state.get(attribute) or {}
            target = getattr(self, attribute)
            for operator in OPERATORS:
                target[operator] = type(default)(values.get(operator, default))

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
            operator: {"usage_count": 0, "reward_count": 0, "mean_reward": None}
            for operator in OPERATORS
        }

    def _operator_records(
        self,
        before: dict[str, float],
        after: dict[str, float],
        generation_stats: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            operator: {
                **generation_stats[operator],
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


def opponent_result_ranks(candidate: Candidate) -> dict[str, int | None]:
    """Map canonical opponent summaries to LOSS=0, DRAW=1, WIN=2."""

    rows = {
        str(row.get("opponent_id")): row
        for row in (candidate.game_eval_result or {}).get("opponent_results") or []
        if isinstance(row, dict) and row.get("opponent_id")
    }
    ranks: dict[str, int | None] = {}
    for case in LEXICASE_CASES:
        row = rows.get(case)
        if row is None or str(row.get("status") or "").lower() != "completed":
            ranks[case] = None
            continue
        try:
            wins = int(row.get("wins") or 0)
            losses = int(row.get("losses") or 0)
        except (TypeError, ValueError):
            ranks[case] = None
            continue
        ranks[case] = 2 if wins > losses else 0 if losses > wins else 1
    return ranks


def calculate_operator_reward(
    parent: Candidate,
    child: Candidate,
    *,
    operator: str,
    config: AOSConfig,
) -> OperatorReward:
    """Assign execution-first, then opponent-case parent-child credit."""

    parent_runnable = is_runnable(parent)
    child_runnable = is_runnable(child)
    transition = f"{'runnable' if parent_runnable else 'failed'}_parent_to_{'runnable' if child_runnable else 'failed'}_child"
    if not parent_runnable and child_runnable:
        reward = config.repaired_execution_reward
        return OperatorReward(operator, parent.id, child.id, reward, parent_runnable, child_runnable, transition=transition)
    if parent_runnable and not child_runnable:
        reward = config.broke_execution_reward
        return OperatorReward(operator, parent.id, child.id, reward, parent_runnable, child_runnable, transition=transition)
    if not parent_runnable and not child_runnable:
        reward = config.still_failed_reward
        return OperatorReward(operator, parent.id, child.id, reward, parent_runnable, child_runnable, transition=transition)

    parent_ranks = opponent_result_ranks(parent)
    child_ranks = opponent_result_ranks(child)
    improved = tuple(case for case in LEXICASE_CASES if parent_ranks[case] is not None and child_ranks[case] is not None and child_ranks[case] > parent_ranks[case])
    regressed = tuple(case for case in LEXICASE_CASES if parent_ranks[case] is not None and child_ranks[case] is not None and child_ranks[case] < parent_ranks[case])
    unchanged = tuple(case for case in LEXICASE_CASES if parent_ranks[case] is not None and child_ranks[case] is not None and child_ranks[case] == parent_ranks[case])
    compared = len(improved) + len(regressed) + len(unchanged)
    reward = (len(improved) - len(regressed)) / compared if compared else 0.0
    return OperatorReward(
        operator, parent.id, child.id, reward, parent_runnable, child_runnable,
        improved, regressed, unchanged, compared, transition,
    )
