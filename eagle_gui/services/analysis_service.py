"""Analysis service adapter for GUI run artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_live_analysis_report(run_dir: Path) -> Any:
    """Build the live analysis report for a run directory.

    Args:
        run_dir: Run artifact directory under `logs/eagle`.

    Returns:
        Analysis report object consumed by the GUI.
    """
    from eagle_gui import desktop_app

    return desktop_app.build_live_analysis_report(run_dir)


def build_timing_analysis_report(run_dir: Path) -> Any:
    """Build the timing analysis report for a run directory."""
    from eagle_gui import desktop_app

    return desktop_app.build_timing_analysis_report(run_dir)


def load_prompts(run_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Load prompt-inspection records for the selected run."""
    from eagle_gui import desktop_app

    return desktop_app.load_prompts(run_dir)
