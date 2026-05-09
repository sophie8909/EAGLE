"""Register built-in component operators."""

from __future__ import annotations

from ..core.registry import (
    ENVIRONMENTAL_SELECTION,
    PARENT_SELECTION,
)
from ..evolution.component.environment_selection import EnvironmentSelection
from ..evolution.component.parent_selection import ParentSelection


def register_default_operators() -> None:
    """Populate registries with the built-in operator functions."""
    PARENT_SELECTION.register("random", ParentSelection.random_selection)
    PARENT_SELECTION.register("tournament", ParentSelection.tournament_selection)
    ENVIRONMENTAL_SELECTION.register("elitism", EnvironmentSelection.elitism_selection)
