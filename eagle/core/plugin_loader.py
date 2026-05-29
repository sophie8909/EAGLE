"""Static task plugin loader."""

from __future__ import annotations

from eagle.core.plugin import TaskPlugin
from eagle.plugins.microrts import MicroRTSPlugin


_PLUGIN_REGISTRY = {
    "microrts": MicroRTSPlugin,
}


def load_plugin(name: str) -> TaskPlugin:
    """Load one task plugin by name."""
    normalized = str(name or "").strip().lower().replace("-", "_")
    if normalized not in _PLUGIN_REGISTRY:
        known = ", ".join(sorted(_PLUGIN_REGISTRY))
        raise ValueError(f"Unknown task plugin {name!r}. Known plugins: {known}.")
    return _PLUGIN_REGISTRY[normalized]()
