"""Domain adapter contracts for third-party applications."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DomainAdapter(Protocol):
    """Minimal interface for one application under ``third_party``."""

    name: str
    third_party_name: str

    def third_party_root(self) -> Path:
        """Return the root directory for this application under ``third_party``."""

    def compile(self) -> None:
        """Prepare the third-party application before evaluation runs."""
