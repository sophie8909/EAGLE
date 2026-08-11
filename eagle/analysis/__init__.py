"""Read-only canonical compact-artifact analysis."""

from .loader import RunData, load_run, resolve_explicit_run, resolve_latest_run


def generate_analysis(*args, **kwargs):
    """Load the optional plotting dependency only for report generation."""

    from .report import generate_analysis as _generate_analysis

    return _generate_analysis(*args, **kwargs)

__all__ = [
    "RunData",
    "generate_analysis",
    "load_run",
    "resolve_explicit_run",
    "resolve_latest_run",
]
