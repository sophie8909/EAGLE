"""Reusable select components for NiceGUI pages."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui


def create_key_select(
    label: str,
    options: dict[str, str],
    value: str | None = None,
    on_change: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a select whose values are stable internal keys."""
    first_key = next(iter(options))
    selected_value = value if value in options else first_key
    return ui.select(options, label=label, value=selected_value, on_change=on_change, **kwargs)
