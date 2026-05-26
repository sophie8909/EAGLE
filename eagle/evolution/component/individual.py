"""
Individual class for representing a candidate solution in the genetic algorithm.
"""

from __future__ import annotations

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
        component_indices: dict[str, int] | None = None,
    ):
        self.id = id or f"ind-{next(self._id_counter)}"
        if id is not None:
            self._sync_id_counter(id)

        self.game_rule = int(game_rule)

        self.component_indices: dict[str, dict[str, int]] = {}

        if isinstance(component_indices, dict):
            self.component_indices.update(self._normalize_component_indices(component_indices))

        self._sync_component_indices()

        self.stable_components = [self.game_rule]
        self.evolving_components: list[int] = []

        self.fitness = DEFAULT_FITNESS.copy()
        self.evaluation_mode: str | None = None

        self.last_round_evaluation: dict[str, Any] = {}
        self.last_surrogate_evaluation: dict[str, Any] = {}
        self.last_gameplay_evaluation: dict[str, Any] = {}
        self.mutation_metadata: dict[str, Any] = {}
        self.reflection_metadata: dict[str, Any] = {}
        self.training_examples: list[dict[str, Any]] = []
        self.ea_llm_call_time = 0.0

    @property
    def components(self) -> list[ComponentEntry]:
        """Return a deterministic representation of selected components."""
        entries = [ComponentEntry("game_rule", self.game_rule)]
        for name, value in sorted((self.component_indices or {}).items()):
            entries.append(ComponentEntry(name, value))
        return entries

    def __repr__(self) -> str:
        """Return a compact representation suitable for logs."""
        return (
            f"Individual(id={self.id}, component_indices={self.component_indices})"
        )

    @classmethod
    def _normalize_component_indices(cls, payload: dict[str, Any] | None) -> dict[str, dict[str, int]]:
        """Normalize checkpoint/config component selections into the current entry shape."""
        normalized: dict[str, dict[str, int]] = {}
        if not isinstance(payload, dict):
            return normalized
        for key, value in payload.items():
            normalized[str(key)] = cls._normalize_component_entry(value)
        return normalized

    @staticmethod
    def _normalize_component_entry(value: Any, *, default_enabled: int = 1) -> dict[str, int]:
        """Return the canonical `{index, enabled}` selector used by operators."""
        if isinstance(value, dict):
            raw_index = value.get("index", 0)
            raw_enabled = value.get("enabled", value.get("bit", default_enabled))
        else:
            raw_index = value
            raw_enabled = default_enabled
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = 0
        try:
            enabled = 1 if int(raw_enabled) else 0
        except (TypeError, ValueError):
            enabled = 1
        return {"index": index, "enabled": enabled}

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

        keys = list(component_keys or component_pool.evolving_component_keys)

        for category in component_pool.component_keys:
            if category in component_pool.non_evolving_component_keys:
                self.set_component_index(category, 0)
            elif category in keys:
                self.set_component_index(
                    category,
                    component_pool.get_random_component_index(category),
                )
            else:
                # Even non-evolving search targets still carry an enabled bit.
                self.set_component_index(category, 0)

        self.training_examples = component_pool.sample_training_examples()
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
        component_indices = dict(seed_payload.get("component_indices") or {})

        self.game_rule = int(seed_payload.get("game_rule", 0))
        self.component_indices = {}

        selected_keys = set(component_pool.component_keys)
        selected_keys.update(str(key) for key in (component_keys or []))
        selected_keys.update(str(key) for key in component_indices.keys())

        for category in sorted(selected_keys):
            if category not in component_pool.component_keys:
                continue

            if category in component_pool.non_evolving_component_keys:
                component_index = 0
            elif category in component_indices:
                component_index = self._normalize_component_entry(component_indices[category])["index"]
            elif fill_missing_random:
                component_index = component_pool.get_random_component_index(category)
            else:
                continue

            component_pool.get_component(category, component_index)
            self.set_component_index(category, component_index)

        if isinstance(seed_payload.get("training_examples"), list):
            self.training_examples = component_pool._normalize_training_examples(
                seed_payload["training_examples"]
            )
        else:
            self.training_examples = component_pool.sample_training_examples()
        self._sync_component_indices()

    def get_component_index(self, category: str) -> int:
        """Read one component index."""
        if category == "game_rule":
            return int(self.game_rule)
        return int(self._normalize_component_entry(self.component_indices.get(category, 0))["index"])

    def is_component_enabled(self, category: str) -> int:
        """Return whether one component is included in the rendered prompt."""
        return int(self._normalize_component_entry(self.component_indices.get(category, 0))["enabled"])

    def set_component_index(self, category: str, value: int) -> None:
        """Write one selected component index."""
        category = str(category)
        value = int(value)

        if category == "game_rule":
            self.game_rule = value

        enabled = self.is_component_enabled(category) if category in self.component_indices else 1
        self.component_indices[category] = {"index": value, "enabled": enabled}
        setattr(self, category, value)

    def set_component_enabled(self, category: str, enabled: int) -> None:
        """Set the prompt-inclusion bit for one component."""
        category = str(category)
        entry = self._normalize_component_entry(self.component_indices.get(category, 0))
        entry["enabled"] = 1 if int(enabled) else 0
        self.component_indices[category] = entry

    def flip_component_enabled(self, category: str) -> tuple[int, int]:
        """Flip one component inclusion bit and return old/new bits."""
        old_bit = self.is_component_enabled(category)
        new_bit = 0 if old_bit else 1
        self.set_component_enabled(category, new_bit)
        return old_bit, new_bit

    def copy(self) -> "Individual":
        """Create a mutable clone suitable for crossover, mutation, or reflection."""
        clone = Individual(
            id=None,
            game_rule=self.game_rule,
            component_indices={key: dict(value) for key, value in self.component_indices.items()},
        )

        for key, value in clone.component_indices.items():
            setattr(clone, key, int(clone.get_component_index(key)))

        clone.fitness = self.fitness.copy() if hasattr(self.fitness, "copy") else self.fitness
        clone.evaluation_mode = self.evaluation_mode

        for attr in (
            "last_round_evaluation",
            "last_surrogate_evaluation",
            "last_gameplay_evaluation",
            "mutation_metadata",
            "reflection_metadata",
        ):
            value = getattr(self, attr, None)
            if isinstance(value, dict):
                setattr(clone, attr, dict(value))
            elif value is not None:
                setattr(clone, attr, value)

        clone.ea_llm_call_time = getattr(self, "ea_llm_call_time", 0.0)
        clone.training_examples = [
            dict(example) for example in getattr(self, "training_examples", []) or []
        ]

        for attr in ("pareto_rank", "crowding_distance"):
            if hasattr(self, attr):
                setattr(clone, attr, getattr(self, attr))

        return clone

    @classmethod
    def from_existing(cls, individual: "Individual") -> "Individual":
        """Create a copy from an existing individual."""
        return individual.copy()

    def _sync_component_indices(self) -> None:
        """Synchronize denormalized fields without overwriting the genotype."""
        merged: dict[str, dict[str, int]] = {}

        existing = getattr(self, "component_indices", {}) or {}
        if isinstance(existing, dict):
            for key, value in existing.items():
                try:
                    merged[str(key)] = self._normalize_component_entry(value)
                except (TypeError, ValueError):
                    continue

        if getattr(self, "game_rule", 0):
            merged.setdefault("game_rule", {"index": int(self.game_rule), "enabled": 1})

        self.component_indices = dict(merged)

        for key, value in self.component_indices.items():
            setattr(self, key, int(value["index"]))
