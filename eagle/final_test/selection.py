"""Select completed-run candidates without observing any final-test result."""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SelectedCandidate:
    candidate_id: str
    generation: int
    evolution_game_performance: float
    evolution_code_quality: float
    source_path: Path
    individual_path: Path

    def to_json_dict(self, run_dir: Path) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "generation": self.generation,
            "source_evolution_objectives": {
                "game_performance": self.evolution_game_performance,
                "code_quality": self.evolution_code_quality,
            },
            "source_artifact_paths": {
                "individual": self.individual_path.relative_to(run_dir).as_posix(),
                "generated_java": self.source_path.relative_to(run_dir).as_posix(),
            },
        }


@dataclass(frozen=True)
class SelectionDecision:
    run_id: str
    selector: str
    candidates: tuple[SelectedCandidate, ...]
    tie_breaking: dict[str, Any]
    selected_at: str
    git_commit: str | None

    def to_json_dict(self, run_dir: Path) -> dict[str, Any]:
        return {
            "selection_schema_version": "eagle-final-test-selection-v1",
            "run_id": self.run_id,
            "selector": self.selector,
            "selected_candidate_ids": [item.candidate_id for item in self.candidates],
            "selected_candidates": [item.to_json_dict(run_dir) for item in self.candidates],
            "tie_breaking_decisions": self.tie_breaking,
            "selection_timestamp": self.selected_at,
            "git_commit": self.git_commit,
            "no_final_test_result_used": True,
            "selection_evidence_statement": (
                "Selection read only summary.json and canonical completed-run candidate artifacts; "
                "the final_tests tree was not an input."
            ),
        }


