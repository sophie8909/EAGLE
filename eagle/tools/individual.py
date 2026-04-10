"""
Individual class for representing a candidate solution in the genetic algorithm.
"""

from __future__ import annotations

import ast
import itertools
from dataclasses import dataclass
from typing import Any

from .component_pool import ComponentPool
from .fitness_utils import DEFAULT_FITNESS


@dataclass(frozen=True)
class ComponentEntry:
    """Stable name/value pair used when serializing an individual's components."""
    name: str
    value: Any


class Individual:
    """One candidate prompt configuration in the evolutionary search space."""

    _id_counter = itertools.count()

    def __init__(
        self,
        id: str | None = None,
        game_rule: int = 0,
        strategy: dict[str, int] | None = None,
        **legacy_components: int,
    ):
        """Create an individual with one game-rule index and a strategy-index map."""
        self.id = id or f"ind-{next(self._id_counter)}"
        if id is not None:
            self._sync_id_counter(id)
        self.game_rule = game_rule
        self.strategy = self._normalize_strategy(strategy)
        self.legacy_components = dict(legacy_components)

        # Keep backward compatibility when older logs/configs still include
        # decomposed non-strategy component names.
        for name, value in self.legacy_components.items():
            setattr(self, name, value)

        self.stable_components = [self.game_rule]
        self.evolving_components: list[int] = []

        # fitness = [win_score, instruction_accuracy_score, resource_advantage_score]
        self.fitness = DEFAULT_FITNESS.copy()
        self.evaluation_mode: str | None = None

    @property
    def components(self) -> list[ComponentEntry]:
        """Return a deterministic representation used by some legacy code paths."""
        strategy_items = tuple(sorted((self.strategy or {}).items()))
        return [
            ComponentEntry("game_rule", self.game_rule),
            ComponentEntry("strategy", strategy_items),
        ]

    def __repr__(self):
        """Return a compact representation suitable for logs and generation dumps."""
        return f"Individual(game_rule={self.game_rule}, strategy={self.strategy})"

    @staticmethod
    def _normalize_strategy(strategy: dict[str, int] | str | None) -> dict[str, int]:
        """Accept dict or stringified-dict strategies and normalize them to dicts."""
        if strategy is None:
            return {}
        if isinstance(strategy, dict):
            return strategy.copy()
        if isinstance(strategy, str):
            try:
                parsed = ast.literal_eval(strategy)
            except (ValueError, SyntaxError) as exc:
                raise ValueError(f"Invalid strategy string: {strategy!r}") from exc
            if isinstance(parsed, dict):
                return parsed.copy()
        raise TypeError(
            f"strategy must be a dict, stringified dict, or None; got {type(strategy).__name__}"
        )

    @classmethod
    def _sync_id_counter(cls, individual_id: str) -> None:
        """Keep generated IDs ahead of any checkpoint-restored explicit ID."""
        if not isinstance(individual_id, str) or not individual_id.startswith("ind-"):
            return
        suffix = individual_id.removeprefix("ind-")
        if not suffix.isdigit():
            return
        target = int(suffix) + 1
        while True:
            current = next(cls._id_counter)
            if current >= target:
                cls._id_counter = itertools.count(current + 1)
                return

    def initialize_randomly(self, component_pool: ComponentPool):
        """Fill the strategy map with random valid indices from the component pool."""
        self.game_rule = 0
        self.strategy = {
            strategy_key: component_pool.get_random_strategy_component_index(strategy_key)
            for strategy_key in component_pool.strategy_keys
        }

    def get_component_index(self, category: str) -> int:
        """Read one component index using either the new or legacy storage layout."""
        if category == "game_rule":
            return self.game_rule
        if category in self.legacy_components:
            return self.legacy_components[category]
        return getattr(self, category)

    def set_component_index(self, category: str, value: int) -> None:
        """Write one component index while preserving backward compatibility."""
        if category == "game_rule":
            self.game_rule = value
            return
        self.legacy_components[category] = value
        setattr(self, category, value)

    def copy(self) -> "Individual":
        """Create a mutable shallow clone suitable for crossover or mutation."""
        clone = Individual(
            game_rule=self.game_rule,
            strategy=dict(self.strategy or {}),
            **dict(self.legacy_components),
        )
        clone.fitness = self.fitness.copy() if hasattr(self.fitness, "copy") else self.fitness
        clone.evaluation_mode = self.evaluation_mode
        return clone
