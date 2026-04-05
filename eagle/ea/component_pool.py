"""
Component pool for managing prompt components in the evolutionary algorithm.
This module defines the ComponentPool class, which loads and organizes prompt components from a JSON file. The ComponentPool provides access to different categories of components, such as combat policies, economy policies, production policies, worker behaviors, targeting policies, and movement policies. These components are used by the evolutionary algorithm to construct and evolve effective prompts for guiding agent behavior in MicroRTS.
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
                "global_strategy": [ [ ... ] ],
                "combat_policy": [ [ ... ] ],
                "economy_policy": [ [ ... ] ],
                "production_policy": [ [ ... ] ],
                "worker_policy": [ [ ... ] ],
                "targeting_policy": [ [ ... ] ],
                "movement_policy": [ [ ... ] ],
                "anti_stale_policy": [ [ ... ] ]
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
