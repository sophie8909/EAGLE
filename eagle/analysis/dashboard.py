"""Canonical, single-pass analysis data loading for the GUI.

The loader is deliberately framework-level: application evaluators contribute
named metrics through the existing candidate records, but are not required by
this module.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any

import pandas as pd

from .errors import normalize_failure_category
from .objectives import available_objectives, generation_statistics, load_objective_directions, pareto_frame, prepare_objective_frame
from .records import ArtifactReadError, CandidateRecord, RunSummary, discover_runs, load_candidate_records
from .timing import summarize_run_timing


FAILURE_SENTINELS = {-1000.0}


@dataclass(frozen=True)
class AnalysisViewModel:
    """All data needed to render an Analysis page without file reads in views."""

    selected_path: Path
    run_dir: Path
    run_kind: str
    run_options: tuple[RunSummary, ...]
    frame: pd.DataFrame
    directions: dict[str, str]
    overview: dict[str, Any]
    evolution: dict[str, Any]
    pareto: dict[str, Any]
    distributions: dict[str, Any]
    operators: dict[str, Any]
    timing: dict[str, Any]
    errors: dict[str, Any]
    candidates: list[dict[str, Any]]
    evaluation: dict[str, Any]
    configuration: dict[str, Any]
    available_artifacts: dict[str, bool]
    warnings: tuple[str, ...] = ()


class AnalysisDataLoader:
    """Detect and parse one run/experiment folder into one normalized model."""

    def load(self, selected_path: Path) -> AnalysisViewModel:
        selected_path = Path(selected_path).expanduser().resolve()
        if not selected_path.is_dir():
            raise ArtifactReadError(f"Analysis folder does not exist: {selected_path}")
        run_dir, run_kind, run_options = self._resolve_run(selected_path)
        records = load_candidate_records(run_dir)
        frame = prepare_objective_frame(records)
        directions = load_objective_directions(run_dir)
        config = self._read_json(run_dir / "resolved_config.json") or {}
        summary = self._read_json(run_dir / "summary.json") or {}
        timing = self._timing(summarize_run_timing(run_dir))
        warnings: list[str] = []
        if not records:
            warnings.append("No candidate records are available yet.")
        if not timing["generations"] and not timing["llm_requests"]:
            warnings.append("Timing data unavailable: timing.jsonl and candidate timing artifacts were not found.")
        errors = self._errors(records, run_dir)
        if not errors["rows"]:
            warnings.append("Error data unavailable: no recorded failures were found.")
        objectives = available_objectives(frame)
        evolution = self._evolution(frame, objectives)
        pareto = self._pareto(frame, objectives, directions)
        distributions = self._distributions(frame, objectives)
        operators = self._operators(records, frame)
        candidates = self._candidates(frame, records, pareto["pareto_ids"])
        evaluation = self._evaluation(records)
        available = self._artifact_inventory(run_dir)
        return AnalysisViewModel(
            selected_path=selected_path,
            run_dir=run_dir,
            run_kind=run_kind,
            run_options=tuple(run_options),
            frame=frame,
            directions=directions,
            overview=self._overview(run_dir, config, summary, records, timing, objectives),
            evolution=evolution,
            pareto=pareto,
            distributions=distributions,
            operators=operators,
            timing=timing,
            errors=errors,
            candidates=candidates,
            evaluation=evaluation,
            configuration=config,
            available_artifacts=available,
            warnings=tuple(warnings),
        )

    def discover_sources(self, root: Path) -> list[RunSummary]:
        """Return direct run sources; experiment folders are represented by their newest run."""
        root = Path(root)
        if not root.is_dir():
            return []
        sources: list[RunSummary] = []
        for path in sorted(root.iterdir()):
            if not path.is_dir():
                continue
            if self._is_canonical(path):
                sources.append(self._summary(path))
                continue
            children = [child for child in path.iterdir() if child.is_dir() and self._is_canonical(child)]
            if children:
                chosen = max(children, key=lambda item: item.stat().st_mtime)
                item = self._summary(chosen)
                sources.append(RunSummary(run_id=f"{path.name} / {item.run_id}", path=path, start_time=item.start_time, status="experiment", generation_count=item.generation_count, candidate_count=item.candidate_count, success_count=item.success_count, failure_count=item.failure_count))
        return sorted(sources, key=lambda item: (item.start_time, item.run_id), reverse=True)

    def _resolve_run(self, path: Path) -> tuple[Path, str, list[RunSummary]]:
        if self._is_canonical(path):
            return path, "run", [self._summary(path)]
        children = [child for child in path.iterdir() if child.is_dir() and self._is_canonical(child)]
        if not children:
            raise ArtifactReadError(f"Unsupported analysis folder: {path}")
        summaries = [self._summary(child) for child in children]
        valid = [item for item in summaries if item.status != "unreadable"]
        if not valid:
            raise ArtifactReadError(f"No readable EAGLE runs found in experiment folder: {path}")
        chosen = max(valid, key=lambda item: (item.path.stat().st_mtime, item.run_id))
        return chosen.path, "experiment", sorted(summaries, key=lambda item: (item.start_time, item.run_id), reverse=True)

    @staticmethod
    def _is_canonical(path: Path) -> bool:
        return any((path / name).exists() for name in ("results.jsonl", "summary.json", "resolved_config.json", "candidates"))

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    def _summary(self, path: Path) -> RunSummary:
        for item in discover_runs(path.parent):
            if item.path == path:
                return item
        raise ArtifactReadError(f"Cannot summarize run folder: {path}")

    @staticmethod
    def _timing(summary: dict[str, Any]) -> dict[str, Any]:
        records = [item for item in summary.get("operation_records", []) if isinstance(item.get("duration_seconds"), (int, float))]
        requests = [item for item in summary.get("llm_requests", []) if isinstance(item.get("duration_seconds"), (int, float))]
        def stats(items: list[dict[str, Any]]) -> dict[str, Any]:
            values = sorted(float(item["duration_seconds"]) for item in items)
            if not values:
                return {"count": 0, "total": 0.0, "mean": None, "median": None, "p95": None, "maximum": None}
            index = min(len(values) - 1, max(0, int((len(values) * 0.95) - 1)))
            return {"count": len(values), "total": sum(values), "mean": sum(values) / len(values), "median": median(values), "p95": values[index], "maximum": max(values)}
        summary = dict(summary)
        summary["operation_statistics"] = stats(records)
        summary["request_statistics"] = stats(requests)
        by_role: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        by_model: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in summary.get("llm_requests", []):
            by_role[str(item.get("operation_stage") or "unknown")].append(item)
            by_model[str(item.get("model_id") or "unknown")].append(item)
        summary["timing_by_role"] = {key: stats(value) for key, value in by_role.items()}
        summary["timing_by_model"] = {key: stats(value) for key, value in by_model.items()}
        return summary
    def _overview(self, run_dir: Path, config: dict[str, Any], summary: dict[str, Any], records: list[CandidateRecord], timing: dict[str, Any], objectives: list[str]) -> dict[str, Any]:
        failed = sum(self._failed(record) for record in records)
        values = {"run_id": run_dir.name, "status": "complete" if (run_dir / "summary.json").exists() else "running" if records else "incomplete", "algorithm": config.get("algorithm"), "application": config.get("application") or config.get("evaluator"), "random_seed": config.get("random_seed"), "start_time": config.get("started_at") or config.get("start_time"), "end_time": config.get("finished_at") or config.get("end_time"), "total_duration_seconds": timing.get("total_run_duration_seconds"), "completed_generations": len({record.generation for record in records}), "configured_generations": config.get("generation_count") or config.get("generations"), "population_size": config.get("population_size"), "number_of_objectives": len(objectives), "objective_names": objectives, "total_candidate_evaluations": len(records), "successful_evaluations": len(records) - failed, "failed_evaluations": failed, "failure_rate": failed / len(records) if records else None, "total_llm_requests": len(timing.get("llm_requests", [])), "total_token_usage": self._token_total(timing.get("llm_requests", []))}
        values.update({"summary": summary})
        return values

    @staticmethod
    def _token_total(requests: list[dict[str, Any]]) -> int | None:
        totals = []
        for item in requests:
            counts = item.get("token_counts")
            if not isinstance(counts, dict):
                continue
            total = counts.get("total_tokens")
            if total is None:
                total = int(counts.get("prompt_tokens", 0) or 0) + int(counts.get("completion_tokens", 0) or 0)
            totals.append(int(total))
        return sum(totals) if totals else None

    def _evolution(self, frame: pd.DataFrame, objectives: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {"objectives": {}, "population": [], "failure_rate": [], "pareto_front_size": []}
        for objective in objectives:
            stats = generation_statistics(frame, objective)
            result["objectives"][objective] = stats.to_dict(orient="records")
        if not frame.empty:
            for generation, group in frame.groupby("generation", sort=True):
                result["population"].append({"generation": int(generation), "count": int(len(group)), "valid_count": int((~group["failed"].astype(bool)).sum())})
                result["failure_rate"].append({"generation": int(generation), "rate": float(group["failed"].astype(bool).mean())})
        return result

    def _pareto(self, frame: pd.DataFrame, objectives: list[str], directions: dict[str, str]) -> dict[str, Any]:
        if len(objectives) < 2 or frame.empty:
            return {"available": False, "pareto_ids": set(), "rows": [], "front_size": None, "dominated_count": None}
        selected = tuple(objectives[:2])
        front = pareto_frame(frame, selected, directions)
        final_generation = int(frame["generation"].max())
        final = frame[frame["generation"] == final_generation].copy()
        final_front = pareto_frame(final, selected, directions)
        ids = set(final_front["candidate_id"].astype(str))
        return {"available": True, "x": selected[0], "y": selected[1], "pareto_ids": ids, "rows": final.to_dict(orient="records"), "front_size": len(ids), "dominated_count": max(0, len(final) - len(ids)), "all_front_size": len(front)}

    def _distributions(self, frame: pd.DataFrame, objectives: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for objective in objectives:
            values = [float(value) for _, row in frame.iterrows() if not bool(row["failed"]) and (value := row.get(objective)) is not None and pd.notna(value) and float(value) not in FAILURE_SENTINELS]
            result[objective] = {"values": values, "min": min(values) if values else None, "max": max(values) if values else None, "mean": mean(values) if values else None, "median": median(values) if values else None, "stddev": stdev(values) if len(values) > 1 else None, "valid_count": len(values), "failed_count": int(frame["failed"].astype(bool).sum()) if not frame.empty else 0}
        return result

    def _operators(self, records: list[CandidateRecord], frame: pd.DataFrame) -> dict[str, Any]:
        result: dict[str, Any] = {}
        total = len(records)
        for operator, group in frame.groupby("operator", sort=True) if not frame.empty else ():
            failed = int(group["failed"].astype(bool).sum())
            result[str(operator)] = {"usage_count": len(group), "usage_share": len(group) / total if total else 0.0, "successful_offspring": len(group) - failed, "success_rate": (len(group) - failed) / len(group) if len(group) else 0.0, "failure_rate": failed / len(group) if len(group) else 0.0}
        return result

    def _candidates(self, frame: pd.DataFrame, records: list[CandidateRecord], pareto_ids: set[str]) -> list[dict[str, Any]]:
        lookup = {record.candidate_id: record for record in records}
        rows = []
        for row in frame.to_dict(orient="records"):
            record = lookup[str(row["candidate_id"])]
            rows.append({**row, "parent_ids": ", ".join(record.parent_ids), "pareto": record.candidate_id in pareto_ids, "evaluation_status": record.status})
        return rows

    def _errors(self, records: list[CandidateRecord], run_dir: Path) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for record in records:
            if not self._failed(record):
                continue
            category = normalize_failure_category(record.failure_category, record.failure_reason, record.failure_stage)
            rows.append({"candidate_id": record.candidate_id, "generation": record.generation, "operator": record.operator, "stage": record.failure_stage or "unknown", "category": category, "message": record.failure_reason or category, "artifact_path": str(run_dir / "candidates" / record.candidate_id), "details": record.raw})
        by_category = Counter(row["category"] for row in rows)
        by_stage = Counter(row["stage"] for row in rows)
        by_generation = Counter(row["generation"] for row in rows)
        return {"rows": rows, "total": len(rows), "by_category": dict(by_category), "by_stage": dict(by_stage), "by_generation": dict(by_generation)}

    @staticmethod
    def _failed(record: CandidateRecord) -> bool:
        return record.status == "failed" or bool(record.failure_reason) or any(float(value) in FAILURE_SENTINELS for value in record.objectives.values())

    @staticmethod
    def _evaluation(records: list[CandidateRecord]) -> dict[str, Any]:
        return {"available": any(record.raw.get("game_metrics") or record.raw.get("game_eval_result") for record in records), "metrics": {}}

    @staticmethod
    def _artifact_inventory(run_dir: Path) -> dict[str, bool]:
        return {name: (run_dir / relative).exists() for name, relative in {"results": "results.jsonl", "summary": "summary.json", "resolved_config": "resolved_config.json", "timing": "timing.jsonl", "llm_requests": "llm_requests", "final_tests": "final_tests"}.items()}
