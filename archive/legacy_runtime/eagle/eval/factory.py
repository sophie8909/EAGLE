"""Generic evaluator factory helpers."""

from __future__ import annotations

from typing import Any

from eagle.core.plugin import TaskPlugin
from eagle.eval.base import Evaluator


def create_evaluator(config: Any, plugin: TaskPlugin, **kwargs: Any) -> Evaluator:
    """Create an evaluator through the selected task plugin."""
    create = getattr(plugin, "create_evaluator", None)
    if create is None:
        raise ValueError(f"Task plugin {plugin.name!r} does not expose create_evaluator().")
    return create(config, **kwargs)
