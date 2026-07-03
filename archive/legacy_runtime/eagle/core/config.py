"""Framework-level config helpers backed by plugin metadata."""

from __future__ import annotations

from typing import Any

from eagle.core.plugin_loader import register_plugin_specs
from eagle.core.registry import PLUGIN_REGISTRY, PluginSpec, normalize_registry_name


def ensure_plugin_specs(application: str) -> None:
    """Ensure lightweight plugin metadata is registered for one application."""
    register_plugin_specs(normalize_registry_name(application or "microrts"))


def plugin_spec(kind: str, plugin_id: str, *, application: str = "microrts") -> PluginSpec:
    """Return one plugin spec after registering the owning application metadata."""
    ensure_plugin_specs(application)
    spec = PLUGIN_REGISTRY.get(kind, plugin_id)
    normalized_application = normalize_registry_name(application)
    if spec.application != normalized_application:
        raise KeyError(f"{kind} plugin {plugin_id!r} is not registered for {application!r}.")
    return spec


def plugin_specs(
    kind: str,
    *,
    application: str = "microrts",
    include_runtime_only: bool = True,
) -> tuple[PluginSpec, ...]:
    """Return plugin specs for one kind and application."""
    ensure_plugin_specs(application)
    specs = PLUGIN_REGISTRY.specs(kind, application=application)
    if include_runtime_only:
        return specs
    return tuple(spec for spec in specs if not spec.default_config.get("runtime_only"))


def plugin_names(
    kind: str,
    *,
    application: str = "microrts",
    include_runtime_only: bool = True,
) -> tuple[str, ...]:
    """Return plugin ids for one kind and application."""
    return tuple(
        spec.id
        for spec in plugin_specs(
            kind,
            application=application,
            include_runtime_only=include_runtime_only,
        )
    )


def plugin_choices(
    kind: str,
    *,
    application: str = "microrts",
    include_runtime_only: bool = True,
) -> dict[str, str]:
    """Return GUI-ready choices for one plugin kind."""
    return {
        spec.id: spec.label
        for spec in plugin_specs(
            kind,
            application=application,
            include_runtime_only=include_runtime_only,
        )
    }


def algorithm_objective_mode(algorithm: Any, *, application: str = "microrts") -> str:
    """Return the objective mode supported by an algorithm plugin."""
    return plugin_spec("algorithm", str(algorithm or "nsga2"), application=application).mode


def algorithm_default_config(algorithm: Any, *, application: str = "microrts") -> dict[str, Any]:
    """Return plugin-declared default config for one algorithm."""
    return dict(plugin_spec("algorithm", str(algorithm or "nsga2"), application=application).default_config)


def is_surrogate_algorithm(algorithm: Any, *, application: str = "microrts") -> bool:
    """Return whether an algorithm plugin declares a surrogate default."""
    return "surrogate" in algorithm_default_config(algorithm, application=application)
