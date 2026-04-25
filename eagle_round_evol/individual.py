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
        clone.fitness = list(getattr(individual, "fitness", DEFAULT_FITNESS) or DEFAULT_FITNESS)
        clone.evaluation_mode = getattr(individual, "evaluation_mode", None)
        last_round_evaluation = getattr(individual, "last_round_evaluation", None)
        if isinstance(last_round_evaluation, dict):
            clone.last_round_evaluation = dict(last_round_evaluation)
        return clone

    def initialize_randomly(
        self,
        component_pool: ComponentPool,
        static_component_keys: list[str] | None = None,
    ) -> None:
        self.game_rule = 0
        self.static_components = {}
        for category in component_pool.static_component_keys:
            if category in component_pool.FIXED_COMPONENT_KEYS:
                self.set_component_index(category, 0)
        for category in list(static_component_keys or []):
            self.set_component_index(category, component_pool.get_random_component_index(category))
        self.strategy = {
            strategy_key: component_pool.get_random_strategy_component_index(strategy_key)
            for strategy_key in component_pool.strategy_keys
        }
        self._sync_component_indices()

    def initialize_from_seed(
        self,
        component_pool: ComponentPool,
        seed: dict[str, Any],
        *,
        static_component_keys: list[str] | None = None,
        fill_missing_random: bool = True,
    ) -> None:
        seed_payload = dict(seed or {})
        flat_seed_indices = dict(seed_payload.get("components") or seed_payload.get("component_indices") or {})
        if "game_rule" in component_pool.component_keys:
            self.game_rule = int(flat_seed_indices.get("game_rule", seed_payload.get("game_rule", 0)))
            component_pool.get_component("game_rule", self.game_rule)
        else:
            self.game_rule = 0

        static_indices = dict(seed_payload.get("static_components") or {})
        static_indices.update(
            {
                key: value
                for key, value in flat_seed_indices.items()
                if key in component_pool.static_component_keys
            }
        )
        self.static_components = {}
        for category in sorted(set(component_pool.static_component_keys) | set(static_component_keys or [])):
            if category not in component_pool.static_component_keys:
                continue
            if category in component_pool.FIXED_COMPONENT_KEYS:
                component_index = 0
                component_pool.get_component(category, component_index)
                self.set_component_index(category, component_index)
                continue
            if category in static_indices:
                component_index = int(static_indices[category])
            elif fill_missing_random:
                component_index = component_pool.get_random_component_index(category)
            else:
                continue
            component_pool.get_component(category, component_index)
            self.set_component_index(category, component_index)

        strategy_indices = dict(seed_payload.get("strategy") or {})
        strategy_indices.update(
            {
                key: value
                for key, value in flat_seed_indices.items()
                if key in component_pool.strategy_keys
            }
        )
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
        self._sync_component_indices()

    def get_component_index(self, category: str) -> int:
        if category == "game_rule":
            return self.game_rule
        if category in self.component_indices:
            return self.component_indices[category]
        if category in self.static_components:
            return self.static_components[category]
        return getattr(self, category)

    def set_component_index(self, category: str, value: int) -> None:
        if category == "game_rule":
            self.game_rule = int(value)
            self.component_indices[category] = int(value)
            return
        self.component_indices[category] = int(value)
        self.static_components[category] = int(value)
        setattr(self, category, int(value))

    def copy(self) -> "Individual":
        clone = Individual(
            game_rule=self.game_rule,
            strategy=dict(self.strategy or {}),
            static_components=dict(self.static_components or {}),
        )
        clone.component_indices = dict(self.component_indices or {})
        clone.fitness = list(self.fitness or DEFAULT_FITNESS)
        clone.evaluation_mode = self.evaluation_mode
        if isinstance(self.last_round_evaluation, dict):
            clone.last_round_evaluation = dict(self.last_round_evaluation)
        return clone

    def _sync_component_indices(self) -> None:
        self.component_indices = {}
        if self.game_rule:
            self.component_indices["game_rule"] = int(self.game_rule)
        self.component_indices.update({str(key): int(value) for key, value in self.static_components.items()})
        self.component_indices.update({str(key): int(value) for key, value in self.strategy.items()})