def select_final_test_candidates(
    run_dir: Path,
    *,
    selector: str | None = None,
    candidate_id: str | None = None,
    selected_at: str | None = None,
    git_commit: str | None = None,
) -> SelectionDecision:
    """Resolve explicit, best-game, balanced, or Pareto candidates deterministically."""

    run_dir = run_dir.resolve()
    summary_path = run_dir / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"EA run is not complete or summary.json is invalid: {summary_path}") from exc
    if not isinstance(summary.get("final_population"), list) or not isinstance(
        summary.get("pareto_fronts"), list
    ):
        raise ValueError("Completed run summary lacks final_population or pareto_fronts metadata.")
    if (selector is None) == (candidate_id is None):
        raise ValueError("Choose exactly one selector or explicit candidate_id.")

    final_candidates = {
        str(item.get("candidate_id") or item.get("id")): item
        for item in summary["final_population"]
        if isinstance(item, dict)
    }
    tie_breaking: dict[str, Any]
    selected: tuple[SelectedCandidate, ...]
    resolved_selector = f"candidate-id:{candidate_id}" if candidate_id else str(selector)
    if candidate_id is not None:
        individual_path = run_dir / "candidates" / candidate_id / "individual.json"
        try:
            record = json.loads(individual_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Explicit candidate artifact is unavailable: {individual_path}") from exc
        selected = (_load_selected_candidate(run_dir, record),)
        tie_breaking = {"explicit_candidate": candidate_id, "tie_break_required": False}
    else:
        valid_final = tuple(
            _load_selected_candidate(run_dir, item)
            for item in final_candidates.values()
            if item.get("status") == "evaluated"
        )
        if not valid_final:
            raise ValueError("Final population contains no valid evaluated candidate.")
        if selector == "best-game-performance":
            ordered = sorted(
                valid_final,
                key=lambda item: (
                    -item.evolution_game_performance,
                    -item.evolution_code_quality,
                    item.candidate_id,
                ),
            )
            selected = (ordered[0],)
            tie_breaking = {
                "ordering": [
                    "game_performance descending",
                    "code_quality descending",
                    "candidate_id ascending",
                ],
                "ordered_candidate_ids": [item.candidate_id for item in ordered],
            }
        elif selector in {"balanced", "pareto"}:
            first_front = summary["pareto_fronts"][0] if summary["pareto_fronts"] else []
            front = tuple(
                _load_selected_candidate(run_dir, final_candidates[str(candidate)])
                for candidate in first_front
                if str(candidate) in final_candidates
                and final_candidates[str(candidate)].get("status") == "evaluated"
            )
            if not front:
                raise ValueError("Final Pareto front contains no valid evaluated candidate.")
            if selector == "pareto":
                selected = tuple(sorted(front, key=lambda item: item.candidate_id))
                tie_breaking = {
                    "ordering": "candidate_id ascending",
                    "source_front": [str(value) for value in first_front],
                }
            else:
                selected, tie_breaking = _balanced_selection(front)
        else:
            raise ValueError(f"Unknown final-test selector: {selector}")
    return SelectionDecision(
        run_id=run_dir.name,
        selector=resolved_selector,
        candidates=selected,
        tie_breaking=tie_breaking,
        selected_at=selected_at or datetime.now(timezone.utc).isoformat(),
        git_commit=git_commit if git_commit is not None else _git_commit(run_dir),
    )


def _load_selected_candidate(run_dir: Path, record: dict[str, Any]) -> SelectedCandidate:
    candidate_id = str(record.get("candidate_id") or record.get("id") or "").strip()
    if not candidate_id:
        raise ValueError("Candidate record has no ID.")
    if record.get("status") != "evaluated":
        raise ValueError(f"Candidate {candidate_id} is not a valid evaluated candidate.")
    objectives = record.get("fitness_objectives") or record.get("objectives")
    if not isinstance(objectives, dict):
        raise ValueError(f"Candidate {candidate_id} has no evolution objectives.")
    try:
        game = float(objectives["game_performance"])
        quality = float(objectives["code_quality"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Candidate {candidate_id} has invalid evolution objectives.") from exc
    if not math.isfinite(game) or not math.isfinite(quality):
        raise ValueError(f"Candidate {candidate_id} has non-finite evolution objectives.")
    candidate_dir = run_dir / "candidates" / candidate_id
    source_path = candidate_dir / "generation" / "normalized_candidate.java"
    individual_path = candidate_dir / "individual.json"
    if not source_path.is_file() or not individual_path.is_file():
        raise ValueError(f"Candidate {candidate_id} lacks canonical final Java or individual artifacts.")
    source = source_path.read_text(encoding="utf-8")
    embedded = str(record.get("generated_java") or "")
    if embedded and embedded != source:
        raise ValueError(f"Candidate {candidate_id} source does not match its canonical artifact.")
    return SelectedCandidate(
        candidate_id=candidate_id,
        generation=int(record.get("generation", 0)),
        evolution_game_performance=game,
        evolution_code_quality=quality,
        source_path=source_path,
        individual_path=individual_path,
    )


def _balanced_selection(
    front: tuple[SelectedCandidate, ...],
) -> tuple[tuple[SelectedCandidate, ...], dict[str, Any]]:
    games = [item.evolution_game_performance for item in front]
    qualities = [item.evolution_code_quality for item in front]
    game_min, game_max = min(games), max(games)
    quality_min, quality_max = min(qualities), max(qualities)

    def normalized(value: float, minimum: float, maximum: float) -> float:
        return 1.0 if maximum == minimum else (value - minimum) / (maximum - minimum)

    distances = {
        item.candidate_id: math.sqrt(
            (1.0 - normalized(item.evolution_game_performance, game_min, game_max)) ** 2
            + (1.0 - normalized(item.evolution_code_quality, quality_min, quality_max)) ** 2
        )
        for item in front
    }
    ordered = sorted(
        front,
        key=lambda item: (
            distances[item.candidate_id],
            -item.evolution_game_performance,
            -item.evolution_code_quality,
            item.candidate_id,
        ),
    )
    return (ordered[0],), {
        "formula": (
            "unweighted Euclidean distance to normalized ideal point (1,1) over "
            "game_performance and code_quality"
        ),
        "weights": {"game_performance": 1.0, "code_quality": 1.0},
        "normalization_ranges": {
            "game_performance": [game_min, game_max],
            "code_quality": [quality_min, quality_max],
        },
        "ideal_point": [1.0, 1.0],
        "distances": distances,
        "tie_break_order": [
            "ideal_point_distance ascending",
            "game_performance descending",
            "code_quality descending",
            "candidate_id ascending",
        ],
    }


def _git_commit(run_dir: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=run_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    value = completed.stdout.strip()
    return value or None

