"""Component pool for managing flattened prompt components."""

from __future__ import annotations

import json
import random
from collections import OrderedDict
from typing import Any, Dict, List


class ComponentPool:
    """Prompt component pool with flattened component keys.

    Component JSON files may still contain a nested ``strategy`` object. The
    pool flattens those buckets into normal top-level component keys while
    preserving a ``components["strategy"]`` compatibility view for existing
    crossover and mutation operators.
    """

    FIXED_COMPONENT_KEYS = {"json_schema"}
    NON_EVOLVING_STATIC_KEYS = FIXED_COMPONENT_KEYS

    def __init__(self, components: Dict[str, Any]):
        raw_components = dict(components or {})
        metadata = dict(raw_components.pop("metadata", {}) or {})
        self.metadata = metadata
        explicit_strategy_keys = [str(key) for key in metadata.get("strategy_keys", []) or []]
        explicit_fixed_keys = [str(key) for key in metadata.get("fixed_component_keys", []) or []]

        self.fixed_component_keys = set(explicit_fixed_keys or self.FIXED_COMPONENT_KEYS)
        self.FIXED_COMPONENT_KEYS = self.fixed_component_keys
        self.NON_EVOLVING_STATIC_KEYS = self.fixed_component_keys
        self.flat_components: OrderedDict[str, list[list[str]]] = OrderedDict()
        self.strategy_keys: list[str] = []
        self._source_strategy_keys: set[str] = set()

        for key, value in raw_components.items():
            if key == "strategy" and isinstance(value, dict):
                for strategy_key, candidates in value.items():
                    strategy_key = str(strategy_key)
                    self._source_strategy_keys.add(strategy_key)
                    if strategy_key not in self.strategy_keys:
                        self.strategy_keys.append(strategy_key)
                    self.flat_components[strategy_key] = self._normalize_candidates(candidates)
                continue
            key = str(key)
            self.flat_components[key] = self._normalize_candidates(value)

        for strategy_key in explicit_strategy_keys:
            if strategy_key in self.flat_components and strategy_key not in self.strategy_keys:
                self.strategy_keys.append(strategy_key)
        if explicit_strategy_keys:
            ordered_strategy_keys = [
                key for key in explicit_strategy_keys
                if key in self.flat_components
            ]
            ordered_strategy_keys.extend(
                key for key in self.strategy_keys
                if key not in ordered_strategy_keys
            )
            self.strategy_keys = ordered_strategy_keys

        self.identity_strategy_key = self._resolve_identity_strategy_key(metadata)
        self.dependent_strategy_keys = [
            key for key in self.strategy_keys
            if key != self.identity_strategy_key
        ]

        strategy_view = OrderedDict(
            (key, self.flat_components[key])
            for key in self.strategy_keys
            if key in self.flat_components
        )
        self.components: OrderedDict[str, Any] = OrderedDict(self.flat_components)
        self.components["strategy"] = strategy_view

        self.component_keys = list(self.flat_components.keys())
        self.game_rule_source_keys = list(self.component_keys)
        self.game_rule_components = [self._flatten_all_prompt_lines()]
        self.static_component_keys = [
            key for key in self.component_keys
            if key not in self.strategy_keys
        ]
        self.mutable_static_component_keys = [
            key for key in self.static_component_keys
            if key not in self.fixed_component_keys
        ]
        self.evolving_component_keys = [
            key for key in self.component_keys
            if key not in self.fixed_component_keys
        ]
        self.reflection_format_keys = self._filter_component_keys(
            metadata.get("reflection_format_keys"),
            fallback=self.mutable_static_component_keys,
        )
        self.reflection_strategy_keys = self._filter_component_keys(
            metadata.get("reflection_strategy_keys"),
            fallback=self.dependent_strategy_keys or self.strategy_keys,
        )

    @classmethod
    def from_json(cls, filepath: str) -> "ComponentPool":
        """Load a component pool definition from disk."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    @staticmethod
    def _normalize_candidates(value: Any) -> list[list[str]]:
        if not isinstance(value, list):
            return [[str(value)]]
        if not value:
            return []
        if all(isinstance(item, str) for item in value):
            return [[str(item) for item in value]]
        candidates: list[list[str]] = []
        for candidate in value:
            if isinstance(candidate, list):
                candidates.append([str(line) for line in candidate])
            else:
                candidates.append([str(candidate)])
        return candidates

    @staticmethod
    def _normalize_component_lines(component_lines: List[str]) -> List[str]:
        """Drop empty placeholder lines while preserving original text order."""
        return [str(line) for line in component_lines if str(line).strip()]

    def _resolve_identity_strategy_key(self, metadata: dict[str, Any]) -> str | None:
        explicit_identity = metadata.get("identity_strategy_key")
        if explicit_identity is not None and str(explicit_identity) in self.strategy_keys:
            return str(explicit_identity)
        return self.strategy_keys[0] if self.strategy_keys else None

    def _filter_component_keys(self, keys: Any, *, fallback: list[str]) -> list[str]:
        if not keys:
            return list(fallback)
        return [
            str(key) for key in keys
            if str(key) in self.component_keys and str(key) not in self.fixed_component_keys
        ] or list(fallback)

    def _flatten_all_prompt_lines(self) -> list[str]:
        lines: list[str] = []
        for key in self.component_keys:
            candidates = self.flat_components.get(key, [])
            if not candidates:
                continue
            if lines:
                lines.append("")
            lines.extend(self._normalize_component_lines(candidates[0]))
        return lines

    def to_flat_dict(self) -> dict[str, list[list[str]]]:
        """Return the canonical flattened component payload."""
        return {key: value for key, value in self.flat_components.items()}

    def to_compatible_dict(self) -> dict[str, Any]:
        """Return a JSON payload that preserves the nested strategy view.

        The runtime representation is flat, but saving the strategy buckets
        under ``strategy`` keeps reloads and older tools from losing which keys
        participate in strategy mutation/crossover.
        """
        payload: OrderedDict[str, Any] = OrderedDict()
        payload["metadata"] = OrderedDict(
            [
                ("strategy_keys", list(self.strategy_keys)),
                ("identity_strategy_key", self.identity_strategy_key),
                ("fixed_component_keys", sorted(self.fixed_component_keys)),
                ("reflection_format_keys", list(self.reflection_format_keys)),
                ("reflection_strategy_keys", list(self.reflection_strategy_keys)),
            ]
        )
        strategy_payload: OrderedDict[str, list[list[str]]] = OrderedDict()
        for key, candidates in self.flat_components.items():
            if key in self.strategy_keys:
                strategy_payload[key] = candidates
            else:
                payload[key] = candidates
        if strategy_payload:
            payload["strategy"] = strategy_payload
        return payload

    def has_category(self, category: str) -> bool:
        """Return whether a component category exists and contains candidates."""
        if category == "game_rule":
            return bool(self.game_rule_components)
        return category in self.flat_components and bool(self.flat_components[category])

    def get_component(self, category: str, index: int) -> List[str]:
        """Fetch one non-strategy component by category and index."""
        if category == "game_rule":
            candidates = self.game_rule_components
        else:
            candidates = self._candidates_for_key(category)
        if not candidates:
            raise ValueError(f"No candidates found for component category: {category}")
        if index < 0 or index >= len(candidates):
            raise IndexError(
                f"Component index out of range for '{category}': {index} (valid: 0..{len(candidates)-1})"
            )
        return candidates[index]

    def get_strategy_component(self, strategy: str, index: int) -> List[str]:
        """Fetch one strategy component from a named flattened strategy bucket."""
        if strategy not in self.strategy_keys:
            raise KeyError(f"Strategy category not found: {strategy}")
        return self.get_component(strategy, index)

    def get_random_strategy_component_index(self, strategy: str) -> int:
        """Sample a valid random index for one strategy category."""
        return self.get_random_component_index(strategy)

    def get_random_component_index(self, category: str) -> int:
        """Sample a valid random index for a component category."""
        candidates = self.game_rule_components if category == "game_rule" else self._candidates_for_key(category)
        if not candidates:
            raise ValueError(f"No candidates found for component category: {category}")
        return random.randint(0, len(candidates) - 1)

    def add_component(self, category: str, component: List[str]) -> int:
        """Append a newly generated component and return its stored index."""
        if category == "game_rule":
            self.game_rule_components.append(component)
            return len(self.game_rule_components) - 1
        candidates = self._candidates_for_key(category)
        candidates.append(component)
        return len(candidates) - 1

    def add_strategy_component(self, strategy: str, component: List[str]) -> int:
        """Append a newly generated strategy component and return its stored index."""
        if strategy not in self.strategy_keys:
            raise KeyError(f"Strategy category not found: {strategy}")
        return self.add_component(strategy, component)

    def get_component_str(self, category: str, index: int) -> str:
        """Return a component as a single newline-joined string."""
        return "\n".join(self.get_component(category, index))

    def parse_component_str(self, component_str: str) -> List[str]:
        """Convert a text block back into the line-based storage format."""
        return component_str.splitlines()

    def render_selected_static_prompt_lines(
        self,
        selected_indices: Dict[str, int] | None,
        game_rule_index: int = 0,
    ) -> List[str]:
        """Render non-strategy prompt sections from flattened component indices."""
        selected_indices = dict(selected_indices or {})
        rendered_lines: list[str] = []
        for key in self.static_component_keys:
            candidates = self.flat_components.get(key, [])
            if not candidates:
                continue
            selected_index = 0 if key in self.fixed_component_keys else int(selected_indices.get(key, 0))
            if selected_index < 0 or selected_index >= len(candidates):
                selected_index = 0
            lines = self._normalize_component_lines(candidates[selected_index])
            if not lines:
                continue
            if rendered_lines:
                rendered_lines.append("")
            rendered_lines.extend(lines)
        return rendered_lines

    def resolve_evolving_static_keys(self, configured_keys: List[str] | None) -> List[str]:
        """Return all mutable non-strategy categories; config no longer narrows them."""
        return [
            key for key in self.mutable_static_component_keys
        ]

    def is_rewriteable_static_key(self, category: str) -> bool:
        """Return whether one static category may be rewritten by LLM operators."""
        return category in self.static_component_keys and category not in self.fixed_component_keys

    def render_strategy_prompt_lines(
        self,
        strategy_indices: Dict[str, int] | None,
        *,
        include_strategy_identity: bool = True,
    ) -> List[str]:
        """Render the strategy portion of the prompt in flattened schema order."""
        strategy_indices = dict(strategy_indices or {})
        rendered_lines: List[str] = []

        for strategy_key in self.strategy_keys:
            if strategy_key == self.identity_strategy_key and not include_strategy_identity:
                continue
            if strategy_key not in strategy_indices:
                continue

            lines = self._normalize_component_lines(
                self.get_strategy_component(strategy_key, int(strategy_indices[strategy_key]))
            )
            if not lines:
                continue

            if rendered_lines:
                rendered_lines.append("")
            rendered_lines.extend(lines)

        return rendered_lines

    def describe_individual_components(
        self,
        individual,
        *,
        include_strategy_identity: bool = True,
    ) -> Dict[str, Any]:
        """Return the concrete flattened component text selected by one individual."""
        component_indices = dict(getattr(individual, "component_indices", {}) or {})
        payload: Dict[str, Any] = {}
        for key in self.component_keys:
            if key == self.identity_strategy_key and not include_strategy_identity:
                continue
            selected_index = int(component_indices.get(key, 0))
            lines = list(self.get_component(key, selected_index))
            payload[key] = {
                "index": selected_index,
                "lines": lines,
                "text": "\n".join(lines),
                "mutable": key not in self.fixed_component_keys,
            }

        return {
            "individual_id": getattr(individual, "id", None),
            "components": payload,
        }

    def _candidates_for_key(self, key: str) -> list[list[str]]:
        if key not in self.flat_components:
            raise KeyError(f"Component category not found: {key}")
        return self.flat_components[key]
