"""Reflection-operator selection and adaptive credit assignment for EAGLE."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from evaluation.parent_offspring import evaluate_parent_vs_offspring

from .candidate import Candidate
from .opponent_cases import LEXICASE_CASES


STRATEGY_REFLECTION = "strategy_reflection"
PROMPT_REFLECTION = "prompt_reflection"
CODE_REFLECTION = "code_reflection"
OPERATORS = (
    STRATEGY_REFLECTION,
    PROMPT_REFLECTION,
    CODE_REFLECTION,
)
TRANSITIONS = (
    "failed_parent_to_runnable_child",
    "runnable_parent_to_failed_child",
    "failed_parent_to_failed_child",
    "runnable_parent_to_runnable_child",
)
OPERATOR_TO_MUTATION = {
    STRATEGY_REFLECTION: "strategy",
    PROMPT_REFLECTION: "prompt",
    CODE_REFLECTION: "code",
}


def _select_eligible_operator(
    rng: Any,
    probabilities: dict[str, float],
    eligible: tuple[str, ...],
) -> str:
    """Draw from configured probabilities after applying operator preconditions."""

    if not eligible or any(operator not in OPERATORS for operator in eligible):
        raise ValueError(f"eligible operators must be a non-empty subset of {OPERATORS!r}.")
    draw_unit = rng.random()
    if len(eligible) == 1:
        return eligible[0]
    weights = {operator: float(probabilities[operator]) for operator in eligible}
    total = sum(weights.values())
    if total <= 0.0:
        raise ValueError("eligible operator probabilities must have positive total weight.")
    draw = draw_unit * total
    cumulative = 0.0
    for operator in eligible:
        cumulative += weights[operator]
        if draw < cumulative:
            return operator
    return eligible[-1]

# These are historical algorithm constants, not experiment configuration.
AOS_CREDIT_ALPHA = 0.20
OPPONENT_REPAIRED_EXECUTION_REWARD = 1.0
OPPONENT_BROKE_EXECUTION_REWARD = -1.0
OPPONENT_STILL_FAILED_REWARD = -0.1
HEAD_TO_HEAD_EXECUTION_FAILURE_REWARD = 0.0


class ReflectionOperatorMode(str, Enum):
    """The three canonical reflection-operator experimental conditions."""

    STATIC = "static"
    AOS_OPPONENT = "aos_opponent"
    AOS_HEAD2HEAD = "aos_head2head"

    @classmethod
    def parse(cls, value: object) -> "ReflectionOperatorMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"reflection_operator_mode must be one of: {allowed}; got {value!r}."
            ) from exc

    @property
    def adaptive(self) -> bool:
        return self is not ReflectionOperatorMode.STATIC

    @property
    def reward_source(self) -> str:
        return {
            ReflectionOperatorMode.STATIC: "static",
            ReflectionOperatorMode.AOS_OPPONENT: "opponent",
            ReflectionOperatorMode.AOS_HEAD2HEAD: "head2head",
        }[self]


@dataclass(frozen=True)
class ReflectionOperatorSettings:
    """Validated internal settings shared by operator selectors."""

    mode: ReflectionOperatorMode = ReflectionOperatorMode.AOS_HEAD2HEAD
    strategy_probability: float = 0.20
    prompt_probability: float = 0.80
    code_probability: float = 0.0
    minimum_probability: float = 0.10
    credit_alpha: float = AOS_CREDIT_ALPHA

    @property
    def initial_probabilities(self) -> dict[str, float]:
        return {
            STRATEGY_REFLECTION: self.strategy_probability,
            PROMPT_REFLECTION: self.prompt_probability,
            CODE_REFLECTION: self.code_probability,
        }

    @property
    def enabled_operators(self) -> tuple[str, ...]:
        return tuple(
            operator
            for operator, probability in self.initial_probabilities.items()
            if probability > 0.0
        )

    def validate(self) -> None:
        values = {
            "strategy_reflection_probability": self.strategy_probability,
            "prompt_reflection_probability": self.prompt_probability,
            "code_reflection_probability": self.code_probability,
        }
        for name, value in values.items():
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a finite number in [0, 1]; got {value!r}.")
        if not math.isclose(sum(values.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                "strategy_reflection_probability + prompt_reflection_probability + "
                "code_reflection_probability "
                f"must equal 1.0; got {sum(values.values()):.12g}."
            )
        if not math.isfinite(self.minimum_probability):
            raise ValueError("aos_minimum_probability must be finite.")
        enabled_count = len(self.enabled_operators)
        if enabled_count == 0:
            raise ValueError("At least one reflection operator probability must be positive.")
        if self.mode.adaptive and not 0.0 <= self.minimum_probability <= 1.0 / enabled_count:
            raise ValueError(
                f"aos_minimum_probability must be in [0, {1.0 / enabled_count:.12g}] for "
                f"{enabled_count} enabled operators "
                f"in {self.mode.value} mode; got {self.minimum_probability!r}."
            )
        if not 0.0 < self.credit_alpha <= 1.0:
            raise ValueError("Internal AOS credit alpha must be in (0, 1].")


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
    opponent_comparison: dict[str, Any] = field(default_factory=dict)
    transition: str = ""
    reward_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "offspring_id": self.offspring_id,
            "comparison_parent_id": self.comparison_parent_id,
            "operator": OPERATOR_TO_MUTATION[self.operator],
            "operator_id": self.operator,
            "reward": self.reward,
            "reward_source": self.reward_source,
            "reward_reason": self.reward_reason,
            "comparison_parent_runnable": self.comparison_parent_runnable,
            "offspring_runnable": self.offspring_runnable,
            "head_to_head": dict(self.head_to_head),
            "opponent_comparison": dict(self.opponent_comparison),
            "transition": self.transition,
        }


class AdaptiveOperatorSelection:
    """The one canonical EMA/probability-matching updater for both AOS modes."""

    def __init__(self, settings: ReflectionOperatorSettings, *, state: dict[str, Any] | None = None) -> None:
        settings.validate()
        if not settings.mode.adaptive:
            raise ValueError("AdaptiveOperatorSelection requires an adaptive reflection operator mode.")
        self.settings = settings
        # Valid config already sums to one. The floor applies only to adaptive
        # updates, so the configured initial probabilities remain exact.
        self.probabilities = dict(settings.initial_probabilities)
        self.credits = {operator: 0.0 for operator in OPERATORS}
        self.total_usage = {operator: 0 for operator in OPERATORS}
        self.total_reward_count = {operator: 0 for operator in OPERATORS}
        self.total_reward_sum = {operator: 0.0 for operator in OPERATORS}
        self.total_transition_counts = {transition: 0 for transition in TRANSITIONS}
        self._generation_usage = {operator: 0 for operator in OPERATORS}
        if state:
            self._restore(state)

    def select_operator(self, rng, *, eligible: tuple[str, ...] = OPERATORS) -> str:
        operator = _select_eligible_operator(rng, self.probabilities, eligible)
        self._generation_usage[operator] += 1
        self.total_usage[operator] += 1
        return operator

    def probability(self, operator: str) -> float:
        return float(self.probabilities[operator])

    def update_generation(self, rewards: list[OperatorReward]) -> dict[str, Any]:
        before = dict(self.probabilities)
        quality_before = dict(self.credits)
        grouped = {operator: [] for operator in OPERATORS}
        head_to_head = {operator: _empty_head_to_head_totals() for operator in OPERATORS}
        opponent_comparison = {operator: _empty_opponent_totals() for operator in OPERATORS}
        transition_counts = {transition: 0 for transition in TRANSITIONS}
        for reward in rewards:
            if reward.operator in grouped:
                grouped[reward.operator].append(float(reward.reward))
                for key in head_to_head[reward.operator]:
                    head_to_head[reward.operator][key] += int(reward.head_to_head.get(key) or 0)
                for key in opponent_comparison[reward.operator]:
                    value = reward.opponent_comparison.get(key) or ()
                    opponent_comparison[reward.operator][key] += (
                        len(value) if isinstance(value, (list, tuple)) else int(value or 0)
                    )
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
                "opponent_comparison": opponent_comparison[operator],
            }
            if values:
                mean_reward = statistics.fmean(values)
                self.credits[operator] = (
                    (1.0 - self.settings.credit_alpha) * self.credits[operator]
                    + self.settings.credit_alpha * mean_reward
                )
                self.total_reward_count[operator] += len(values)
                self.total_reward_sum[operator] += sum(values)
        for transition, count in transition_counts.items():
            self.total_transition_counts[transition] += count
        self.probabilities = self._probability_match(self.credits)
        after = dict(self.probabilities)
        record = {
            "operators": self._operator_records(before, after, quality_before, generation_stats),
            "transition_counts": transition_counts,
            "cumulative_transition_counts": dict(self.total_transition_counts),
        }
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
        restored = {
            operator: float((state.get("probabilities") or {}).get(operator, self.probabilities[operator]))
            for operator in OPERATORS
        }
        if any(not math.isfinite(value) or value < 0.0 for value in restored.values()) or not math.isclose(
            sum(restored.values()), 1.0, rel_tol=0.0, abs_tol=1e-9
        ):
            raise ValueError("Persisted reflection-operator probabilities are invalid.")
        self.probabilities = restored
        for attribute, converter in (
            ("credits", float),
            ("total_usage", int),
            ("total_reward_count", int),
            ("total_reward_sum", float),
        ):
            values = state.get(attribute) or {}
            target = getattr(self, attribute)
            for operator in OPERATORS:
                target[operator] = converter(values.get(operator, target[operator]))
        transition_values = state.get("total_transition_counts") or {}
        for transition in TRANSITIONS:
            self.total_transition_counts[transition] = int(transition_values.get(transition, 0))

    def _normalize_with_floor(self, values: dict[str, float]) -> dict[str, float]:
        enabled = self.settings.enabled_operators
        positive = {
            operator: max(0.0, values[operator]) if operator in enabled else 0.0
            for operator in OPERATORS
        }
        total = sum(positive.values())
        if total <= 0:
            positive = dict(self.probabilities)
            total = sum(positive.values())
        normalized = {operator: positive[operator] / total for operator in OPERATORS}
        floor = self.settings.minimum_probability
        below_floor = [operator for operator in enabled if normalized[operator] < floor]
        if not below_floor:
            return normalized
        fixed_total = floor * len(below_floor)
        remaining = 1.0 - fixed_total
        above_total = sum(normalized[operator] for operator in enabled if operator not in below_floor)
        if above_total <= 0:
            return {operator: 1.0 / len(enabled) if operator in enabled else 0.0 for operator in OPERATORS}
        return {
            operator: 0.0 if operator not in enabled else (
                floor if operator in below_floor else remaining * normalized[operator] / above_total
            )
            for operator in OPERATORS
        }

    def _probability_match(self, credits: dict[str, float]) -> dict[str, float]:
        return self._normalize_with_floor({operator: max(0.0, credits[operator]) for operator in OPERATORS})

    def _empty_generation_record(self) -> dict[str, Any]:
        return {
            operator: {
                "usage_count": 0,
                "reward_count": 0,
                "mean_reward": None,
                "head_to_head": _empty_head_to_head_totals(),
                "opponent_comparison": _empty_opponent_totals(),
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


class RewardProvider(Protocol):
    source: str

    def collect(
        self,
        parents: list[Candidate],
        children: list[Candidate],
        *,
        config: Any,
        candidates_dir: Path,
        classes_dir: Path,
        mock: bool,
    ) -> tuple[list[Candidate], list[OperatorReward]]: ...


class OpponentRewardProvider:
    """Historical reward restored from 5d8a30d^ (tree 7e7604c; introduced e481954)."""

    source = "opponent"

    def collect(self, parents, children, *, config, candidates_dir, classes_dir, mock):
        del config, candidates_dir, classes_dir, mock
        return _collect_selected_rewards(parents, children, calculate_opponent_reward)


class HeadToHeadRewardProvider:
    """Current direct parent-vs-offspring reward provider."""

    source = "head2head"

    def collect(self, parents, children, *, config, candidates_dir, classes_dir, mock):
        parent_by_id = {candidate.id: candidate for candidate in parents}
        updated: list[Candidate] = []
        rewards: list[OperatorReward] = []
        for child in children:
            selection = child.metadata.get("aos") or {}
            operator = selection.get("operator_id")
            parent_id = selection.get("comparison_parent_id")
            if not operator or not parent_id or parent_id not in parent_by_id:
                updated.append(child)
                continue
            parent = parent_by_id[parent_id]
            evidence = {
                "maps": list(config.evaluation_maps),
                "rounds": list(range(config.rounds_per_map)),
                "sides": ["offspring_p0_parent_p1", "parent_p0_offspring_p1"],
                **_empty_head_to_head_totals(),
                "valid_matches": 0,
                "skipped_reason": (
                    "execution_failure" if not is_runnable(child)
                    else "comparison_parent_execution_failure"
                ),
            }
            if is_runnable(child) and can_run_as_comparison_parent(parent):
                direct = evaluate_parent_vs_offspring(
                    child,
                    parent,
                    config=config,
                    classes_dir=classes_dir,
                    match_artifacts_dir=candidates_dir / child.id / "aos" / "head_to_head" / "matches",
                    mock=mock,
                )
                evidence = {"reward": direct.reward, **direct.to_dict()}
            reward = calculate_head_to_head_reward(parent, child, operator=operator, head_to_head=evidence)
            child = _attach_reward(child, selection, reward)
            updated.append(child)
            rewards.append(reward)
        return updated, rewards


class ReflectionOperatorController:
    """Mode-independent interface used by the evolutionary search."""

    def __init__(self, settings: ReflectionOperatorSettings) -> None:
        settings.validate()
        self.settings = settings

    @property
    def mode(self) -> ReflectionOperatorMode:
        return self.settings.mode

    def select_operator(self, rng, *, eligible: tuple[str, ...] = OPERATORS) -> str:
        raise NotImplementedError

    def probability(self, operator: str) -> float:
        raise NotImplementedError

    def initial_generation_record(self) -> dict[str, Any]:
        raise NotImplementedError

    def collect_rewards(self, parents, children, *, config, candidates_dir, classes_dir, mock):
        raise NotImplementedError

    def update_generation(self, rewards: list[OperatorReward]) -> dict[str, Any]:
        raise NotImplementedError

    def persist_reward_outcomes(
        self,
        children: list[Candidate],
        rewards: list[OperatorReward],
        *,
        record: dict[str, Any],
        candidates_dir: Path,
    ) -> list[Candidate]:
        from .artifacts import write_aos_reward_artifact, write_candidate_snapshot

        rewards_by_offspring = {reward.offspring_id: reward for reward in rewards}
        updated: list[Candidate] = []
        for child in children:
            reward = rewards_by_offspring.get(child.id)
            if reward is None:
                updated.append(child)
                continue
            stats = (record.get("operators") or {}).get(reward.operator) or {}
            metadata = {
                **reward.to_dict(),
                "mode": self.mode.value,
                "operator_quality_before": stats.get("operator_quality_before"),
                "operator_quality_after": stats.get("operator_quality_after"),
                "probability_before": stats.get("selection_probability_before"),
                "probability_after": stats.get("selection_probability"),
            }
            child = replace(child, metadata={**child.metadata, "aos": metadata})
            write_aos_reward_artifact(candidates_dir, metadata)
            write_candidate_snapshot(candidates_dir, child)
            updated.append(child)
        return updated


class StaticOperatorSelector(ReflectionOperatorController):
    """Fixed-probability selector that never computes or updates AOS credit."""

    def __init__(self, settings: ReflectionOperatorSettings, *, state: dict[str, Any] | None = None) -> None:
        super().__init__(settings)
        self.probabilities = dict(settings.initial_probabilities)
        self.total_usage = {operator: 0 for operator in OPERATORS}
        self._generation_usage = {operator: 0 for operator in OPERATORS}
        if state:
            for operator in OPERATORS:
                self.total_usage[operator] = int((state.get("total_usage") or {}).get(operator, 0))

    def select_operator(self, rng, *, eligible: tuple[str, ...] = OPERATORS) -> str:
        operator = _select_eligible_operator(rng, self.probabilities, eligible)
        self._generation_usage[operator] += 1
        self.total_usage[operator] += 1
        return operator

    def probability(self, operator: str) -> float:
        return float(self.probabilities[operator])

    def collect_rewards(self, parents, children, *, config, candidates_dir, classes_dir, mock):
        del parents, config, candidates_dir, classes_dir, mock
        return children, []

    def update_generation(self, rewards: list[OperatorReward]) -> dict[str, Any]:
        if rewards:
            raise ValueError("Static reflection operator mode must not receive adaptive rewards.")
        record = self._record(self._generation_usage)
        self._generation_usage = {operator: 0 for operator in OPERATORS}
        return record

    def initial_generation_record(self) -> dict[str, Any]:
        return self._record({operator: 0 for operator in OPERATORS})

    def _record(self, usage: dict[str, int]) -> dict[str, Any]:
        operators = {
            operator: {
                "usage_count": usage[operator],
                "reward_count": 0,
                "mean_reward": None,
                "operator_quality_before": None,
                "operator_quality_after": None,
                "recent_credit": None,
                "selection_probability_before": self.probabilities[operator],
                "selection_probability": self.probabilities[operator],
                "cumulative_usage_count": self.total_usage[operator],
                "cumulative_reward_count": 0,
                "cumulative_mean_reward": None,
                "head_to_head": _empty_head_to_head_totals(),
                "opponent_comparison": _empty_opponent_totals(),
            }
            for operator in OPERATORS
        }
        return _canonical_generation_record(
            self.settings,
            before=self.probabilities,
            after=self.probabilities,
            operators=operators,
            transitions={transition: 0 for transition in TRANSITIONS},
            state={
                "mode": self.mode.value,
                "probabilities": dict(self.probabilities),
                "total_usage": dict(self.total_usage),
            },
        )


class AdaptiveOperatorSelector(ReflectionOperatorController):
    """Adaptive controller: one reward provider feeding one shared updater."""

    def __init__(
        self,
        settings: ReflectionOperatorSettings,
        provider: RewardProvider,
        *,
        state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(settings)
        self.provider = provider
        self.updater = AdaptiveOperatorSelection(settings, state=state)

    def select_operator(self, rng, *, eligible: tuple[str, ...] = OPERATORS) -> str:
        return self.updater.select_operator(rng, eligible=eligible)

    def probability(self, operator: str) -> float:
        return self.updater.probability(operator)

    def collect_rewards(self, parents, children, *, config, candidates_dir, classes_dir, mock):
        return self.provider.collect(
            parents,
            children,
            config=config,
            candidates_dir=candidates_dir,
            classes_dir=classes_dir,
            mock=mock,
        )

    def initial_generation_record(self) -> dict[str, Any]:
        probabilities = dict(self.updater.probabilities)
        stats = self.updater._empty_generation_record()
        operators = self.updater._operator_records(
            probabilities, probabilities, dict(self.updater.credits), stats
        )
        return _canonical_generation_record(
            self.settings,
            before=probabilities,
            after=probabilities,
            operators=operators,
            transitions={transition: 0 for transition in TRANSITIONS},
            state=self._state_dict(),
        )

    def update_generation(self, rewards: list[OperatorReward]) -> dict[str, Any]:
        base = self.updater.update_generation(rewards)
        return _canonical_generation_record(
            self.settings,
            before={
                operator: base["operators"][operator]["selection_probability_before"]
                for operator in OPERATORS
            },
            after=dict(self.updater.probabilities),
            operators=base["operators"],
            transitions=base["transition_counts"],
            cumulative_transitions=base["cumulative_transition_counts"],
            state=self._state_dict(),
        )

    def _state_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, **self.updater.state_dict()}


def build_reflection_operator_controller(
    config: Any,
    *,
    state: dict[str, Any] | None = None,
) -> ReflectionOperatorController:
    """Create the only mode-specific object used by search and resume."""

    settings = config.reflection_operator_settings
    retired_operators = {
        "balance_reflection",
        "generate_code_reflection",
        "prompt_compliance_reflection",
    }
    if state and any(
        retired_operators.intersection(state.get(field) or {})
        for field in (
            "probabilities",
            "credits",
            "total_usage",
            "total_reward_count",
            "total_reward_sum",
        )
    ):
        raise ValueError(
            "This run uses retired reflection-operator semantics and cannot be "
            "resumed under Strategy/Prompt/Code Reflection. Start a new run."
        )
    if state and state.get("mode") != settings.mode.value:
        raise ValueError(
            "Persisted reflection operator mode does not match the resume config: "
            f"run={state.get('mode')!r}, config={settings.mode.value!r}."
        )
    if settings.mode is ReflectionOperatorMode.STATIC:
        return StaticOperatorSelector(settings, state=state)
    provider: RewardProvider = (
        OpponentRewardProvider()
        if settings.mode is ReflectionOperatorMode.AOS_OPPONENT
        else HeadToHeadRewardProvider()
    )
    return AdaptiveOperatorSelector(settings, provider, state=state)


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


def opponent_result_ranks(candidate: Candidate) -> dict[str, int | None]:
    """Historical W/D/L rank: LOSS=0, DRAW=1, WIN=2 for each canonical case."""

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


def calculate_opponent_reward(parent: Candidate, child: Candidate, *, operator: str) -> OperatorReward:
    """Restore the exact execution-first opponent reward from repository history."""

    parent_runnable = is_runnable(parent)
    child_runnable = is_runnable(child)
    transition = _transition(parent_runnable, child_runnable)
    if not parent_runnable and child_runnable:
        return _reward(
            parent, child, operator, OPPONENT_REPAIRED_EXECUTION_REWARD, "opponent",
            parent_runnable, child_runnable, transition, "execution_repair",
        )
    if parent_runnable and not child_runnable:
        return _reward(
            parent, child, operator, OPPONENT_BROKE_EXECUTION_REWARD, "opponent",
            parent_runnable, child_runnable, transition, "execution_regression",
        )
    if not parent_runnable and not child_runnable:
        return _reward(
            parent, child, operator, OPPONENT_STILL_FAILED_REWARD, "opponent",
            parent_runnable, child_runnable, transition, "both_failed",
        )

    parent_ranks = opponent_result_ranks(parent)
    child_ranks = opponent_result_ranks(child)
    improved = tuple(
        case for case in LEXICASE_CASES
        if parent_ranks[case] is not None and child_ranks[case] is not None
        and child_ranks[case] > parent_ranks[case]
    )
    regressed = tuple(
        case for case in LEXICASE_CASES
        if parent_ranks[case] is not None and child_ranks[case] is not None
        and child_ranks[case] < parent_ranks[case]
    )
    unchanged = tuple(
        case for case in LEXICASE_CASES
        if parent_ranks[case] is not None and child_ranks[case] is not None
        and child_ranks[case] == parent_ranks[case]
    )
    compared = len(improved) + len(regressed) + len(unchanged)
    reward_value = (len(improved) - len(regressed)) / compared if compared else 0.0
    evidence = {
        "improved_cases": list(improved),
        "regressed_cases": list(regressed),
        "unchanged_cases": list(unchanged),
        "compared_cases": compared,
        "parent_ranks": parent_ranks,
        "offspring_ranks": child_ranks,
    }
    return _reward(
        parent, child, operator, reward_value, "opponent",
        True, True, transition, "opponent_rank_change", opponent_comparison=evidence,
    )


def calculate_head_to_head_reward(
    parent: Candidate,
    child: Candidate,
    *,
    operator: str,
    head_to_head: dict[str, Any] | None = None,
) -> OperatorReward:
    """Preserve the current [0,1] direct-match reward and failure behavior."""

    parent_runnable = is_runnable(parent)
    child_runnable = is_runnable(child)
    transition = _transition(parent_runnable, child_runnable)
    evidence = {} if head_to_head is None else {key: value for key, value in head_to_head.items() if key != "reward"}
    if not child_runnable:
        return _reward(
            parent, child, operator, HEAD_TO_HEAD_EXECUTION_FAILURE_REWARD, "head2head",
            parent_runnable, False, transition, "execution_failure", head_to_head=evidence,
        )
    if head_to_head is not None and "reward" in head_to_head:
        reward_value = float(head_to_head["reward"])
        if not 0.0 <= reward_value <= 1.0:
            raise ValueError("Head-to-head reward must be in [0, 1].")
        return _reward(
            parent, child, operator, reward_value, "head2head",
            parent_runnable, True, transition, "direct_matches", head_to_head=evidence,
        )
    if not can_run_as_comparison_parent(parent):
        return _reward(
            parent, child, operator, 1.0, "head2head",
            False, True, transition, "comparison_parent_execution_failure", head_to_head=evidence,
        )
    raise ValueError("Runnable offspring and comparison parent require head-to-head evidence.")


def _collect_selected_rewards(parents, children, calculator):
    parent_by_id = {candidate.id: candidate for candidate in parents}
    updated: list[Candidate] = []
    rewards: list[OperatorReward] = []
    for child in children:
        selection = child.metadata.get("aos") or {}
        operator = selection.get("operator_id")
        parent_id = selection.get("comparison_parent_id")
        if not operator or not parent_id or parent_id not in parent_by_id:
            updated.append(child)
            continue
        reward = calculator(parent_by_id[parent_id], child, operator=operator)
        updated.append(_attach_reward(child, selection, reward))
        rewards.append(reward)
    return updated, rewards


def _attach_reward(child: Candidate, selection: dict[str, Any], reward: OperatorReward) -> Candidate:
    return replace(child, metadata={**child.metadata, "aos": {**selection, **reward.to_dict()}})


def _reward(
    parent,
    child,
    operator,
    reward_value,
    source,
    parent_runnable,
    child_runnable,
    transition,
    reason,
    *,
    head_to_head=None,
    opponent_comparison=None,
):
    return OperatorReward(
        operator=operator,
        comparison_parent_id=parent.id,
        offspring_id=child.id,
        reward=reward_value,
        reward_source=source,
        comparison_parent_runnable=parent_runnable,
        offspring_runnable=child_runnable,
        generation=child.generation,
        head_to_head={} if head_to_head is None else head_to_head,
        opponent_comparison={} if opponent_comparison is None else opponent_comparison,
        transition=transition,
        reward_reason=reason,
    )


def _transition(parent_runnable: bool, child_runnable: bool) -> str:
    return (
        f"{'runnable' if parent_runnable else 'failed'}_parent_to_"
        f"{'runnable' if child_runnable else 'failed'}_child"
    )


def _empty_head_to_head_totals() -> dict[str, int]:
    return {"wins": 0, "draws": 0, "losses": 0, "errors": 0, "total_matches": 0}


def _empty_opponent_totals() -> dict[str, int]:
    return {"improved_cases": 0, "regressed_cases": 0, "unchanged_cases": 0, "compared_cases": 0}


def _canonical_generation_record(
    settings: ReflectionOperatorSettings,
    *,
    before: dict[str, float],
    after: dict[str, float],
    operators: dict[str, Any],
    transitions: dict[str, int],
    state: dict[str, Any],
    cumulative_transitions: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "eagle-reflection-operator-v5",
        "mode": settings.mode.value,
        "reward_source": settings.mode.reward_source,
        "strategy_probability_before": before[STRATEGY_REFLECTION],
        "prompt_probability_before": before[PROMPT_REFLECTION],
        "code_probability_before": before[CODE_REFLECTION],
        "strategy_probability_after": after[STRATEGY_REFLECTION],
        "prompt_probability_after": after[PROMPT_REFLECTION],
        "code_probability_after": after[CODE_REFLECTION],
        "strategy_reward": operators[STRATEGY_REFLECTION].get("mean_reward"),
        "prompt_reward": operators[PROMPT_REFLECTION].get("mean_reward"),
        "code_reward": operators[CODE_REFLECTION].get("mean_reward"),
        "selection_probabilities": dict(before),
        "post_update_probabilities": dict(after),
        "operators": operators,
        "transition_counts": transitions,
        "cumulative_transition_counts": cumulative_transitions or {transition: 0 for transition in TRANSITIONS},
        "state": state,
    }
