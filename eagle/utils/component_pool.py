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
    PREFERRED_STRATEGY_KEYS = {
        "strategy_identity",
        "phase_transition_rule",
        "early_game_plan",
        "mid_game_plan",
        "late_game_plan",
        "decision_priority",
        "tactical_heuristics",
        "anti_stall_rules",
        "combat_evaluation",
        "decision_rule",
    }

    def __init__(self, components: Dict[str, Any]):
        self.flat_components: OrderedDict[str, list[list[str]]] = OrderedDict()
        self.strategy_keys: list[str] = []
        self._source_strategy_keys: set[str] = set()

        for key, value in dict(components or {}).items():
            if key == "strategy" and isinstance(value, dict):
                for strategy_key, candidates in value.items():
                    strategy_key = str(strategy_key)
                    self._source_strategy_keys.add(strategy_key)
                    self.strategy_keys.append(strategy_key)
                    self.flat_components[strategy_key] = self._normalize_candidates(candidates)
                continue
            key = str(key)
            if key in self.PREFERRED_STRATEGY_KEYS and key not in self.strategy_keys:
                self.strategy_keys.append(key)
            self.flat_components[key] = self._normalize_candidates(value)

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
        self.evolving_component_keys = [
            key for key in self.component_keys
            if key not in self.FIXED_COMPONENT_KEYS
        ]

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
            selected_index = 0 if key in self.FIXED_COMPONENT_KEYS else int(selected_indices.get(key, 0))
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
            key for key in self.static_component_keys
            if key not in self.FIXED_COMPONENT_KEYS
        ]

    def is_rewriteable_static_key(self, category: str) -> bool:
        """Return whether one static category may be rewritten by LLM operators."""
        return category in self.static_component_keys and category not in self.FIXED_COMPONENT_KEYS

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
            if strategy_key == "strategy_identity" and not include_strategy_identity:
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
            if key == "strategy_identity" and not include_strategy_identity:
                continue
            selected_index = int(component_indices.get(key, 0))
            lines = list(self.get_component(key, selected_index))
            payload[key] = {
                "index": selected_index,
                "lines": lines,
                "text": "\n".join(lines),
                "mutable": key not in self.FIXED_COMPONENT_KEYS,
            }

        return {
            "individual_id": getattr(individual, "id", None),
            "components": payload,
        }

    def _candidates_for_key(self, key: str) -> list[list[str]]:
        if key not in self.flat_components:
            raise KeyError(f"Component category not found: {key}")
        return self.flat_components[key]
