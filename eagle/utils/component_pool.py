"""
Component pool for managing prompt components in the evolutionary algorithm.
This module defines the ComponentPool class, which loads and organizes prompt
components from a JSON file. The strategy search space is organized around
coherent style and phase buckets rather than function-specific policies so
mutation and crossover can recombine higher-level plans more cleanly.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

class ComponentPool:
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
        self.components = components
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
        

    @classmethod
    def from_json(cls, filepath: str) -> ComponentPool:
        """Load a component pool definition from disk."""
        with open(filepath, "r") as f:
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
        source_blocks: List[List[str]] = []
        can_render_from_source = all(
            len(self.components.get(key, [])) <= 1
            for key in self.game_rule_source_keys
        )

        if can_render_from_source:
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
