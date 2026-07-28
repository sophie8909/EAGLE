"""Read-only canonical compact-artifact analysis."""

from .loader import RunData, load_run, resolve_explicit_run, resolve_latest_run
from .report import generate_analysis

__all__ = [
    "RunData",
    "generate_analysis",
    "load_run",
    "resolve_explicit_run",
    "resolve_latest_run",
]
