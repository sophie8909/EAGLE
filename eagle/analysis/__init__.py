"""Read-only analysis services shared by CLI tools and the GUI."""

from .dashboard import AnalysisDataLoader, AnalysisViewModel
from .records import CandidateArtifacts, CandidateRecord, RunSummary, discover_runs, load_candidate, load_candidate_records

__all__ = [
    "AnalysisDataLoader",
    "AnalysisViewModel",
    "CandidateArtifacts",
    "CandidateRecord",
    "RunSummary",
    "discover_runs",
    "load_candidate",
    "load_candidate_records",
]