"""Read-only controller for run and candidate inspection."""

from pathlib import Path

from eagle.analysis.records import CandidateArtifacts, CandidateRecord, RunSummary, discover_runs, load_candidate, load_candidate_records


class ArtifactController:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir

    def runs(self) -> list[RunSummary]:
        return discover_runs(self.runs_dir)

    def candidates(self, run_dir: Path) -> list[CandidateRecord]:
        return load_candidate_records(run_dir)

    def candidate(self, run_dir: Path, candidate_id: str) -> CandidateArtifacts:
        return load_candidate(run_dir, candidate_id)
