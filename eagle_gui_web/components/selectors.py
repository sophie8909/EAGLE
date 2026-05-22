"""Reusable selector builders for NiceGUI pages."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from nicegui import ui


MODE_OPTIONS = {
    "single": "Single",
    "all": "All",
}
METRIC_OPTIONS = {
    "win_rate": "Win rate",
    "score": "Score",
    "ally_resources": "Ally resources",
    "enemy_resources": "Enemy resources",
    "total_ally_resources": "Total ally resources",
    "total_enemy_resources": "Total enemy resources",
    "resource_difference": "Resource difference",
    "weighted_resource_score": "Weighted resource score",
}
AGGREGATION_OPTIONS = {
    "mean": "Mean",
    "best": "Best",
    "worst": "Worst",
}
OPPONENT_OPTIONS = {
    "ai.abstraction.HeavyRush": "HeavyRush",
    "ai.abstraction.LightRush": "LightRush",
    "ai.RandomBiasedAI": "RandomBiasedAI",
    "ai.RandomAI": "RandomAI",
    "ai.PassiveAI": "PassiveAI",
}


def create_run_selector(
    *,
    label: str = "Run folder",
    value: str | Path | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a run-folder selector."""
    return _create_selector(label, {}, _string_value(value), on_change, **kwargs)


def create_map_selector(
    *,
    label: str = "Map",
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a MicroRTS map selector."""
    return _create_selector(label, {"maps/8x8/basesWorkers8x8.xml": "8x8 / basesWorkers8x8.xml"}, value, on_change, **kwargs)


def create_opponent_selector(
    *,
    label: str = "Opponent",
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a MicroRTS opponent selector."""
    return _create_selector(label, OPPONENT_OPTIONS, value, on_change, **kwargs)


def create_metric_selector(
    *,
    label: str = "Metric",
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a final-test analysis metric selector."""
    return _create_selector(label, METRIC_OPTIONS, value, on_change, **kwargs)


def create_aggregation_selector(
    *,
    label: str = "Aggregation",
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a final-test aggregation selector."""
    return _create_selector(label, AGGREGATION_OPTIONS, value, on_change, **kwargs)


def create_mode_selector(
    *,
    label: str = "Mode",
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a single/all mode selector."""
    return _create_selector(label, MODE_OPTIONS, value, on_change, **kwargs)


def _create_selector(
    label: str,
    options: dict[str, str],
    value: str | None,
    on_change: Callable[[Any], None] | None,
    **kwargs: Any,
) -> Any:
    """Create a select with a validated keyed value."""
    selected_value = _valid_value(options, value)
    return ui.select(options, label=label, value=selected_value, on_change=on_change, **kwargs)


def _valid_value(options: dict[str, str], value: str | None) -> str | None:
    """Return value when valid, otherwise the first available option key."""
    if value in options:
        return value
    return next(iter(options), None)


def _string_value(value: str | Path | None) -> str | None:
    """Normalize optional path values for keyed selectors."""
    return str(value) if value is not None else None
