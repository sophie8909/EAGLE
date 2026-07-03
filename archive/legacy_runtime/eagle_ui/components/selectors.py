"""Reusable selector builders for NiceGUI pages."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from nicegui import ui

from eagle_ui import services


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
    key: key.rsplit(".", 1)[-1] for key in services.MICRORTS_OPPONENT_CHOICES
}


def create_run_selector(
    *,
    label: str = "Run folder",
    value: str | Path | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a run-folder selector."""
    return _create_selector(label, _run_options(), _string_value(value), on_change, **kwargs)


def create_map_selector(
    *,
    label: str = "Map",
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    include_all: bool = False,
    **kwargs: Any,
) -> Any:
    """Create a MicroRTS map-folder selector."""
    options = _map_options()
    if include_all:
        options = {"all": "All", **options}
    return _create_selector(label, options, value, on_change, **kwargs)


def create_opponent_selector(
    *,
    label: str = "Opponent",
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    include_all: bool = False,
    **kwargs: Any,
) -> Any:
    """Create a MicroRTS opponent selector."""
    options = {"all": "All", **OPPONENT_OPTIONS} if include_all else OPPONENT_OPTIONS
    return _create_selector(label, options, value, on_change, **kwargs)


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


def _run_options() -> dict[str, str]:
    """Discover EAGLE run folders from logs/eagle."""
    services.LOG_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted((path for path in services.LOG_DIR.iterdir() if path.is_dir()), reverse=True)
    return {str(path): path.name for path in paths}


def _map_options() -> dict[str, str]:
    """Discover immediate MicroRTS map folders."""
    maps_root = services.ROOT / "third_party" / "microrts" / "maps"
    if not maps_root.exists():
        return {"8x8": "8x8"}
    options = {path.name: path.name for path in sorted(maps_root.iterdir()) if path.is_dir()}
    return options or {"8x8": "8x8"}
