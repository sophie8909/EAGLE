"""MicroRTS domain adapter."""

from __future__ import annotations

from pathlib import Path

from ...envs.microrts.compiler import compile_microrts, locate_microrts_root


class MicroRTSAdapter:
    """Adapter for the bundled MicroRTS application under ``third_party``."""

    name = "microrts"
    third_party_name = "microrts"

    def third_party_root(self) -> Path:
        """Return the active MicroRTS checkout path."""
        return locate_microrts_root()

    def compile(self) -> None:
        """Compile MicroRTS before Java-backed evaluation."""
        compile_microrts()
