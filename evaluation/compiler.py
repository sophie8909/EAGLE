"""Compile command construction for generated Java agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompilePlan:
    source_path: Path
    microrts_dir: Path

    def command(self) -> list[str]:
        classpath = f"{self.microrts_dir / 'bin'};{self.microrts_dir / 'lib' / '*'}"
        return ["javac", "-cp", classpath, str(self.source_path)]

