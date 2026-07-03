"""Name-based registries for framework plugins and runtime classes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable


OBJECTIVE_MODES = {"SO", "MO", "both"}


@dataclass(frozen=True)
class PluginSpec:
    """Metadata for one replaceable framework component."""

    id: str
    label: str
    kind: str
    mode: str = "both"
    default_config: Mapping[str, Any] = field(default_factory=dict)
    factory: Any | None = None
    application: str = "microrts"


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


class PluginRegistry:
    """Registry for metadata describing replaceable EAGLE framework components."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, PluginSpec]] = {}

    def register(self, spec: PluginSpec) -> PluginSpec:
        """Register one plugin spec and return it for decorator-style use."""
        kind = normalize_registry_name(spec.kind)
        plugin_id = normalize_registry_name(spec.id)
        mode = str(spec.mode or "both")
        if mode not in OBJECTIVE_MODES:
            raise ValueError(f"Plugin {spec.id!r} mode must be one of: SO, MO, both.")
        normalized = PluginSpec(
            id=plugin_id,
            label=str(spec.label or plugin_id),
            kind=kind,
            mode=mode,
            default_config=dict(spec.default_config or {}),
            factory=spec.factory,
            application=normalize_registry_name(spec.application or "microrts"),
        )
        self._items.setdefault(kind, {})[plugin_id] = normalized
        return normalized

    def get(self, kind: str, plugin_id: str) -> PluginSpec:
        """Return one plugin spec by kind and id."""
        normalized_kind = normalize_registry_name(kind)
        normalized_id = normalize_registry_name(plugin_id)
        plugins = self._items.get(normalized_kind, {})
        if normalized_id not in plugins:
            known = ", ".join(sorted(plugins)) or "(none)"
            raise KeyError(f"Unknown {normalized_kind} plugin {plugin_id!r}. Available values: {known}.")
        return plugins[normalized_id]

    def specs(self, kind: str, *, application: str | None = None) -> tuple[PluginSpec, ...]:
        """Return registered specs for one plugin kind."""
        normalized_kind = normalize_registry_name(kind)
        normalized_application = normalize_registry_name(application) if application else None
        specs = tuple(self._items.get(normalized_kind, {}).values())
        if normalized_application is not None:
            specs = tuple(spec for spec in specs if spec.application == normalized_application)
        return tuple(sorted(specs, key=lambda spec: spec.id))

    def names(self, kind: str, *, application: str | None = None) -> tuple[str, ...]:
        """Return registered plugin ids for one kind."""
        return tuple(spec.id for spec in self.specs(kind, application=application))


PLUGIN_REGISTRY = PluginRegistry()


ALGORITHMS = Registry("algorithm")
CROSSOVER_OPERATORS = Registry("crossover operator")
MUTATION_OPERATORS = Registry("mutation operator")
REFLECTION_OPERATORS = Registry("reflection operator")
PARENT_SELECTION = Registry("parent selection")
ENVIRONMENTAL_SELECTION = Registry("environmental selection")
EVALUATORS = Registry("evaluator")
