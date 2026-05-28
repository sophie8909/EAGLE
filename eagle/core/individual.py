"""Core individual interface for reusable EAGLE algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Individual:
    """Framework-level candidate representation."""

    genome: Any = None
    rendered_prompt: str = ""
    fitness: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
