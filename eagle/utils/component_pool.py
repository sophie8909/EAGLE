"""Component pool for managing flattened prompt components."""

from __future__ import annotations

import json
import random
import re
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Dict, List


class ComponentPool:
    """Prompt component pool with one flattened component namespace."""

    DEFAULT_NON_EVOLVING_COMPONENT_KEYS = {"json_schema"}
    TRAINING_EXAMPLES_KEY = "training_examples"
    CODE_MANAGED_COMPONENT_KEYS = {TRAINING_EXAMPLES_KEY}
    MAX_TRAINING_EXAMPLES_PER_RENDER = 4

    def __init__(self, components: Dict[str, Any]):
        """Create a flattened prompt-component pool from the current JSON schema.

        Args:
            components: Current component-pool payload. The only training-example
                schema accepted here is the merged `training_examples` list.

        Call flow:
            `ComponentPool.from_json()` loads JSON, this constructor normalizes current
            component candidates, and EA evaluators later call `render_prompt_lines()`
            to produce the exact prompt text for one individual.
        """
        raw_components = dict(components or {})
        metadata = dict(raw_components.pop("metadata", {}) or {})
        self.metadata = metadata

        self.flat_components: OrderedDict[str, list[list[str]]] = OrderedDict()
        self.prompt_component_keys: list[str] = []
        self.training_examples: list[dict[str, Any]] = []
        for key, value in raw_components.items():
            key = str(key)
            if key == self.TRAINING_EXAMPLES_KEY:
                self.training_examples = self._normalize_training_examples(value)
                self.prompt_component_keys.append(key)
                continue
            self.flat_components[key] = self._normalize_candidates(value)
            self.prompt_component_keys.append(key)

        self.component_keys = list(self.flat_components.keys())
        self.game_rule_source_keys = list(self.component_keys)
        self.game_rule_components = [self._flatten_all_prompt_lines()]

        metadata_non_evolving = metadata.get("non_evolving_component_keys")
        self.non_evolving_component_keys = self._valid_key_set(
            metadata_non_evolving,
            fallback=self.DEFAULT_NON_EVOLVING_COMPONENT_KEYS,
        )
        self.evolving_component_keys = self.resolve_evolving_component_keys(None)

        self.identity_component_key = self._resolve_identity_component_key(metadata)
        self.reflection_format_keys = self._filter_component_keys(
            metadata.get("reflection_format_keys"),
            fallback=self.evolving_component_keys,
        )
        self.reflection_alignment_keys = self._filter_component_keys(
            metadata.get("reflection_alignment_keys"),
            fallback=self.evolving_component_keys,
        )

        self.dependent_strategy_keys = [
            key for key in self.evolving_component_keys
            if key != self.identity_component_key
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

    def _valid_key_set(self, keys: Any, *, fallback: set[str]) -> set[str]:
        raw_keys = fallback if keys is None else set(str(key) for key in (keys or []))
        return {
            key
            for key in raw_keys
            if key in self.component_keys
            or key == "json_schema"
            or key in self.CODE_MANAGED_COMPONENT_KEYS
        }

    def _resolve_identity_component_key(self, metadata: dict[str, Any]) -> str | None:
        explicit_identity = metadata.get("identity_component_key")
        if explicit_identity is not None and str(explicit_identity) in self.component_keys:
            return str(explicit_identity)
        return None

    def _filter_component_keys(self, keys: Any, *, fallback: list[str]) -> list[str]:
        if not keys:
            return list(fallback)
        return [
            str(key) for key in keys
            if str(key) in self.component_keys and str(key) not in self.non_evolving_component_keys
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

    def configure_non_evolving_keys(self, keys: list[str] | None) -> None:
        """Apply config-level component exclusions after loading the pool."""
        self.non_evolving_component_keys = self._valid_key_set(
            keys,
            fallback=self.DEFAULT_NON_EVOLVING_COMPONENT_KEYS,
        )
        self.evolving_component_keys = self.resolve_evolving_component_keys(None)
        self.dependent_strategy_keys = [
            key for key in self.evolving_component_keys
            if key != self.identity_component_key
        ]

    def resolve_evolving_component_keys(self, non_evolving_keys: list[str] | None) -> list[str]:
        """Return component keys that may enter evolution."""
        excluded = self._valid_key_set(
            non_evolving_keys,
            fallback=self.non_evolving_component_keys,
        )
        return [key for key in self.component_keys if key not in excluded]

    def to_flat_dict(self) -> dict[str, Any]:
        """Return the canonical flattened component payload."""
        payload: dict[str, Any] = {}
        for key in self.prompt_component_keys:
            if key == self.TRAINING_EXAMPLES_KEY:
                payload[key] = deepcopy(self.training_examples)
            else:
                payload[key] = self.flat_components[key]
        return payload

    def to_component_dict(self) -> dict[str, Any]:
        """Return a JSON payload using the flattened component schema."""
        payload: OrderedDict[str, Any] = OrderedDict()
        payload["metadata"] = OrderedDict(
            [
                ("identity_component_key", self.identity_component_key),
                ("non_evolving_component_keys", sorted(self.non_evolving_component_keys)),
                ("reflection_format_keys", list(self.reflection_format_keys)),
                ("reflection_alignment_keys", list(self.reflection_alignment_keys)),
            ]
        )
        for key in self.prompt_component_keys:
            if key == self.TRAINING_EXAMPLES_KEY:
                payload[key] = deepcopy(self.training_examples)
            else:
                payload[key] = deepcopy(self.flat_components[key])
        return payload

    def set_training_examples(self, examples: list[dict[str, Any]]) -> None:
        """Replace runtime-managed training examples."""
        self.training_examples = self._normalize_training_examples(examples)

    def extend_training_examples(self, examples: list[dict[str, Any]], *, max_examples: int | None = None) -> None:
        """Append deduplicated runtime-managed training examples."""
        merged = list(self.training_examples)
        seen = {self._training_example_key(example) for example in merged}
        for example in self._normalize_training_examples(examples):
            key = self._training_example_key(example)
            if key in seen:
                continue
            merged.append(example)
            seen.add(key)
        if max_examples is not None:
            merged = merged[-max(1, int(max_examples)):]
        self.training_examples = merged

    def has_category(self, category: str) -> bool:
        """Return whether a component category exists and contains candidates."""
        if category == "game_rule":
            return bool(self.game_rule_components)
        return category in self.flat_components and bool(self.flat_components[category])

    def get_component(self, category: str, index: int) -> List[str]:
        """Fetch one component by category and index."""
        candidates = self.game_rule_components if category == "game_rule" else self._candidates_for_key(category)
        if not candidates:
            raise ValueError(f"No candidates found for component category: {category}")
        if index < 0 or index >= len(candidates):
            raise IndexError(
                f"Component index out of range for '{category}': {index} (valid: 0..{len(candidates)-1})"
            )
        return candidates[index]

    def get_random_component_index(self, category: str) -> int:
        """Sample a valid random index for a component category."""
        candidates = self.game_rule_components if category == "game_rule" else self._candidates_for_key(category)
        if not candidates:
            raise ValueError(f"No candidates found for component category: {category}")
        return random.randint(0, len(candidates) - 1)

    def add_component(self, category: str, component: List[str]) -> int:
        """Append a newly generated component and return its stored index."""
        component = self._normalize_component_lines(component)
        if category == "game_rule":
            self.game_rule_components.append(component)
            return len(self.game_rule_components) - 1
        candidates = self._candidates_for_key(category)
        candidates.append(component)
        return len(candidates) - 1

    def get_component_str(self, category: str, index: int) -> str:
        """Return a component as a single newline-joined string."""
        return "\n".join(self.get_component(category, index))

    def parse_component_str(self, component_str: str) -> List[str]:
        """Convert a text block back into the line-based storage format."""
        return self._normalize_component_lines(str(component_str).splitlines())

    def parse_rewritten_component(self, category: str, component_str: str) -> List[str]:
        """Parse LLM rewrite output while keeping only the requested component."""
        if category not in self.component_keys:
            raise KeyError(f"Component category not found: {category}")
        return self.parse_component_str(
            self._extract_target_component_text(category, str(component_str))
        )

    def _extract_target_component_text(self, category: str, text: str) -> str:
        text = self._strip_code_fences(text.strip())
        if not text:
            return ""

        lines = text.splitlines()
        known_keys = set(self.component_keys)
        collected: list[str] = []
        collecting = False
        found_target_header = False
        found_any_component_header = False

        for line in lines:
            header_key = self._component_header_key(line, known_keys)
            if header_key is None:
                if collecting:
                    collected.append(line)
                continue

            found_any_component_header = True
            if header_key == category:
                found_target_header = True
                collecting = True
                continue
            if found_target_header and collecting:
                break
            collecting = False

        if found_target_header:
            return "\n".join(collected).strip()

        if found_any_component_header:
            prefix_lines: list[str] = []
            for line in lines:
                if self._component_header_key(line, known_keys) is not None:
                    break
                prefix_lines.append(line)
            if any(line.strip() for line in prefix_lines):
                return "\n".join(prefix_lines).strip()

        return text

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _component_header_key(line: str, known_keys: set[str]) -> str | None:
        stripped = line.strip()
        if not stripped:
            return None

        bracket_match = re.fullmatch(r"\[([A-Za-z0-9_\-]+)\]", stripped)
        if bracket_match and bracket_match.group(1) in known_keys:
            return bracket_match.group(1)

        heading_match = re.fullmatch(r"#{1,6}\s*([A-Za-z0-9_\-]+)\s*:?", stripped)
        if heading_match and heading_match.group(1) in known_keys:
            return heading_match.group(1)

        label_match = re.fullmatch(r"([A-Za-z0-9_\-]+)\s*:", stripped)
        if label_match and label_match.group(1) in known_keys:
            return label_match.group(1)

        return None

    def render_prompt_lines(
        self,
        selected_indices: Dict[str, int] | None,
        *,
        include_identity_component: bool = True,
    ) -> List[str]:
        """Render the full prompt from flattened component indices."""
        selected_indices = dict(selected_indices or {})
        rendered_lines: list[str] = []
        for key in self.prompt_component_keys:
            if key == self.TRAINING_EXAMPLES_KEY:
                lines = self._render_training_examples(selected_indices.get(key))
                if lines:
                    if rendered_lines:
                        rendered_lines.append("")
                    rendered_lines.extend(lines)
                continue
            if not self._selected_enabled(selected_indices.get(key, 0)):
                continue
            if key == self.identity_component_key and not include_identity_component:
                continue
            candidates = self.flat_components.get(key, [])
            if not candidates:
                continue
            selected_index = 0 if key in self.non_evolving_component_keys else self._selected_index(selected_indices.get(key, 0))
            if selected_index < 0 or selected_index >= len(candidates):
                selected_index = 0
            lines = self._normalize_component_lines(candidates[selected_index])
            if not lines:
                continue
            if rendered_lines:
                rendered_lines.append("")
            rendered_lines.extend(lines)
        return rendered_lines

    @staticmethod
    def _selected_index(value: Any) -> int:
        if isinstance(value, dict):
            value = value.get("index", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _selected_enabled(value: Any) -> bool:
        if isinstance(value, dict):
            value = value.get("enabled", 1)
        else:
            value = 1
        try:
            return bool(int(value))
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _normalize_training_examples(value: Any) -> list[dict[str, Any]]:
        """Normalize merged training examples while preserving example text."""
        if not isinstance(value, list):
            return []
        examples: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if isinstance(item, dict):
                name = str(item.get("name", f"example_{index}"))
                content = item.get("content", [])
            else:
                name = f"example_{index}"
                content = item
            if isinstance(content, list):
                lines = [str(line) for line in content]
            else:
                lines = [str(content)]
            examples.append({"name": name, "content": lines})
        return examples

    def _render_training_examples(self, selection: Any = None) -> list[str]:
        """Sample and concatenate training examples for one prompt render."""
        if not self.training_examples:
            return []
        max_count = min(self.MAX_TRAINING_EXAMPLES_PER_RENDER, len(self.training_examples))
        sample_count = self._training_example_sample_count(selection, max_count)
        if sample_count <= 0:
            return []
        selected_examples = random.sample(self.training_examples, sample_count)
        rendered_lines: list[str] = []
        for example in selected_examples:
            lines = self._normalize_component_lines(example.get("content", []))
            if not lines:
                continue
            if rendered_lines:
                rendered_lines.append("")
            rendered_lines.extend(lines)
        return rendered_lines

    @staticmethod
    def _training_example_key(example: dict[str, Any]) -> str:
        moves = example.get("moves")
        if isinstance(moves, list) and moves:
            move = moves[0]
            if isinstance(move, dict):
                return "|".join(
                    str(move.get(field, "")).strip().lower()
                    for field in ("raw_move", "action_type", "unit_type")
                )
        return "\n".join(str(line).strip().lower() for line in example.get("content", []))

    @staticmethod
    def _training_example_sample_count(selection: Any, max_count: int) -> int:
        """Resolve random or fixed training-example sample count."""
        if isinstance(selection, dict):
            selection = selection.get("sample_count", selection.get("count"))
        raw_selection = str(selection).strip().lower() if selection is not None else ""
        if selection is None or raw_selection in {"", "random"}:
            return random.randint(0, max_count)
        normalized_selection = raw_selection.replace("_", " ")
        range_match = re.search(r"(\d+)\s*-\s*(\d+)", normalized_selection)
        if not range_match:
            range_match = re.search(r"random\s+(\d+)\s+(\d+)", normalized_selection)
        if range_match:
            lower = max(0, min(max_count, int(range_match.group(1))))
            upper = max(0, min(max_count, int(range_match.group(2))))
            if lower > upper:
                lower, upper = upper, lower
            return random.randint(lower, upper)
        try:
            fixed_count = int(selection)
        except (TypeError, ValueError):
            return random.randint(0, max_count)
        return max(0, min(max_count, fixed_count))

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
            if key == self.identity_component_key and not include_strategy_identity:
                continue
            selected_value = component_indices.get(key, 0)
            selected_index = self._selected_index(selected_value)
            lines = list(self.get_component(key, selected_index))
            payload[key] = {
                "index": selected_index,
                "lines": lines,
                "text": "\n".join(lines),
                "evolving": key not in self.non_evolving_component_keys,
                "included": self._selected_enabled(selected_value),
            }
        return {
            "individual_id": getattr(individual, "id", None),
            "components": payload,
        }

    def _candidates_for_key(self, key: str) -> list[list[str]]:
        if key not in self.flat_components:
            raise KeyError(f"Component category not found: {key}")
        return self.flat_components[key]
