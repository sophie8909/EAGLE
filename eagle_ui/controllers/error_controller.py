"""Error-analysis controller using shared normalization."""

from pathlib import Path

from eagle.analysis.errors import error_summary, error_trend, export_error_frame, filter_error_frame, load_error_frame, root_cause_groups
from eagle.analysis.records import load_candidate_records


class ErrorAnalysisController:
    def load(self, run_dir: Path):
        records = load_candidate_records(run_dir)
        frame = load_error_frame(run_dir)
        counts: dict[int, int] = {}
        for record in records:
            counts[record.generation] = counts.get(record.generation, 0) + 1
        return frame, len(records), counts

    filter = staticmethod(filter_error_frame)
    summary = staticmethod(error_summary)
    trend = staticmethod(error_trend)
    root_causes = staticmethod(root_cause_groups)
    export = staticmethod(export_error_frame)
