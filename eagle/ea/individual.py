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
    name: str
    value: Any


class Individual:
    _id_counter = itertools.count()

    def __init__(
        self,
        game_rule: int = 0,
        strategy: dict[str, int] | None = None,
        **legacy_components: int,
    ):
        self.id = f"ind-{next(self._id_counter)}"
        self.game_rule = game_rule
        self.strategy = self._normalize_strategy(strategy)
        self.legacy_components = dict(legacy_components)

        # Keep backward compatibility when older logs/configs still include
        # decomposed non-strategy component names.
        for name, value in self.legacy_components.items():
            setattr(self, name, value)

        self.stable_components = [self.game_rule]
        self.evolving_components: list[int] = []

        # fitness = [win_score, resource_advantage_score, game_round_score]
        self.fitness = DEFAULT_FITNESS.copy()

    @property
    def components(self) -> list[ComponentEntry]:
        strategy_items = tuple(sorted((self.strategy or {}).items()))
        return [
            ComponentEntry("game_rule", self.game_rule),
            ComponentEntry("strategy", strategy_items),
        ]

    def __repr__(self):
        return f"Individual(game_rule={self.game_rule}, strategy={self.strategy})"

    @staticmethod
    def _normalize_strategy(strategy: dict[str, int] | str | None) -> dict[str, int]:
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

    def initialize_randomly(self, component_pool: ComponentPool):
        self.game_rule = 0
        self.strategy = {
            strategy_key: component_pool.get_random_strategy_component_index(strategy_key)
            for strategy_key in component_pool.strategy_keys
        }

    def get_component_index(self, category: str) -> int:
        if category == "game_rule":
            return self.game_rule
        if category in self.legacy_components:
            return self.legacy_components[category]
        return getattr(self, category)

    def set_component_index(self, category: str, value: int) -> None:
        if category == "game_rule":
            self.game_rule = value
            return
        self.legacy_components[category] = value
        setattr(self, category, value)

    def copy(self) -> "Individual":
        clone = Individual(
            game_rule=self.game_rule,
            strategy=dict(self.strategy or {}),
            **dict(self.legacy_components),
        )
        clone.fitness = self.fitness.copy() if hasattr(self.fitness, "copy") else self.fitness
        return clone
