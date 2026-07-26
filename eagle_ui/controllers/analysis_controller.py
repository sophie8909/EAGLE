"""Objective and persisted timing analysis controller."""

from pathlib import Path

from eagle.analysis.objectives import available_objectives, generation_statistics, load_objective_directions, pareto_frame, prepare_objective_frame
from eagle.analysis.plots import generation_distribution_options, objective_scatter_options
from eagle.analysis.records import load_candidate_records
from eagle.analysis.timing import plot_payloads, summarize_run_timing


class AnalysisController:
    def load_run(self, run_dir: Path) -> tuple:
        frame = self.load(run_dir)
        directions = self.directions(run_dir)
        timing = self.timing(run_dir)
        return frame, directions, timing, plot_payloads(timing)

    def load(self, run_dir: Path):
        return prepare_objective_frame(load_candidate_records(run_dir))


    def objectives(self, frame) -> list[str]:
        return available_objectives(frame)

    def directions(self, run_dir: Path) -> dict[str, str]:
        return load_objective_directions(run_dir)

    def pareto(self, frame, objectives: tuple[str, ...], directions: dict[str, str]):
        return pareto_frame(frame, objectives, directions)

    def statistics(self, frame, objective: str):
        return generation_statistics(frame, objective)

    def distribution_plot(self, frame, objective: str) -> dict:
        return generation_distribution_options(frame, objective)

    def scatter_plot(self, frame, x_objective: str, y_objective: str, pareto_ids: set[str]) -> dict:
        return objective_scatter_options(frame, x_objective, y_objective, pareto_ids=pareto_ids)

    def timing(self, run_dir: Path) -> dict:
        return summarize_run_timing(run_dir)

    def timing_plots(self, run_dir: Path) -> dict[str, dict]:
        return plot_payloads(self.timing(run_dir))