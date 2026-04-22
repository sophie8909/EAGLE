"""
Component pool for managing prompt components in the evolutionary algorithm.
This module defines the ComponentPool class, which loads and organizes prompt
components from a JSON file. The strategy search space is organized around
coherent style and phase buckets rather than function-specific policies so
mutation and crossover can recombine higher-level plans more cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

class ComponentPool:
    NON_EVOLVING_STATIC_KEYS = {
        "actions",
        "raw_move_format",
        "json_schema",
        "field_requirements",
        "field_requirement",
        "examples",
    }
    """
        A pool of prompt components loaded from a JSON file.

        The JSON file should have the following structure:
        {
            "role": [ [ ... ] ],
            "critical_rules": [ [ ... ] ],
            "actions": [ [ ... ] ],
            "json_schema": [ [ ... ] ],
            "field_requirements": [ [ ... ] ],
            "examples": [ [ ... ] ],
            "strategy": {
                "strategy_identity": [ [ ... ] ],
                "phase_transition_rule": [ [ ... ] ],
                "early_game_plan": [ [ ... ] ],
                "mid_game_plan": [ [ ... ] ],
                "late_game_plan": [ [ ... ] ],
                "decision_priority": [ [ ... ] ],
                "tactical_heuristics": [ [ ... ] ],
                "anti_stall_rules": [ [ ... ] ]
            }
        }
    """
    

    def __init__(self, components: Dict[str, Any]):
        """Normalize the raw JSON component structure into convenient lookup lists."""
        normalized_components = dict(components)
        strategy_components = dict(normalized_components.get("strategy", {}))

        preferred_strategy_keys = [
            "strategy_identity",
            "phase_transition_rule",
            "early_game_plan",
            "mid_game_plan",
            "late_game_plan",
            "decision_priority",
            "tactical_heuristics",
            "anti_stall_rules",
        ]
        for key in preferred_strategy_keys:
            if key in normalized_components and key not in strategy_components:
                strategy_components[key] = normalized_components.pop(key)

        normalized_components["strategy"] = strategy_components

        self.components = normalized_components
        self.component_keys = list(self.components.keys())
        self.strategy_keys = list(self.components.get("strategy", {}).keys())
        source_game_rule_keys = [
            key for key in self.component_keys if key != "strategy"
        ]
        preferred_game_rule_order = [
            "game_rule",
            "role",
            "critical_rules",
            "game_rules",
            "unit_types",
            "building_types",
            "strategy_guide",
            "game_state_format",
            "raw_move_format",
            "actions",
            "json_schema",
            "field_requirements",
            "examples",
        ]
        ordered_game_rule_keys = [
            key for key in preferred_game_rule_order
            if key in source_game_rule_keys
        ] + [
            key for key in source_game_rule_keys
            if key not in preferred_game_rule_order
        ]
        if "game_rule" in self.components:
            self.game_rule_source_keys = ["game_rule"]
            self.game_rule_components = self.components["game_rule"]
        else:
            self.game_rule_source_keys = ordered_game_rule_keys
            merged_lines: list[str] = []
            for key in self.game_rule_source_keys:
                component_groups = self.components.get(key, [])
                for component in component_groups:
                    merged_lines.extend(component)
            self.game_rule_components = [merged_lines] if merged_lines else []
        self.static_component_keys = [
            key for key in self.game_rule_source_keys
            if key != "game_rule"
        ]
        

    @classmethod
    def from_json(cls, filepath: str) -> ComponentPool:
        """Load a component pool definition from disk."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def has_category(self, category: str) -> bool:
        """Return whether a component category exists and contains candidates."""
        if category == "game_rule":
            return bool(self.game_rule_components)
        return category in self.components and bool(self.components[category])
    
    def get_component(self, category: str, index: int) -> List[str]:
        """Fetch one non-strategy component by category and index."""
        if category == "game_rule":
            candidates = self.game_rule_components
        else:
            if category not in self.components:
                raise KeyError(f"Component category not found: {category}")
            candidates = self.components[category]
        if not candidates:
            raise ValueError(f"No candidates found for component category: {category}")
        if index < 0 or index >= len(candidates):
            raise IndexError(
                f"Component index out of range for '{category}': {index} (valid: 0..{len(candidates)-1})"
            )
        return candidates[index]
    
    def get_strategy_component(self, strategy: str, index: int) -> List[str]:
        """Fetch one strategy component from a named strategy bucket."""
        candidates = self.components["strategy"][strategy]
        if not candidates:
            raise ValueError(f"No candidates found for strategy category: {strategy}")
        if index < 0 or index >= len(candidates):
            raise IndexError(
                f"Strategy index out of range for '{strategy}': {index} (valid: 0..{len(candidates)-1})"
            )
        return candidates[index]

    def get_random_strategy_component_index(self, strategy: str) -> int:
        """Sample a valid random index for one strategy category."""
        import random
        candidates = self.components["strategy"][strategy]
        if not candidates:
            raise ValueError(f"No candidates found for strategy category: {strategy}")
        return random.randint(0, len(candidates) - 1)
    
    def get_random_component_index(self, category: str) -> int:
        """Sample a valid random index for a non-strategy category."""
        import random
        if category == "game_rule":
            candidates = self.game_rule_components
        else:
            if category not in self.components:
                raise KeyError(f"Component category not found: {category}")
            candidates = self.components[category]
        if not candidates:
            raise ValueError(f"No candidates found for component category: {category}")
        return random.randint(0, len(candidates) - 1)
    
    def add_component(self, category: str, component: List[str]) -> int:
        """Append a newly generated component and return its stored index."""
        if category == "game_rule":
            self.game_rule_components.append(component)
            return len(self.game_rule_components) - 1
        if category not in self.components:
            raise KeyError(f"Component category not found: {category}")
        self.components[category].append(component)
        return len(self.components[category]) - 1  # Return the index of the newly added component

    def add_strategy_component(self, strategy: str, component: List[str]) -> int:
        """Append a newly generated strategy component and return its stored index."""
        if strategy not in self.components["strategy"]:
            raise KeyError(f"Strategy category not found: {strategy}")
        self.components["strategy"][strategy].append(component)
        return len(self.components["strategy"][strategy]) - 1  # Return the index of the newly added component     
    def get_component_str(self, category: str, index: int) -> str:
        """Return a non-strategy component as a single newline-joined string."""
        if category == "strategy":
            raise ValueError(
                "Use get_strategy_component(strategy_key, index) for strategy components."
            )
        component_lines = self.get_component(category, index)
        return "\n".join(component_lines)
    
    def parse_component_str(self, component_str: str) -> List[str]:
        """Convert a text block back into the line-based storage format."""
        return component_str.splitlines()

    @staticmethod
    def _normalize_component_lines(component_lines: List[str]) -> List[str]:
        """Drop empty placeholder lines while preserving original text order."""
        return [str(line) for line in component_lines if str(line).strip()]

    def render_static_prompt_lines(self, game_rule_index: int = 0) -> List[str]:
        """Render the non-strategy prompt prefix from the current component schema."""
        return self.render_selected_static_prompt_lines({}, game_rule_index=game_rule_index)

    def render_selected_static_prompt_lines(
        self,
        selected_indices: Dict[str, int] | None,
        game_rule_index: int = 0,
    ) -> List[str]:
        """Render the non-strategy prompt prefix with explicit per-category selection."""
        selected_indices = dict(selected_indices or {})
        source_blocks: List[List[str]] = []
        can_render_from_source = all(
            len(self.components.get(key, [])) <= 1
            for key in self.game_rule_source_keys
        )
        has_selected_static_indices = any(
            key in selected_indices
            for key in self.static_component_keys
        )

        if has_selected_static_indices:
            for key in self.game_rule_source_keys:
                if key == "game_rule":
                    continue
                component_groups = self.components.get(key, [])
                if not component_groups:
                    continue
                selected_index = int(selected_indices.get(key, 0))
                if selected_index < 0 or selected_index >= len(component_groups):
                    selected_index = 0
                normalized_lines = self._normalize_component_lines(component_groups[selected_index])
                if normalized_lines:
                    source_blocks.append(normalized_lines)
        elif can_render_from_source:
            for key in self.game_rule_source_keys:
                for component in self.components.get(key, []):
                    normalized_lines = self._normalize_component_lines(component)
                    if normalized_lines:
                        source_blocks.append(normalized_lines)
        else:
            normalized_lines = self._normalize_component_lines(
                self.get_component("game_rule", game_rule_index)
            )
            if normalized_lines:
                source_blocks.append(normalized_lines)

        rendered_lines: List[str] = []
        for block in source_blocks:
            if rendered_lines:
                rendered_lines.append("")
            rendered_lines.extend(block)
        return rendered_lines

    def resolve_evolving_static_keys(self, configured_keys: List[str] | None) -> List[str]:
        """Return config-enabled static categories that actually exist in the pool."""
        configured = [str(key) for key in (configured_keys or [])]
        return [
            key for key in self.static_component_keys
            if key in configured and key not in self.NON_EVOLVING_STATIC_KEYS
        ]

    def render_strategy_prompt_lines(
        self,
        strategy_indices: Dict[str, int] | None,
        *,
        include_strategy_identity: bool = True,
    ) -> List[str]:
        """Render the strategy portion of the prompt in schema order."""
        strategy_indices = dict(strategy_indices or {})
        rendered_lines: List[str] = []

        for strategy_key in self.strategy_keys:
            if strategy_key == "strategy_identity" and not include_strategy_identity:
                continue
            if strategy_key not in strategy_indices:
                continue

            normalized_lines = self._normalize_component_lines(
                self.get_strategy_component(strategy_key, strategy_indices[strategy_key])
            )
            if not normalized_lines:
                continue

            if rendered_lines:
                rendered_lines.append("")
            rendered_lines.extend(normalized_lines)

        return rendered_lines

    def describe_individual_components(
        self,
        individual,
        *,
        include_strategy_identity: bool = True,
    ) -> Dict[str, Any]:
        """Return the concrete component text selected by one individual."""
        static_payload: Dict[str, Any] = {}
        for key in self.game_rule_source_keys:
            if key == "game_rule":
                static_payload[key] = {
                    "index": int(getattr(individual, "game_rule", 0)),
                    "lines": list(self.get_component("game_rule", int(getattr(individual, "game_rule", 0)))),
                    "text": self.get_component_str("game_rule", int(getattr(individual, "game_rule", 0))),
                }
                continue

            candidates = self.components.get(key, [])
            if not candidates:
                continue
            selected_index = int(getattr(individual, "static_components", {}).get(key, 0))
            lines = list(self.get_component(key, selected_index))
            static_payload[key] = {
                "index": selected_index,
                "lines": lines,
                "text": "\n".join(lines),
            }

        strategy_payload: Dict[str, Any] = {}
        strategy_indices = dict(getattr(individual, "strategy", {}) or {})
        for strategy_key in self.strategy_keys:
            if strategy_key == "strategy_identity" and not include_strategy_identity:
                continue
            if strategy_key not in strategy_indices:
                continue
            selected_index = int(strategy_indices[strategy_key])
            lines = list(self.get_strategy_component(strategy_key, selected_index))
            strategy_payload[strategy_key] = {
                "index": selected_index,
                "lines": lines,
                "text": "\n".join(lines),
            }

        return {
            "individual_id": getattr(individual, "id", None),
            "game_rule_source_keys": list(self.game_rule_source_keys),
            "static_components": static_payload,
            "strategy_components": strategy_payload,
        }
