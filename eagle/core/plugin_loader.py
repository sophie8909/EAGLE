"""Static task plugin loader."""

from __future__ import annotations

from eagle.core.plugin import TaskPlugin


_PLUGIN_REGISTRY = {
    "microrts": "eagle.plugins.microrts:MicroRTSPlugin",
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
