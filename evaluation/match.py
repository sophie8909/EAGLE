"""MicroRTS match command construction and result parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MatchPlan:
    microrts_dir: Path
    agent_class: str
    opponent: str
    tick_limit: int

    def command(self) -> list[str]:
        return [
            "java",
            "-cp",
            f"{self.microrts_dir / 'bin'};{self.microrts_dir / 'lib' / '*'}",
            "tests.EvaluateAI",
            self.agent_class,
            self.opponent,
            str(self.tick_limit),
        ]


def parse_match_score(output: str) -> float:
    for line in output.splitlines():
        if line.startswith("score="):
            return float(line.split("=", 1)[1].strip())
    raise ValueError("MicroRTS match output did not contain a score= line.")

