"""Small compatibility helpers for NiceGUI EChart updates."""

from __future__ import annotations


def replace_chart_options(chart: object, options: dict) -> None:
    """Replace an EChart's mutable options dictionary in place."""
    current = getattr(chart, "options")
    current.clear()
    current.update(options)
