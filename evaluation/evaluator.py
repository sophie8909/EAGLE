"""Generated Java agent evaluator."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from eagle.candidate import CandidatePrompt
from generation.backend import generated_class_name

from .compiler import CompilePlan
from .fitness import fitness_from_score
from .match import MatchPlan, parse_match_score


@dataclass(frozen=True)
class Evaluation:
    fitness: float
    artifacts: dict[str, str]


@dataclass(frozen=True)
class CandidateEvaluator:
    microrts_dir: Path
    opponent: str
    tick_limit: int
    dry_run: bool = True

    def evaluate(self, candidate: CandidatePrompt, source_path: Path) -> Evaluation:
        compile_plan = CompilePlan(source_path=source_path, microrts_dir=self.microrts_dir)
        agent_class = f"ai.generated.{generated_class_name(candidate.candidate_id)}"
        match_plan = MatchPlan(
            microrts_dir=self.microrts_dir,
            agent_class=agent_class,
            opponent=self.opponent,
            tick_limit=self.tick_limit,
        )
        artifacts = {
            "source_path": str(source_path),
            "compile_command": " ".join(compile_plan.command()),
            "match_command": " ".join(match_plan.command()),
        }
        if self.dry_run:
            return Evaluation(fitness=0.0, artifacts=artifacts)

        subprocess.run(compile_plan.command(), cwd=self.microrts_dir, check=True)
        completed = subprocess.run(
            match_plan.command(),
            cwd=self.microrts_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        score = parse_match_score(completed.stdout)
        return Evaluation(fitness=fitness_from_score(score), artifacts=artifacts)

