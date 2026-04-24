"""
Individual class for representing a candidate solution in the genetic algorithm.
"""

from __future__ import annotations

import ast
import itertools
from dataclasses import dataclass
from typing import Any

from .component_pool import ComponentPool

DEFAULT_FITNESS = [0.0, 0.0]

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
        static_components: dict[str, int] | None = None,
    ):
        """Create an individual with one game-rule index and a strategy-index map."""
        self.id = id or f"ind-{next(self._id_counter)}"
        if id is not None:
            self._sync_id_counter(id)
        self.game_rule = game_rule
        self.strategy = self._normalize_strategy(strategy)
        self.static_components = dict(static_components or {})
        for name, value in self.static_components.items():
            setattr(self, name, value)

        self.stable_components = [self.game_rule]
        self.evolving_components: list[int] = []

        # EA-level fitness stores one scalar per configured opponent slot.
        # With the default config this means [LightRush_score, HeavyRush_score].
        self.fitness = DEFAULT_FITNESS.copy()
        self.evaluation_mode: str | None = None

    @property
    def components(self) -> list[ComponentEntry]:
        """Return a deterministic representation used by some legacy code paths."""
        strategy_items = tuple(sorted((self.strategy or {}).items()))
        entries = [
            ComponentEntry("game_rule", self.game_rule),
        ]
        for name, value in sorted((self.static_components or {}).items()):
            entries.append(ComponentEntry(name, value))
        entries.append(ComponentEntry("strategy", strategy_items))
        return entries

    def __repr__(self):
        """Return a compact representation suitable for logs and generation dumps."""
        return (
            f"Individual(game_rule={self.game_rule}, "
            f"static_components={self.static_components}, "
            f"strategy={self.strategy})"
        )

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

    def initialize_randomly(
        self,
        component_pool: ComponentPool,
        static_component_keys: list[str] | None = None,
    ):
        """Fill the selected static categories and strategy map with random valid indices."""
        self.game_rule = 0
        self.static_components = {}
        for category in list(static_component_keys or []):
            self.set_component_index(category, component_pool.get_random_component_index(category))
        self.strategy = {
            strategy_key: component_pool.get_random_strategy_component_index(strategy_key)
            for strategy_key in component_pool.strategy_keys
        }

    def initialize_from_seed(
        self,
        component_pool: ComponentPool,
        seed: dict[str, Any],
        *,
        static_component_keys: list[str] | None = None,
        fill_missing_random: bool = True,
    ) -> None:
        """Initialize one individual from a partial seed and fill the rest from the pool."""
        seed_payload = dict(seed or {})
        reserved_keys = {"id", "game_rule", "static_components", "strategy"}
        direct_static_indices = {
            key: value
            for key, value in seed_payload.items()
            if key not in reserved_keys and key in component_pool.static_component_keys
        }
        static_indices = dict(seed_payload.get("static_components") or {})
        static_indices.update(direct_static_indices)
        strategy_indices = dict(seed_payload.get("strategy") or {})

        self.game_rule = int(seed_payload.get("game_rule", 0))
        component_pool.get_component("game_rule", self.game_rule)

        self.static_components = {}
        selected_static_keys = set(component_pool.static_component_keys)
        selected_static_keys.update(str(key) for key in (static_component_keys or []))
        selected_static_keys.update(str(key) for key in static_indices.keys())

        for category in sorted(selected_static_keys):
            if category not in component_pool.static_component_keys:
                continue
            if category in static_indices:
                component_index = int(static_indices[category])
            elif fill_missing_random:
                component_index = component_pool.get_random_component_index(category)
            else:
                continue
            component_pool.get_component(category, component_index)
            self.set_component_index(category, component_index)

        self.strategy = {}
        for strategy_key in component_pool.strategy_keys:
            if strategy_key in strategy_indices:
                component_index = int(strategy_indices[strategy_key])
            elif fill_missing_random:
                component_index = component_pool.get_random_strategy_component_index(strategy_key)
            else:
                continue
            component_pool.get_strategy_component(strategy_key, component_index)
            self.strategy[strategy_key] = component_index

    def get_component_index(self, category: str) -> int:
        """Read one component index using either the new or legacy storage layout."""
        if category == "game_rule":
            return self.game_rule
        if category in self.static_components:
            return self.static_components[category]
        return getattr(self, category)

    def set_component_index(self, category: str, value: int) -> None:
        """Write one selected static component index."""
        if category == "game_rule":
            self.game_rule = value
            return
        self.static_components[category] = value
        setattr(self, category, value)

    def copy(self) -> "Individual":
        """Create a mutable shallow clone suitable for crossover or mutation."""
        clone = Individual(
            game_rule=self.game_rule,
            strategy=dict(self.strategy or {}),
            static_components=dict(self.static_components),
        )
        clone.fitness = self.fitness.copy() if hasattr(self.fitness, "copy") else self.fitness
        clone.evaluation_mode = self.evaluation_mode
        last_surrogate_evaluation = getattr(self, "last_surrogate_evaluation", None)
        if isinstance(last_surrogate_evaluation, dict):
            clone.last_surrogate_evaluation = dict(last_surrogate_evaluation)
        last_real_evaluation = getattr(self, "last_real_evaluation", None)
        if isinstance(last_real_evaluation, dict):
            clone.last_real_evaluation = dict(last_real_evaluation)
        return clone
