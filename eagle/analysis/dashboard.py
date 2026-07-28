"""Single-pass, framework-level analysis loading for the EAGLE GUI."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Iterable

import pandas as pd

from .errors import normalize_failure_category
from .final_tests import load_final_test_summaries
from .objectives import (
    ANALYSIS_METRIC_DIRECTIONS,
    pareto_frame,
    prepare_objective_frame,
)
from .records import (
    CANDIDATE_ARTIFACT_PATHS,
    ArtifactReadError,
    CandidateRecord,
    RunSummary,
    discover_runs,
    load_candidate_records,
)
from .timing import summarize_run_timing


FAILURE_SENTINELS = {-1000.0}
SUPPORTED_ARTIFACT_SCHEMA_VERSIONS = {"phase4-v1"}
RUN_MARKERS = (
    "results.jsonl",
    "summary.json",
    "resolved_config.json",
    "candidates",
)


@dataclass(frozen=True)
class AnalysisViewModel:
    """Everything the Analysis page needs after one load."""

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
    candidate_details: dict[str, dict[str, Any]]
    evaluation: dict[str, Any]
    configuration: dict[str, Any]
    available_artifacts: dict[str, bool]
    section_warnings: dict[str, tuple[str, ...]]
    warnings: tuple[str, ...] = ()


class AnalysisDataLoader:
    """Detect one run/experiment folder and normalize all available evidence."""

    def load(self, selected_path: Path) -> AnalysisViewModel:
        selected_path = Path(selected_path).expanduser().resolve()
        if not selected_path.is_dir():
            raise ArtifactReadError(f"Analysis folder does not exist: {selected_path}")

        run_dir, run_kind, run_options = self._resolve_run(selected_path)
        section_warnings: defaultdict[str, list[str]] = defaultdict(list)
        config = self._read_optional_json(
            run_dir / "resolved_config.json", "configuration", section_warnings
        )
        schema_version = config.get("artifact_schema_version")
        if (
            schema_version is not None
            and schema_version not in SUPPORTED_ARTIFACT_SCHEMA_VERSIONS
        ):
            raise ArtifactReadError(
                f"Unsupported artifact schema {schema_version!r} in "
                f"{run_dir / 'resolved_config.json'}"
            )
        records = load_candidate_records(run_dir)
        if not records:
            section_warnings["candidates"].append(
                "No candidate records are available yet."
            )
        summary = self._read_optional_json(
            run_dir / "summary.json", "overview", section_warnings
        )
        prompt_snapshot = self._read_optional_json(
            run_dir / "prompt_snapshot.json", "configuration", section_warnings
        )
        directions = self._directions(config, section_warnings)
        objective_names = self._objective_names(records, summary)
        for objective in objective_names:
            if objective not in directions:
                section_warnings["objectives"].append(
                    f"Direction is not recorded for objective {objective!r}; "
                    "direction-dependent ranking is unavailable."
                )

        frame = prepare_objective_frame(records)
        timing = self._timing(run_dir, section_warnings)
        final_records = self._final_population(
            run_dir, summary, records, section_warnings
        )
        final_frame = prepare_objective_frame(final_records)
        evolution = self._evolution(frame, objective_names, directions)
        pareto = self._pareto(
            final_frame, objective_names, directions, summary, section_warnings
        )
        distributions = self._distributions(
            final_frame, objective_names, records
        )
        operators = self._operators(records, objective_names)
        errors = self._errors(records, run_dir)
        candidate_rows = self._candidates(frame, records, pareto["pareto_ids"])
        candidate_details = self._candidate_details(records, run_dir)
        try:
            final_tests = load_final_test_summaries(run_dir)
        except (OSError, ValueError) as exc:
            section_warnings["evaluation"].append(
                f"Cannot parse final-test summaries: {exc}"
            )
            final_tests = []
        evaluation = self._evaluation(records, final_tests)

        self._record_absence_warnings(
            objective_names,
            pareto,
            operators,
            timing,
            errors,
            evaluation,
            section_warnings,
        )
        warnings = tuple(
            warning
            for section in section_warnings.values()
            for warning in section
        )
        return AnalysisViewModel(
            selected_path=selected_path,
            run_dir=run_dir,
            run_kind=run_kind,
            run_options=tuple(run_options),
            frame=frame,
            directions=directions,
            overview=self._overview(
                run_dir,
                config,
                summary,
                records,
                timing,
                objective_names,
            ),
            evolution=evolution,
            pareto=pareto,
            distributions=distributions,
            operators=operators,
            timing=timing,
            errors=errors,
            candidates=candidate_rows,
            candidate_details=candidate_details,
            evaluation=evaluation,
            configuration={
                "resolved_config": config,
                "run_summary": summary,
                "prompt_snapshot": prompt_snapshot,
            },
            available_artifacts=self._artifact_inventory(run_dir),
            section_warnings={
                name: tuple(values) for name, values in section_warnings.items()
            },
            warnings=warnings,
        )

    def discover_sources(self, root: Path) -> list[RunSummary]:
        """Discover only direct run or experiment children of ``root``."""

        root = Path(root)
        if not root.is_dir():
            return []
        sources: list[RunSummary] = []
        direct = {item.path: item for item in discover_runs(root)}
        for path in sorted(root.iterdir()):
            if not path.is_dir():
                continue
            if self._is_canonical(path):
                sources.append(direct.get(path) or self._lightweight_summary(path))
                continue
            children = [
                child
                for child in path.iterdir()
                if child.is_dir() and self._is_canonical(child)
            ]
            if not children:
                continue
            chosen = max(children, key=lambda item: (item.stat().st_mtime, item.name))
            nested = {item.path: item for item in discover_runs(path)}
            item = nested.get(chosen) or self._lightweight_summary(chosen)
            sources.append(
                RunSummary(
                    run_id=f"{path.name} / {item.run_id}",
                    path=path,
                    start_time=item.start_time,
                    status="experiment",
                    generation_count=item.generation_count,
                    candidate_count=item.candidate_count,
                    success_count=item.success_count,
                    failure_count=item.failure_count,
                )
            )
        return sorted(
            sources, key=lambda item: (item.start_time, item.run_id), reverse=True
        )

    def _resolve_run(self, path: Path) -> tuple[Path, str, list[RunSummary]]:
        if self._is_canonical(path):
            return path, "run", [self._lightweight_summary(path)]
        children = [
            child
            for child in path.iterdir()
            if child.is_dir() and self._is_canonical(child)
        ]
        if not children:
            raise ArtifactReadError(f"Unsupported analysis folder: {path}")
        summaries = [self._lightweight_summary(child) for child in children]
        valid = [
            item for item in summaries if self._appears_readable(item.path)
        ]
        if not valid:
            raise ArtifactReadError(
                f"No readable EAGLE runs found in experiment folder: {path}"
            )
        chosen = max(
            valid, key=lambda item: (item.path.stat().st_mtime, item.run_id)
        )
        ordered = sorted(
            summaries,
            key=lambda item: (item.path.stat().st_mtime, item.run_id),
            reverse=True,
        )
        return chosen.path, "experiment", ordered

    @staticmethod
    def _lightweight_summary(path: Path) -> RunSummary:
        candidate_count = (
            sum(1 for item in (path / "candidates").iterdir() if item.is_dir())
            if (path / "candidates").is_dir()
            else 0
        )
        generation_count = len(list(path.glob("generation_*_population.json")))
        try:
            start_time = datetime.strptime(
                path.name[:15], "%Y%m%d_%H%M%S"
            ).isoformat()
        except ValueError:
            start_time = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        return RunSummary(
            run_id=path.name,
            path=path,
            start_time=start_time,
            status=(
                "complete"
                if (path / "summary.json").is_file()
                else "running"
                if candidate_count or (path / "results.jsonl").is_file()
                else "incomplete"
            ),
            generation_count=generation_count,
            candidate_count=candidate_count,
            success_count=0,
            failure_count=0,
        )

    @staticmethod
    def _appears_readable(path: Path) -> bool:
        for name in ("resolved_config.json", "summary.json"):
            artifact = path / name
            if artifact.is_file():
                try:
                    json.loads(artifact.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return False
        individuals = sorted((path / "candidates").glob("*/individual.json"))
        if individuals:
            try:
                payload = json.loads(individuals[0].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            return isinstance(payload, dict)
        results = path / "results.jsonl"
        if not results.is_file() or results.stat().st_size == 0:
            return True
        # Small streams are cheap enough to validate during experiment
        # detection; large streams are accepted by marker and later use the
        # bounded canonical candidate-summary path.
        if results.stat().st_size <= 10 * 1024 * 1024:
            try:
                load_candidate_records(path)
            except (OSError, TypeError, ValueError):
                return False
        return True

    @staticmethod
    def _is_canonical(path: Path) -> bool:
        return any((path / marker).exists() for marker in RUN_MARKERS)

    @staticmethod
    def _read_optional_json(
        path: Path,
        section: str,
        warnings: defaultdict[str, list[str]],
    ) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings[section].append(f"Cannot parse {path.name}: {exc}")
            return {}
        if not isinstance(payload, dict):
            warnings[section].append(f"{path.name} is not a JSON object.")
            return {}
        return payload

    @staticmethod
    def _directions(
        config: dict[str, Any],
        warnings: defaultdict[str, list[str]],
    ) -> dict[str, str]:
        result = dict(ANALYSIS_METRIC_DIRECTIONS)
        raw = config.get("objective_directions")
        if not isinstance(raw, dict):
            return result
        for name, value in raw.items():
            direction = str(value)
            if direction not in {"maximize", "minimize"}:
                warnings["objectives"].append(
                    f"Unsupported direction {value!r} for objective {name!r}."
                )
                continue
            result[str(name)] = direction
        return result

    @staticmethod
    def _objective_names(
        records: Iterable[CandidateRecord], summary: dict[str, Any]
    ) -> list[str]:
        names: list[str] = []
        summary_names = summary.get("objectives")
        if isinstance(summary_names, list):
            names.extend(str(item) for item in summary_names if str(item))
        for record in records:
            for name in record.objectives:
                if name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _timing(
        run_dir: Path, warnings: defaultdict[str, list[str]]
    ) -> dict[str, Any]:
        try:
            result = summarize_run_timing(run_dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings["timing"].append(f"Cannot parse timing artifacts: {exc}")
            result = {
                "run_id": run_dir.name,
                "total_run_duration_seconds": None,
                "generations": [],
                "operation_totals": {},
                "operation_records": [],
                "llm_requests": [],
                "slowest_requests": [],
            }
        warnings["timing"].extend(str(item) for item in result.get("warnings", []))
        return AnalysisDataLoader._with_timing_statistics(result)

    @staticmethod
    def _with_timing_statistics(summary: dict[str, Any]) -> dict[str, Any]:
        result = dict(summary)
        operations = [
            item
            for item in result.get("operation_records", [])
            if _number(item.get("duration_seconds")) is not None
        ]
        requests = [
            item
            for item in result.get("llm_requests", [])
            if _number(item.get("duration_seconds")) is not None
        ]
        result["operation_statistics"] = _duration_statistics(operations)
        result["request_statistics"] = _duration_statistics(requests)
        result["operation_groups"] = _group_duration(operations, "operation")
        result["timing_by_role"] = _group_duration(requests, "operation_stage")
        result["timing_by_model"] = _group_duration(requests, "model_id")
        result["timing_by_endpoint"] = _group_duration(
            requests, "server_or_endpoint"
        )
        total = _number(result.get("total_run_duration_seconds"))
        for group in result["operation_groups"].values():
            group["run_time_percent"] = (
                100.0 * group["total"] / total if total and total > 0 else None
            )
        result["slowest_operations"] = sorted(
            operations,
            key=lambda item: _number(item.get("duration_seconds")) or 0.0,
            reverse=True,
        )[:20]
        result["slowest_requests"] = sorted(
            requests,
            key=lambda item: _number(item.get("duration_seconds")) or 0.0,
            reverse=True,
        )[:20]
        return result

    def _final_population(
        self,
        run_dir: Path,
        summary: dict[str, Any],
        records: list[CandidateRecord],
        warnings: defaultdict[str, list[str]],
    ) -> list[CandidateRecord]:
        payload = summary.get("final_population")
        if isinstance(payload, list):
            parsed = self._records_from_payloads(payload, run_dir / "summary.json")
            if parsed:
                return parsed

        manifests = sorted(run_dir.glob("generation_*_population.json"))
        if manifests:
            path = manifests[-1]
            try:
                values = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(values, list):
                    parsed = self._records_from_payloads(values, path)
                    if parsed:
                        return parsed
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                warnings["objectives"].append(
                    f"Cannot parse final population manifest {path.name}: {exc}"
                )
        if not records:
            return []
        warnings["objectives"].append(
            "A persisted final population was not found; using all evaluated "
            "candidates as a partial-run fallback."
        )
        return list(records)

    @staticmethod
    def _records_from_payloads(
        payloads: list[Any], source: Path
    ) -> list[CandidateRecord]:
        records: list[CandidateRecord] = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            candidate_id = str(
                payload.get("candidate_id") or payload.get("id") or ""
            ).strip()
            if not candidate_id:
                continue
            objectives = payload.get("fitness_objectives") or payload.get(
                "objectives"
            )
            objectives = objectives if isinstance(objectives, dict) else {}
            metadata = (
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            )
            records.append(
                CandidateRecord(
                    candidate_id=candidate_id,
                    generation=int(payload.get("generation", 0)),
                    parent_ids=tuple(
                        str(item) for item in payload.get("parent_ids", [])
                    ),
                    operator=str(payload.get("operator") or "unknown"),
                    mutation_type=(
                        str(payload["mutation_type"])
                        if payload.get("mutation_type") is not None
                        else None
                    ),
                    status=str(payload.get("status") or "unknown"),
                    objectives={
                        str(key): float(value)
                        for key, value in objectives.items()
                        if _number(value) is not None
                    },
                    failure_category=_text(
                        payload.get("failure_category")
                        or metadata.get("failure_category")
                    ),
                    failure_stage=_text(
                        payload.get("failure_stage")
                        or metadata.get("failure_stage")
                    ),
                    failure_reason=_text(
                        payload.get("failure_reason")
                        or metadata.get("failure_reason")
                    ),
                    strategy_prompt=str(payload.get("strategy_prompt") or ""),
                    generation_prompt=str(
                        payload.get("generation_prompt") or ""
                    ),
                    generated_java=str(payload.get("generated_java") or ""),
                    raw={**payload, "_source": str(source)},
                )
            )
        return records

    def _overview(
        self,
        run_dir: Path,
        config: dict[str, Any],
        summary: dict[str, Any],
        records: list[CandidateRecord],
        timing: dict[str, Any],
        objectives: list[str],
    ) -> dict[str, Any]:
        failed = sum(self._failed(record) for record in records)
        generations = sorted({record.generation for record in records})
        timing_generations = timing.get("generations", [])
        start_time = (
            config.get("started_at")
            or config.get("start_time")
            or _first_timestamp(timing_generations, "started_at")
        )
        end_time = (
            config.get("finished_at")
            or config.get("end_time")
            or _last_timestamp(timing_generations, "finished_at")
        )
        return {
            "run_id": run_dir.name,
            "status": (
                "complete"
                if (run_dir / "summary.json").exists()
                else "running"
                if records
                else "incomplete"
            ),
            "algorithm": config.get("algorithm"),
            "application": config.get("application") or config.get("evaluator"),
            "random_seed": config.get("ea_random_seed")
            if "ea_random_seed" in config
            else config.get("random_seed"),
            "start_time": start_time,
            "end_time": end_time,
            "total_duration_seconds": timing.get("total_run_duration_seconds"),
            "completed_generations": len(generations),
            "configured_generations": config.get("generation_count")
            or config.get("generations"),
            "population_size": config.get("population_size"),
            "number_of_objectives": len(objectives),
            "objective_names": objectives,
            "total_candidate_evaluations": len(records),
            "successful_evaluations": len(records) - failed,
            "failed_evaluations": failed,
            "failure_rate": failed / len(records) if records else None,
            "total_llm_requests": len(timing.get("llm_requests", [])),
            "total_token_usage": self._token_total(
                timing.get("llm_requests", [])
            ),
            "artifact_schema_version": config.get("artifact_schema_version"),
            "git_commit": config.get("git_commit_hash"),
            "stop_reason": summary.get("stop_reason"),
        }

    @staticmethod
    def _token_total(requests: list[dict[str, Any]]) -> int | None:
        totals: list[int] = []
        for item in requests:
            counts = item.get("token_counts")
            if not isinstance(counts, dict):
                continue
            total = counts.get("total_tokens")
            if total is None:
                total = int(counts.get("prompt_tokens", 0) or 0) + int(
                    counts.get("completion_tokens", 0) or 0
                )
            totals.append(int(total))
        return sum(totals) if totals else None

    def _evolution(
        self,
        frame: pd.DataFrame,
        objectives: list[str],
        directions: dict[str, str],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "objectives": {},
            "population": [],
            "failure_rate": [],
            "pareto_front_size": [],
        }
        if frame.empty:
            return result
        for objective in objectives:
            rows: list[dict[str, Any]] = []
            if objective not in frame:
                result["objectives"][objective] = rows
                continue
            for generation, group in frame.groupby("generation", sort=True):
                valid = [
                    float(value)
                    for _, row in group.iterrows()
                    if not bool(row["failed"])
                    and (value := row.get(objective)) is not None
                    and pd.notna(value)
                    and float(value) not in FAILURE_SENTINELS
                ]
                direction = directions.get(objective)
                best = (
                    max(valid)
                    if valid and direction == "maximize"
                    else min(valid)
                    if valid and direction == "minimize"
                    else None
                )
                worst = (
                    min(valid)
                    if valid and direction == "maximize"
                    else max(valid)
                    if valid and direction == "minimize"
                    else None
                )
                rows.append(
                    {
                        "generation": int(generation),
                        "best": best,
                        "mean": mean(valid) if valid else None,
                        "median": median(valid) if valid else None,
                        "worst": worst,
                        "valid_count": len(valid),
                        "failure_count": int(
                            group["failed"].astype(bool).sum()
                        ),
                    }
                )
            result["objectives"][objective] = rows

        known = [
            objective for objective in objectives if objective in directions
        ]
        for generation, group in frame.groupby("generation", sort=True):
            failed = int(group["failed"].astype(bool).sum())
            valid_group = group.loc[~group["failed"].astype(bool)]
            front_size = None
            if len(known) >= 2 and not valid_group.empty:
                front_size = len(
                    pareto_frame(
                        valid_group,
                        tuple(known),
                        directions,
                    )
                )
            result["population"].append(
                {
                    "generation": int(generation),
                    "count": int(len(group)),
                    "valid_count": int(len(group) - failed),
                }
            )
            result["failure_rate"].append(
                {
                    "generation": int(generation),
                    "rate": failed / len(group) if len(group) else None,
                }
            )
            result["pareto_front_size"].append(
                {"generation": int(generation), "count": front_size}
            )
        return result

    def _pareto(
        self,
        final_frame: pd.DataFrame,
        objectives: list[str],
        directions: dict[str, str],
        summary: dict[str, Any],
        warnings: defaultdict[str, list[str]],
    ) -> dict[str, Any]:
        base = {
            "available": False,
            "objectives": objectives,
            "pareto_ids": set(),
            "rows": final_frame.to_dict(orient="records"),
            "front_size": None,
            "dominated_count": None,
            "hypervolume_history": self._hypervolume(summary),
        }
        if len(objectives) < 2 or final_frame.empty:
            return base
        missing = [name for name in objectives if name not in directions]
        if missing:
            warnings["objectives"].append(
                "Pareto analysis requires recorded directions for: "
                + ", ".join(missing)
            )
            return base
        usable = final_frame.loc[~final_frame["failed"].astype(bool)]
        front = pareto_frame(usable, tuple(objectives), directions)
        ids = set(front["candidate_id"].astype(str))
        return {
            **base,
            "available": True,
            "x": objectives[0],
            "y": objectives[1],
            "pareto_ids": ids,
            "front_size": len(ids),
            "dominated_count": max(0, len(usable) - len(ids)),
        }

    @staticmethod
    def _hypervolume(summary: dict[str, Any]) -> list[dict[str, Any]]:
        value = summary.get("hypervolume_history")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _distributions(
        self,
        final_frame: pd.DataFrame,
        objectives: list[str],
        all_records: list[CandidateRecord],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        total_failures = sum(self._failed(record) for record in all_records)
        for objective in objectives:
            values: list[float] = []
            missing = 0
            if objective in final_frame:
                for _, row in final_frame.iterrows():
                    value = _number(row.get(objective))
                    if (
                        bool(row.get("failed"))
                        or value is None
                        or value in FAILURE_SENTINELS
                    ):
                        missing += 1
                    else:
                        values.append(value)
            result[objective] = {
                "values": values,
                **_value_statistics(values),
                "valid_count": len(values),
                "failed_count": max(missing, total_failures if final_frame.empty else 0),
                "histogram": _histogram(values),
            }
        return result

    def _operators(
        self, records: list[CandidateRecord], objectives: list[str]
    ) -> dict[str, Any]:
        groups: defaultdict[str, list[CandidateRecord]] = defaultdict(list)
        for record in records:
            groups[record.operator or "unknown"].append(record)
        result: dict[str, Any] = {
            "statistics": {},
            "history": [],
            "mutation_vs_crossover": {},
        }
        total = len(records)
        for operator, values in sorted(groups.items()):
            failed = sum(self._failed(record) for record in values)
            improvements = [
                value
                for record in values
                for value in [
                    _first_numeric(
                        record.raw,
                        ("operator_reward", "reward", "improvement"),
                    )
                ]
                if value is not None
            ]
            result["statistics"][operator] = {
                "operator": operator,
                "usage_count": len(values),
                "usage_share": len(values) / total if total else 0.0,
                "successful_offspring": len(values) - failed,
                "success_rate": (len(values) - failed) / len(values),
                "failure_rate": failed / len(values),
                "mean_reward_or_improvement": (
                    mean(improvements) if improvements else None
                ),
                "offspring_validity_rate": (len(values) - failed) / len(values),
                "compilation_failure_rate": (
                    sum(record.failure_stage == "compilation" for record in values)
                    / len(values)
                ),
                "evaluation_failure_rate": (
                    sum(
                        record.failure_stage in {"runtime", "evaluation"}
                        for record in values
                    )
                    / len(values)
                ),
            }
            for record in values:
                reward = _first_numeric(
                    record.raw, ("operator_reward", "reward", "improvement")
                )
                probability = _first_numeric(
                    record.raw,
                    (
                        "operator_probability",
                        "selection_probability",
                        "selection_weight",
                    ),
                )
                if reward is not None or probability is not None:
                    result["history"].append(
                        {
                            "generation": record.generation,
                            "operator": operator,
                            "reward": reward,
                            "probability": probability,
                        }
                    )
        for kind in ("mutation", "crossover"):
            count = sum(
                kind in (record.operator or "").lower() for record in records
            )
            result["mutation_vs_crossover"][kind] = {
                "count": count,
                "share": count / total if total else 0.0,
            }
        return result

    def _errors(
        self, records: list[CandidateRecord], run_dir: Path
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        candidate_root = run_dir / "candidates"
        for record in records:
            if not self._failed(record):
                continue
            category = normalize_failure_category(
                record.failure_category,
                record.failure_reason,
                record.failure_stage,
            )
            raw = record.raw
            timestamp = _first_nested_value(
                raw,
                ("timestamp", "finished_at", "candidate_finished_at"),
            )
            rows.append(
                {
                    "candidate_id": record.candidate_id,
                    "generation": record.generation,
                    "operator": record.operator,
                    "stage": record.failure_stage or "unknown",
                    "category": category,
                    "message": _short_message(
                        record.failure_reason or category
                    ),
                    "artifact_path": str(
                        candidate_root / record.candidate_id
                    ),
                    "timestamp": timestamp,
                    "details": {
                        "failure_reason": record.failure_reason,
                        "failure_category": record.failure_category,
                        "failure_stage": record.failure_stage,
                        "recorded_evidence": raw,
                    },
                }
            )
        by_category = Counter(row["category"] for row in rows)
        by_stage = Counter(row["stage"] for row in rows)
        by_generation = Counter(row["generation"] for row in rows)
        by_operator = Counter(row["operator"] for row in rows)
        generation_totals = Counter(record.generation for record in records)
        operator_totals = Counter(record.operator for record in records)
        return {
            "rows": rows,
            "total": len(rows),
            "by_category": dict(by_category),
            "by_stage": dict(by_stage),
            "by_generation": dict(by_generation),
            "by_operator": dict(by_operator),
            "by_generation_failure_rate": {
                generation: count / generation_totals[generation]
                for generation, count in by_generation.items()
                if generation_totals[generation]
            },
            "by_operator_failure_rate": {
                operator: count / operator_totals[operator]
                for operator, count in by_operator.items()
                if operator_totals[operator]
            },
        }

    def _candidates(
        self,
        frame: pd.DataFrame,
        records: list[CandidateRecord],
        pareto_ids: set[str],
    ) -> list[dict[str, Any]]:
        lookup = {record.candidate_id: record for record in records}
        rows: list[dict[str, Any]] = []
        for row in frame.to_dict(orient="records"):
            record = lookup[str(row["candidate_id"])]
            metadata = (
                record.raw.get("metadata")
                if isinstance(record.raw.get("metadata"), dict)
                else {}
            )
            timing = (
                record.raw.get("timing")
                if isinstance(record.raw.get("timing"), dict)
                else {}
            )
            rows.append(
                {
                    **row,
                    "parent_ids": ", ".join(record.parent_ids),
                    "pareto": record.candidate_id in pareto_ids,
                    "rank": metadata.get("pareto_rank"),
                    "crowding_distance": metadata.get("crowding_distance"),
                    "evaluation_status": record.status,
                    "compilation_status": record.raw.get("compile_status"),
                    "validation_status": _nested_status(
                        record.raw, "validation_result"
                    ),
                    "token_usage": _candidate_token_usage(timing),
                    "generation_duration_seconds": _candidate_duration(timing),
                }
            )
        return rows

    @staticmethod
    def _candidate_details(
        records: list[CandidateRecord], run_dir: Path
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for record in records:
            candidate_dir = run_dir / "candidates" / record.candidate_id
            envelope = record.raw.get("_result_envelope")
            envelope = envelope if isinstance(envelope, dict) else {}
            raw_response = _first_nested_value(
                envelope,
                ("raw_llm_output", "raw_response"),
            )
            extracted_output = _first_nested_value(
                envelope,
                ("extracted_code", "extracted_output"),
            )
            assembled_output = _first_nested_value(
                envelope,
                ("assembled_java", "assembled_output"),
            )
            result[record.candidate_id] = {
                "identity": {
                    "candidate_id": record.candidate_id,
                    "generation": record.generation,
                    "parent_ids": list(record.parent_ids),
                    "operator": record.operator,
                    "mutation_type": record.mutation_type,
                    "status": record.status,
                },
                "objectives": record.objectives,
                "evaluation": {
                    key: envelope.get(key, record.raw.get(key))
                    for key in (
                        "game_metrics",
                        "code_quality",
                        "function_capability",
                        "strategy_alignment",
                        "matches",
                    )
                    if envelope.get(key, record.raw.get(key)) is not None
                },
                "lineage_and_operator": {
                    key: record.raw.get(key)
                    for key in (
                        "parent_ids",
                        "strategy_parent_id",
                        "previous_code_parent_id",
                        "generation_prompt_parent_id",
                        "source_candidate_ids",
                        "operator",
                        "mutation_type",
                        "metadata",
                    )
                },
                "prompts_and_source": {
                    "strategy_prompt": record.strategy_prompt,
                    "generation_prompt": record.generation_prompt,
                    "generated_java": record.generated_java,
                    "raw_llm_response": raw_response
                    if raw_response is not None
                    else _read_detail_text(
                        candidate_dir / "generation" / "response_raw.txt"
                    ),
                    "extracted_output": extracted_output
                    if extracted_output is not None
                    else _read_detail_text(
                        candidate_dir
                        / "generation"
                        / "extracted_candidate.java"
                    ),
                    "assembled_output": assembled_output
                    if assembled_output is not None
                    else record.generated_java
                    or _read_detail_text(
                        candidate_dir
                        / "generation"
                        / "normalized_candidate.java"
                    ),
                },
                "failure": {
                    "stage": record.failure_stage,
                    "category": record.failure_category,
                    "reason": record.failure_reason,
                    "error": envelope.get("error"),
                },
                "timing": envelope.get("generation_timing")
                or record.raw.get("timing"),
                "artifact_paths": _candidate_artifact_paths(candidate_dir),
            }
        return result

    def _evaluation(
        self, records: list[CandidateRecord], final_tests: list[Any]
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        durations: list[float] = []
        success_count = 0
        failure_count = 0
        for record in records:
            raw = record.raw
            envelope = raw.get("_result_envelope")
            envelope = envelope if isinstance(envelope, dict) else {}
            metrics_source = (
                envelope.get("game_metrics")
                or raw.get("game_metrics")
                or raw.get("game_eval_result")
            )
            metrics = _flatten_numeric(metrics_source)
            for name, value in metrics.items():
                rows.append(
                    {
                        "candidate_id": record.candidate_id,
                        "generation": record.generation,
                        "metric": name,
                        "value": value,
                        "failed": self._failed(record),
                    }
                )
            duration = _evaluation_duration(raw, envelope)
            if duration is not None:
                durations.append(duration)
            if self._failed(record):
                failure_count += 1
            else:
                success_count += 1

        summaries: dict[str, dict[str, Any]] = {}
        trends: list[dict[str, Any]] = []
        metric_names = sorted({row["metric"] for row in rows})
        for name in metric_names:
            metric_rows = [row for row in rows if row["metric"] == name]
            valid = [row["value"] for row in metric_rows if not row["failed"]]
            summaries[name] = {
                "metric": name,
                **_value_statistics(valid),
                "count": len(valid),
                "missing_or_failed_count": len(metric_rows) - len(valid),
            }
            by_generation: defaultdict[int, list[float]] = defaultdict(list)
            for row in metric_rows:
                if not row["failed"]:
                    by_generation[int(row["generation"])].append(
                        float(row["value"])
                    )
            for generation, values in sorted(by_generation.items()):
                trends.append(
                    {
                        "generation": generation,
                        "metric": name,
                        "mean": mean(values),
                        "count": len(values),
                    }
                )
        return {
            "available": bool(rows),
            "rows": rows,
            "summaries": summaries,
            "trends": trends,
            "success_count": success_count,
            "failure_count": failure_count,
            "duration": {
                **_value_statistics(durations),
                "count": len(durations),
            },
            "final_tests": [
                {
                    "final_test_id": item.final_test_id,
                    "status": item.status,
                    "formal": item.formal,
                    "tested_candidate_ids": list(item.tested_candidate_ids),
                    "expected_matches": item.expected_matches,
                    "completed_matches": item.completed_matches,
                    "incomplete_matches": item.incomplete_matches,
                    "path": str(item.path),
                }
                for item in final_tests
            ],
        }

    @staticmethod
    def _record_absence_warnings(
        objectives: list[str],
        pareto: dict[str, Any],
        operators: dict[str, Any],
        timing: dict[str, Any],
        errors: dict[str, Any],
        evaluation: dict[str, Any],
        warnings: defaultdict[str, list[str]],
    ) -> None:
        if not objectives:
            warnings["objectives"].append(
                "Objective data unavailable: no objective values were recorded."
            )
        if len(objectives) >= 2 and not pareto["available"]:
            warnings["objectives"].append(
                "Multi-objective data is incomplete; the Pareto view cannot be computed."
            )
        if not operators["statistics"]:
            warnings["operators"].append(
                "Operator data unavailable: no candidate operator identifiers were recorded."
            )
        if not timing.get("generations") and not timing.get("llm_requests"):
            warnings["timing"].append(
                "Timing data unavailable: no run or candidate timing records were found."
            )
        if not errors["rows"]:
            warnings["errors"].append(
                "No recorded failures are available for error analysis."
            )
        if not evaluation["available"]:
            warnings["evaluation"].append(
                "Generic evaluator metrics were not recorded."
            )

    @staticmethod
    def _failed(record: CandidateRecord) -> bool:
        return (
            record.status == "failed"
            or bool(record.failure_reason)
            or any(
                float(value) in FAILURE_SENTINELS
                for value in record.objectives.values()
            )
        )

    @staticmethod
    def _artifact_inventory(run_dir: Path) -> dict[str, bool]:
        paths = {
            "results": "results.jsonl",
            "summary": "summary.json",
            "resolved_config": "resolved_config.json",
            "prompt_snapshot": "prompt_snapshot.json",
            "timing": "timing.jsonl",
            "llm_requests": "llm_logs",
            "candidates": "candidates",
            "final_tests": "final_tests",
        }
        return {
            name: (run_dir / relative).exists()
            for name, relative in paths.items()
        }


def filter_candidate_rows(
    rows: list[dict[str, Any]],
    *,
    search: str = "",
    generation: int | None = None,
    status: str | None = None,
    pareto: bool | None = None,
) -> list[dict[str, Any]]:
    """Pure filter used by the paginated GUI table and unit tests."""

    needle = search.strip().lower()
    result = []
    for row in rows:
        if needle and needle not in str(row.get("candidate_id", "")).lower():
            continue
        if generation is not None and int(row.get("generation", -1)) != generation:
            continue
        failed = bool(row.get("failed")) or row.get("status") == "failed"
        if status == "success" and failed:
            continue
        if status == "failed" and not failed:
            continue
        if pareto is not None and bool(row.get("pareto")) is not pareto:
            continue
        result.append(row)
    return result


def _duration_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(
        value
        for item in records
        if (value := _number(item.get("duration_seconds"))) is not None
    )
    if not values:
        return {
            "count": 0,
            "total": 0.0,
            "mean": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    p95_index = max(0, math.ceil(0.95 * len(values)) - 1)
    return {
        "count": len(values),
        "total": sum(values),
        "mean": mean(values),
        "median": median(values),
        "p95": values[p95_index],
        "maximum": max(values),
    }


def _group_duration(
    records: list[dict[str, Any]], key: str
) -> dict[str, dict[str, Any]]:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get(key) or "unknown")].append(record)
    return {
        name: _duration_statistics(values) for name, values in sorted(groups.items())
    }


def _value_statistics(values: list[float]) -> dict[str, float | None]:
    return {
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "stddev": stdev(values) if len(values) > 1 else None,
    }


def _histogram(values: list[float]) -> list[dict[str, float | int | str]]:
    if not values:
        return []
    if len(set(values)) == 1:
        return [{"label": f"{values[0]:.4g}", "count": len(values)}]
    bin_count = min(20, max(5, math.ceil(math.sqrt(len(values)))))
    low, high = min(values), max(values)
    width = (high - low) / bin_count
    counts = [0] * bin_count
    for value in values:
        index = min(bin_count - 1, int((value - low) / width))
        counts[index] += 1
    return [
        {
            "label": f"{low + index * width:.4g}–{low + (index + 1) * width:.4g}",
            "count": count,
        }
        for index, count in enumerate(counts)
    ]


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _first_timestamp(records: list[dict[str, Any]], key: str) -> Any:
    values = [item.get(key) for item in records if item.get(key)]
    return min(values) if values else None


def _last_timestamp(records: list[dict[str, Any]], key: str) -> Any:
    values = [item.get(key) for item in records if item.get(key)]
    return max(values) if values else None


def _first_numeric(payload: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _first_nested_value(payload, (name,))
        number = _number(value)
        if number is not None:
            return number
    return None


def _first_nested_value(payload: Any, names: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for name in names:
            if name in payload and payload[name] is not None:
                return payload[name]
        for value in payload.values():
            found = _first_nested_value(value, names)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _first_nested_value(value, names)
            if found is not None:
                return found
    return None


def _short_message(message: str, limit: int = 240) -> str:
    compact = " ".join(message.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _nested_status(payload: dict[str, Any], name: str) -> Any:
    value = payload.get(name)
    if isinstance(value, dict):
        return value.get("status") or value.get("ok")
    return None


def _candidate_token_usage(timing: dict[str, Any]) -> int | None:
    total = 0
    found = False
    for value in timing.values():
        if not isinstance(value, dict):
            continue
        for attempt in value.get("attempts", []):
            if not isinstance(attempt, dict):
                continue
            counts = attempt.get("token_counts")
            if not isinstance(counts, dict):
                continue
            found = True
            total += int(counts.get("total_tokens", 0) or 0)
    return total if found else None


def _candidate_duration(timing: dict[str, Any]) -> float | None:
    for name in ("child_total", "total_duration_seconds"):
        value = timing.get(name)
        if isinstance(value, dict):
            value = value.get("duration_seconds")
        number = _number(value)
        if number is not None:
            return number
    return None


def _candidate_artifact_paths(candidate_dir: Path) -> dict[str, str]:
    if not candidate_dir.is_dir():
        return {}
    relatives = set(CANDIDATE_ARTIFACT_PATHS.values())
    relatives.update(
        {
            "genotype/strategy_prompt.txt",
            "genotype/previous_code.java",
            "genotype/generation_prompt.txt",
            "crossover/provenance.json",
            "mutation/reflector_request.txt",
            "mutation/reflector_response_raw.txt",
            "mutation/rewriter_request.txt",
            "mutation/rewriter_response_raw.txt",
            "strategy_alignment/result.json",
            "evaluation/function_capability.json",
            "evaluation/summary.json",
            "evaluation/runtime_failure.json",
        }
    )
    return {
        relative: str(candidate_dir / relative)
        for relative in sorted(relatives)
        if (candidate_dir / relative).is_file()
    }


def _flatten_numeric(payload: Any, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            number = _number(value)
            if number is not None:
                result[name] = number
            elif isinstance(value, dict):
                result.update(_flatten_numeric(value, name))
    return result


def _read_detail_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[Unable to read {path}: {exc}]"


def _evaluation_duration(
    raw: dict[str, Any], envelope: dict[str, Any]
) -> float | None:
    timing = envelope.get("generation_timing") or raw.get("timing")
    if not isinstance(timing, dict):
        return None
    evaluation = timing.get("evaluation")
    if isinstance(evaluation, dict):
        return _number(evaluation.get("duration_seconds"))
    return None
