"""
Individual class for representing a candidate solution in the genetic algorithm.
"""

from __future__ import annotations

import ast
import itertools
from dataclasses import dataclass
from typing import Any

from eagle.utils.component_pool import ComponentPool


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
        strategy: dict[str, int] | str | None = None,
        static_components: dict[str, int] | None = None,
        component_indices: dict[str, int] | None = None,
    ):
        self.id = id or f"ind-{next(self._id_counter)}"
        if id is not None:
            self._sync_id_counter(id)

        self.game_rule = int(game_rule)

        self.component_indices: dict[str, int] = {}
        self.static_components: dict[str, int] = {}
        self.strategy: dict[str, int] = {}

        if isinstance(component_indices, dict):
            self.component_indices.update(
                {str(key): int(value) for key, value in component_indices.items()}
            )

        if isinstance(static_components, dict):
            self.component_indices.update(
                {str(key): int(value) for key, value in static_components.items()}
            )

        normalized_strategy = self._normalize_strategy(strategy)
        self.component_indices.update(normalized_strategy)

        self._sync_component_indices()

        self.stable_components = [self.game_rule]
        self.evolving_components: list[int] = []

        self.fitness = DEFAULT_FITNESS.copy()
        self.evaluation_mode: str | None = None

        self.last_round_evaluation: dict[str, Any] = {}
        self.last_surrogate_evaluation: dict[str, Any] = {}
        self.last_real_evaluation: dict[str, Any] = {}
        self.mutation_metadata: dict[str, Any] = {}
        self.reflection_metadata: dict[str, Any] = {}
        self.ea_llm_call_time = 0.0

    @property
    def components(self) -> list[ComponentEntry]:
        """Return a deterministic representation used by legacy code paths."""
        entries = [ComponentEntry("game_rule", self.game_rule)]
        for name, value in sorted((self.component_indices or {}).items()):
            entries.append(ComponentEntry(name, value))
        return entries

    def __repr__(self) -> str:
        """Return a compact representation suitable for logs."""
        return f"Individual(id={self.id}, component_indices={self.component_indices})"

    @staticmethod
    def _normalize_strategy(strategy: dict[str, int] | str | None) -> dict[str, int]:
        """Normalize legacy strategy payloads into component-index dictionaries."""
        if strategy is None:
            return {}

        if isinstance(strategy, dict):
            normalized: dict[str, int] = {}
            for key, value in strategy.items():
                try:
                    normalized[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
            return normalized

        if isinstance(strategy, str):
            try:
                parsed = ast.literal_eval(strategy)
            except (ValueError, SyntaxError):
                return {}
            if isinstance(parsed, dict):
                normalized = {}
                for key, value in parsed.items():
                    try:
                        normalized[str(key)] = int(value)
                    except (TypeError, ValueError):
                        continue
                return normalized

        return {}

    @classmethod
    def _sync_id_counter(cls, individual_id: str) -> None:
        """Keep generated IDs ahead of checkpoint-restored explicit IDs."""
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
        component_keys: list[str] | None = None,
    ) -> None:
        """Fill selected flattened component categories with random valid indices."""
        self.game_rule = 0
        self.component_indices = {}
        self.static_components = {}
        self.strategy = {}

        keys = list(component_keys or component_pool.evolving_component_keys)

        for category in component_pool.component_keys:
            if category in component_pool.non_evolving_component_keys:
                self.set_component_index(category, 0)

        for category in keys:
            if category not in component_pool.component_keys:
                continue
            if category in component_pool.non_evolving_component_keys:
                self.set_component_index(category, 0)
            else:
                self.set_component_index(
                    category,
                    component_pool.get_random_component_index(category),
                )

        self._sync_component_indices()

    def initialize_from_seed(
        self,
        component_pool: ComponentPool,
        seed: dict[str, Any],
        *,
        component_keys: list[str] | None = None,
        fill_missing_random: bool = True,
    ) -> None:
        """Initialize one individual from a partial seed."""
        seed_payload = dict(seed or {})
        reserved_keys = {
            "id",
            "game_rule",
            "static_components",
            "strategy",
            "components",
            "component_indices",
        }

        direct_indices = {
            key: value
            for key, value in seed_payload.items()
            if key not in reserved_keys and key in component_pool.component_keys
        }

        component_indices = dict(
            seed_payload.get("components")
            or seed_payload.get("component_indices")
            or {}
        )
        component_indices.update(dict(seed_payload.get("static_components") or {}))
        component_indices.update(self._normalize_strategy(seed_payload.get("strategy")))
        component_indices.update(direct_indices)

        self.game_rule = int(seed_payload.get("game_rule", 0))
        self.component_indices = {}
        self.static_components = {}
        self.strategy = {}

        selected_keys = set(component_pool.component_keys)
        selected_keys.update(str(key) for key in (component_keys or []))
        selected_keys.update(str(key) for key in component_indices.keys())

        for category in sorted(selected_keys):
            if category not in component_pool.component_keys:
                continue

            if category in component_pool.non_evolving_component_keys:
                component_index = 0
            elif category in component_indices:
                component_index = int(component_indices[category])
            elif fill_missing_random:
                component_index = component_pool.get_random_component_index(category)
            else:
                continue

            component_pool.get_component(category, component_index)
            self.set_component_index(category, component_index)

        self._sync_component_indices()

    def get_component_index(self, category: str) -> int:
        """Read one component index."""
        if category == "game_rule":
            return int(self.game_rule)
        return int(self.component_indices.get(category, 0))

    def set_component_index(self, category: str, value: int) -> None:
        """Write one selected component index."""
        category = str(category)
        value = int(value)

        if category == "game_rule":
            self.game_rule = value

        self.component_indices[category] = value
        self.static_components[category] = value
        setattr(self, category, value)

    def copy(self) -> "Individual":
        """Create a mutable clone suitable for crossover, mutation, or reflection."""
        clone = Individual(
            id=None,
            game_rule=self.game_rule,
            component_indices=dict(self.component_indices),
        )

        clone.static_components = dict(self.static_components)
        clone.strategy = {}

        for key, value in clone.component_indices.items():
            setattr(clone, key, int(value))

        clone.fitness = self.fitness.copy() if hasattr(self.fitness, "copy") else self.fitness
        clone.evaluation_mode = self.evaluation_mode

        for attr in (
            "last_round_evaluation",
            "last_surrogate_evaluation",
            "last_real_evaluation",
            "mutation_metadata",
            "reflection_metadata",
        ):
            value = getattr(self, attr, None)
            if isinstance(value, dict):
                setattr(clone, attr, dict(value))
            elif value is not None:
                setattr(clone, attr, value)

        clone.ea_llm_call_time = getattr(self, "ea_llm_call_time", 0.0)

        for attr in ("pareto_rank", "crowding_distance"):
            if hasattr(self, attr):
                setattr(clone, attr, getattr(self, attr))

        return clone

    @classmethod
    def from_existing(cls, individual: "Individual") -> "Individual":
        """Create a copy from an existing individual for legacy EA code."""
        return individual.copy()

    def _sync_component_indices(self) -> None:
        """Synchronize compatibility fields without overwriting the genotype."""
        merged: dict[str, int] = {}

        existing = getattr(self, "component_indices", {}) or {}
        if isinstance(existing, dict):
            for key, value in existing.items():
                try:
                    merged[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue

        if getattr(self, "game_rule", 0):
            merged.setdefault("game_rule", int(self.game_rule))

        static_components = getattr(self, "static_components", {}) or {}
        if isinstance(static_components, dict):
            for key, value in static_components.items():
                try:
                    merged.setdefault(str(key), int(value))
                except (TypeError, ValueError):
                    continue

        strategy = getattr(self, "strategy", {}) or {}
        if isinstance(strategy, dict):
            for key, value in strategy.items():
                try:
                    merged.setdefault(str(key), int(value))
                except (TypeError, ValueError):
                    continue

        self.component_indices = dict(merged)
        self.static_components = dict(self.component_indices)
        self.strategy = {}

        for key, value in self.component_indices.items():
            setattr(self, key, int(value))