"""Static task plugin loader."""

from __future__ import annotations

from eagle.core.plugin import TaskPlugin


_PLUGIN_REGISTRY = {
    "microrts": "eagle.plugins.microrts:MicroRTSPlugin",
}
_PLUGIN_SPEC_REGISTRY = {
    "microrts": "eagle.plugins.microrts.specs:register_framework_specs",
}


def load_plugin(name: str) -> TaskPlugin:
    """Load one task plugin by name."""
    normalized = str(name or "").strip().lower().replace("-", "_")
    if normalized not in _PLUGIN_REGISTRY:
        known = ", ".join(sorted(_PLUGIN_REGISTRY))
        raise ValueError(f"Unknown task plugin {name!r}. Known plugins: {known}.")
    module_name, class_name = _PLUGIN_REGISTRY[normalized].split(":", 1)
    from importlib import import_module

    plugin_cls = getattr(import_module(module_name), class_name)
    return plugin_cls()


def register_plugin_specs(name: str) -> None:
    """Register lightweight framework metadata for one task plugin."""
    normalized = str(name or "").strip().lower().replace("-", "_")
    if normalized not in _PLUGIN_SPEC_REGISTRY:
        known = ", ".join(sorted(_PLUGIN_SPEC_REGISTRY))
        raise ValueError(f"Unknown task plugin {name!r}. Known plugins: {known}.")
    module_name, function_name = _PLUGIN_SPEC_REGISTRY[normalized].split(":", 1)
    from importlib import import_module

    register = getattr(import_module(module_name), function_name)
    register()
