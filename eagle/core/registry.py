"""Name-based registries for algorithms, operators, and evaluators."""

from __future__ import annotations

from typing import Any, Callable


class Registry:
    """Small explicit registry used by config-driven experiments."""

    def __init__(self, label: str):
        """Create an empty registry with one human-readable label."""
        self.label = label
        self._items: dict[str, Any] = {}

    def register(self, name: str, item: Any | None = None) -> Callable[[Any], Any] | Any:
        """Register an item by name or return a decorator for deferred use."""
        normalized_name = normalize_registry_name(name)

        def decorator(candidate: Any) -> Any:
            """Store one candidate under the normalized name."""
            self._items[normalized_name] = candidate
            return candidate

        if item is None:
            return decorator
        return decorator(item)

    def get(self, name: str) -> Any:
        """Return a registered item by name."""
        normalized_name = normalize_registry_name(name)
        if normalized_name not in self._items:
            raise KeyError(
                f"Unknown {self.label}: {name!r}. "
                f"Available values: {', '.join(sorted(self._items)) or '(none)'}."
            )
        return self._items[normalized_name]

    def names(self) -> list[str]:
        """Return registered names in sorted order."""
        return sorted(self._items)


def normalize_registry_name(name: str) -> str:
    """Normalize CLI/config names without changing their meaning."""
    return str(name).strip().lower().replace("-", "_")


ALGORITHMS = Registry("algorithm")
CROSSOVER_OPERATORS = Registry("crossover operator")
MUTATION_OPERATORS = Registry("mutation operator")
REFLECTION_OPERATORS = Registry("reflection operator")
PARENT_SELECTION = Registry("parent selection")
ENVIRONMENTAL_SELECTION = Registry("environmental selection")
EVALUATORS = Registry("evaluator")
