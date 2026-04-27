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
    """One candidate prompt configuration evaluated on generated game states.

    Current design:
    - All selectable prompt components are stored in component_indices.
    - non-evolving components are fixed to index 0.
    - strategy/static_components are kept only for backward compatibility.
    """

    _id_counter = itertools.count()

    def __init__(
        self,
        id: str | None = None,
        game_rule: int = 0,
        strategy: dict[str, int] | str | int | None = None,
        static_components: dict[str, int] | None = None,
        component_indices: dict[str, int] | None = None,
    ):
        self.id = id or f"round-ind-{next(self._id_counter)}"
        self.game_rule = int(game_rule)

        self.component_indices: dict[str, int] = {}
        self.static_components: dict[str, int] = {}
        self.strategy: dict[str, int] = {}

        if component_indices:
            self.component_indices.update(self._normalize_index_dict(component_indices))

        if static_components:
            self.component_indices.update(self._normalize_index_dict(static_components))

        normalized_strategy = self._normalize_strategy(strategy)
        if normalized_strategy:
            self.component_indices.update(normalized_strategy)

        if self.game_rule:
            self.component_indices["game_rule"] = self.game_rule

        self._sync_component_indices()

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
            f"component_indices={self.component_indices})"
        )

    @staticmethod
    def _normalize_index_dict(value: Any) -> dict[str, int]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, int] = {}
        for key, item in value.items():
            try:
                normalized[str(key)] = int(item)
            except (TypeError, ValueError):
                continue
        return normalized

    @classmethod
    def _normalize_strategy(cls, strategy: dict[str, int] | str | int | None) -> dict[str, int]:
        if strategy is None:
            return {}

        if isinstance(strategy, dict):
            return cls._normalize_index_dict(strategy)

        if isinstance(strategy, int):
            # Backward compatibility: old code may accidentally pass strategy as an index.
            # It cannot be mapped safely to a key here, so ignore it.
            return {}

        if isinstance(strategy, str):
            try:
                parsed = ast.literal_eval(strategy)
            except (SyntaxError, ValueError):
                return {}

            if isinstance(parsed, dict):
                return cls._normalize_index_dict(parsed)

            return {}

        return {}

    @classmethod
    def from_existing(cls, individual: Any) -> "Individual":
        clone = cls(
            id=getattr(individual, "id", None),
            game_rule=getattr(individual, "game_rule", 0),
            component_indices=dict(getattr(individual, "component_indices", {}) or {}),
            static_components=dict(getattr(individual, "static_components", {}) or {}),
            strategy=getattr(individual, "strategy", None),
        )

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

        selected_keys = list(component_keys or component_pool.evolving_component_keys)

        for category in component_pool.component_keys:
            if category in component_pool.non_evolving_component_keys:
                self.set_component_index(category, 0)

        for category in selected_keys:
            if category in component_pool.non_evolving_component_keys:
                self.set_component_index(category, 0)
                continue
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
        seed_payload = dict(seed or {})

        flat_seed_indices: dict[str, int] = {}
        flat_seed_indices.update(
            self._normalize_index_dict(seed_payload.get("components"))
        )
        flat_seed_indices.update(
            self._normalize_index_dict(seed_payload.get("component_indices"))
        )
        flat_seed_indices.update(
            self._normalize_index_dict(seed_payload.get("static_components"))
        )
        flat_seed_indices.update(
            self._normalize_strategy(seed_payload.get("strategy"))
        )

        self.game_rule = int(
            flat_seed_indices.get("game_rule", seed_payload.get("game_rule", 0))
        )
        self.component_indices = {}

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
            return int(self.component_indices[category])

        attr_value = getattr(self, category, None)
        if attr_value is None:
            raise KeyError(f"Component index not found for category: {category}")

        return int(attr_value)

    def set_component_index(self, category: str, value: int) -> None:
        index = int(value)

        if category == "game_rule":
            self.game_rule = index

        self.component_indices[str(category)] = index
        setattr(self, str(category), index)

    def copy(self) -> "Individual":
        clone = Individual(
            game_rule=self.game_rule,
            component_indices=dict(self.component_indices or {}),
        )

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
        existing_indices: dict[str, int] = {}

        existing_indices.update(
            self._normalize_index_dict(getattr(self, "component_indices", {}) or {})
        )
        existing_indices.update(
            self._normalize_index_dict(getattr(self, "static_components", {}) or {})
        )

        strategy = getattr(self, "strategy", None)
        if isinstance(strategy, dict):
            existing_indices.update(self._normalize_index_dict(strategy))

        if self.game_rule:
            existing_indices["game_rule"] = int(self.game_rule)

        self.component_indices = existing_indices
        self.static_components = dict(existing_indices)
        self.strategy = {}

        for key, value in self.component_indices.items():
            setattr(self, key, int(value))