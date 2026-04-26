"""Round-evaluation individual model."""

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
    """One candidate prompt configuration evaluated on generated game states."""

    _id_counter = itertools.count()

    def __init__(
        self,
        id: str | None = None,
        game_rule: int = 0,
        strategy: dict[str, int] | str | None = None,
        static_components: dict[str, int] | None = None,
    ):
        self.id = id or f"round-ind-{next(self._id_counter)}"
        self.game_rule = int(game_rule)
        self.strategy = self._normalize_strategy(strategy)
        self.static_components = dict(static_components or {})
        self.component_indices: dict[str, int] = {}
        self._sync_component_indices()
        for name, value in self.static_components.items():
            setattr(self, name, value)

        self.fitness = DEFAULT_FITNESS.copy()
        self.evaluation_mode: str | None = None
        self.last_round_evaluation: dict[str, Any] | None = None

    @property
    def components(self) -> list[ComponentEntry]:
        return [
            ComponentEntry(name, value)
            for name, value in sorted((self.component_indices or {}).items())
        ]

    def __repr__(self) -> str:
        return (
            f"Individual(game_rule={self.game_rule}, "
            f"static_components={self.static_components}, "
            f"strategy={self.strategy})"
        )

    @staticmethod
    def _normalize_strategy(strategy: dict[str, int] | str | None) -> dict[str, int]:
        if strategy is None:
            return {}
        if isinstance(strategy, dict):
            return {str(key): int(value) for key, value in strategy.items()}
        if isinstance(strategy, str):
            parsed = ast.literal_eval(strategy)
            if isinstance(parsed, dict):
                return {str(key): int(value) for key, value in parsed.items()}
        raise TypeError(f"strategy must be dict, stringified dict, or None; got {type(strategy).__name__}")

    @classmethod
    def from_existing(cls, individual: Any) -> "Individual":
        clone = cls(
            id=getattr(individual, "id", None),
            game_rule=getattr(individual, "game_rule", 0),
            strategy=dict(getattr(individual, "strategy", {}) or {}),
            static_components=dict(getattr(individual, "static_components", {}) or {}),
        )
        component_indices = getattr(individual, "component_indices", None)
        if isinstance(component_indices, dict):
            clone.component_indices = {str(key): int(value) for key, value in component_indices.items()}
            clone.static_components = dict(clone.component_indices)
            clone.strategy = {}
        clone.fitness = list(getattr(individual, "fitness", DEFAULT_FITNESS) or DEFAULT_FITNESS)
        clone.evaluation_mode = getattr(individual, "evaluation_mode", None)
        last_round_evaluation = getattr(individual, "last_round_evaluation", None)
        if isinstance(last_round_evaluation, dict):
            clone.last_round_evaluation = dict(last_round_evaluation)
        for attr in ("mutation_metadata", "reflection_metadata", "ea_llm_call_time"):
            if hasattr(individual, attr):
                value = getattr(individual, attr)
                setattr(clone, attr, dict(value) if isinstance(value, dict) else value)
        return clone

    def initialize_randomly(
        self,
        component_pool: ComponentPool,
        component_keys: list[str] | None = None,
    ) -> None:
        self.game_rule = 0
        self.component_indices = {}
        self.static_components = {}
        self.strategy = {}
        for category in component_pool.component_keys:
            if category in component_pool.non_evolving_component_keys:
                self.set_component_index(category, 0)
        for category in list(component_keys or component_pool.evolving_component_keys):
            self.set_component_index(category, component_pool.get_random_component_index(category))
        self._sync_component_indices()

    def initialize_from_seed(
        self,
        component_pool: ComponentPool,
        seed: dict[str, Any],
        *,
        component_keys: list[str] | None = None,
        fill_missing_random: bool = True,
    ) -> None:
        seed_payload = dict(seed or {})
        flat_seed_indices = dict(seed_payload.get("components") or seed_payload.get("component_indices") or {})
        flat_seed_indices.update(dict(seed_payload.get("static_components") or {}))
        flat_seed_indices.update(dict(seed_payload.get("strategy") or {}))

        self.game_rule = int(flat_seed_indices.get("game_rule", seed_payload.get("game_rule", 0)))
        self.component_indices = {}
        self.static_components = {}
        self.strategy = {}
        selected_keys = set(component_pool.component_keys)
        selected_keys.update(str(key) for key in (component_keys or []))

        for category in sorted(selected_keys):
            if category not in component_pool.component_keys:
                continue
            if category in component_pool.non_evolving_component_keys:
                component_index = 0
            elif category in flat_seed_indices:
                component_index = int(flat_seed_indices[category])
            elif fill_missing_random:
                component_index = component_pool.get_random_component_index(category)
            else:
                continue
            component_pool.get_component(category, component_index)
            self.set_component_index(category, component_index)
        self._sync_component_indices()

    def get_component_index(self, category: str) -> int:
        if category == "game_rule":
            return self.game_rule
        if category in self.component_indices:
            return self.component_indices[category]
        return getattr(self, category)

    def set_component_index(self, category: str, value: int) -> None:
        if category == "game_rule":
            self.game_rule = int(value)
            self.component_indices[category] = int(value)
            return
        self.component_indices[category] = int(value)
        setattr(self, category, int(value))

    def copy(self) -> "Individual":
        clone = Individual(
            game_rule=self.game_rule,
            strategy={},
            static_components=dict(self.component_indices or {}),
        )
        clone.component_indices = dict(self.component_indices or {})
        clone.fitness = list(self.fitness or DEFAULT_FITNESS)
        clone.evaluation_mode = self.evaluation_mode
        if isinstance(self.last_round_evaluation, dict):
            clone.last_round_evaluation = dict(self.last_round_evaluation)
        for attr in ("mutation_metadata", "reflection_metadata", "ea_llm_call_time"):
            if hasattr(self, attr):
                value = getattr(self, attr)
                setattr(clone, attr, dict(value) if isinstance(value, dict) else value)
        return clone

    def _sync_component_indices(self) -> None:
        existing_indices = dict(getattr(self, "component_indices", {}) or {})
        if self.game_rule:
            existing_indices["game_rule"] = int(self.game_rule)
        existing_indices.update({str(key): int(value) for key, value in self.static_components.items()})
        existing_indices.update({str(key): int(value) for key, value in self.strategy.items()})
        self.component_indices = existing_indices
        self.static_components = dict(existing_indices)
        self.strategy = {}
