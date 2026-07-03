"""Workspace management for generated Java agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eagle.candidate import Candidate
from generation.backend import generated_class_name


@dataclass(frozen=True)
class AgentWorkspace:
    root: Path

    def package_dir(self) -> Path:
        return self.root / "src" / "ai" / "generated"

    def write_source(self, candidate: Candidate, java_source: str) -> Path:
        output_dir = self.package_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{generated_class_name(candidate.id)}.java"
        path.write_text(java_source, encoding="utf-8")
        return path
