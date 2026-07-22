"""Objective data preparation, filtering, Pareto sets, and statistics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping

import pandas as pd

from evaluation.nsga2_objectives import OBJECTIVE_DIRECTIONS

from .records import CandidateRecord


ANALYSIS_METRIC_DIRECTIONS = {
    **OBJECTIVE_DIRECTIONS,
    "compilation_score": "maximize",
    "function_capability": "maximize",
    "strategy_alignment": "maximize",
}


@dataclass(frozen=True)
class ObjectiveFilters:
    generation_min: int | None = None
    generation_max: int | None = None
    statuses: tuple[str, ...] = ()
    operators: tuple[str, ...] = ()
    candidate_id: str = ""
    failure_categories: tuple[str, ...] = ()


def prepare_objective_frame(records: Iterable[CandidateRecord]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        row: dict[str, object] = {
            "candidate_id": record.candidate_id,
            "generation": record.generation,
            "status": record.status,
            "operator": record.operator,
            "mutation_type": record.mutation_type,
            "failure_category": record.failure_category,
            "failed": bool(record.failure_reason) or record.status == "failed",
        }
        row.update(record.objectives)
        quality = record.raw.get("code_quality_result")
        if isinstance(quality, dict):
            breakdown = quality.get("code_quality_breakdown")
            if isinstance(breakdown, dict):
                row["compilation_score"] = _number(breakdown.get("compilation_score"))
                row["function_capability"] = _number(breakdown.get("function_score"))
                row["strategy_alignment"] = _number(breakdown.get("strategy_alignment_score"))
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["generation", "candidate_id"], kind="stable").reset_index(drop=True)
    return frame


def filter_objective_frame(frame: pd.DataFrame, filters: ObjectiveFilters) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    mask = pd.Series(True, index=frame.index)
    if filters.generation_min is not None:
        mask &= frame["generation"] >= filters.generation_min
    if filters.generation_max is not None:
        mask &= frame["generation"] <= filters.generation_max
    if filters.statuses:
        mask &= frame["status"].isin(filters.statuses)
    if filters.operators:
        mask &= frame["operator"].isin(filters.operators)
    if filters.candidate_id:
        mask &= frame["candidate_id"].astype(str).str.contains(filters.candidate_id, case=False, regex=False)
    if filters.failure_categories:
        mask &= frame["failure_category"].isin(filters.failure_categories)
    return frame.loc[mask].copy()


def available_objectives(frame: pd.DataFrame) -> list[str]:
    metadata = {"candidate_id", "generation", "status", "operator", "mutation_type", "failure_category", "failed"}
    return [column for column in frame.columns if column not in metadata and pd.api.types.is_numeric_dtype(frame[column]) and frame[column].notna().any()]


def load_objective_directions(run_dir: Path) -> dict[str, str]:
    path = run_dir / "resolved_config.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        directions = payload.get("objective_directions")
        if isinstance(directions, dict):
            resolved = {str(name): _validate_direction(str(value)) for name, value in directions.items()}
            return {**ANALYSIS_METRIC_DIRECTIONS, **resolved}
    return dict(ANALYSIS_METRIC_DIRECTIONS)


def pareto_frame(frame: pd.DataFrame, objectives: tuple[str, ...], directions: Mapping[str, str]) -> pd.DataFrame:
    if frame.empty or not objectives:
        return frame.iloc[0:0].copy()
    usable = frame.dropna(subset=list(objectives)).copy()
    nondominated: list[bool] = []
    for left_index, left in usable.iterrows():
        dominated = False
        for right_index, right in usable.iterrows():
            if left_index == right_index:
                continue
            if _dominates(right, left, objectives, directions):
                dominated = True
                break
        nondominated.append(not dominated)
    return usable.loc[nondominated].copy()


def generation_statistics(frame: pd.DataFrame, objective: str) -> pd.DataFrame:
    columns = ["generation", "min", "max", "mean", "median", "success_count", "failure_count"]
    if frame.empty or objective not in frame:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for generation, group in frame.groupby("generation", sort=True):
        values = [float(value) for value in group[objective].dropna()]
        if not values:
            continue
        failed = int(group["failed"].astype(bool).sum())
        rows.append({
            "generation": int(generation),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "median": median(values),
            "success_count": len(group) - failed,
            "failure_count": failed,
        })
    return pd.DataFrame(rows, columns=columns)


def _dominates(left: pd.Series, right: pd.Series, objectives: tuple[str, ...], directions: Mapping[str, str]) -> bool:
    no_worse = True
    strictly_better = False
    for objective in objectives:
        direction = _validate_direction(directions[objective])
        left_value = float(left[objective])
        right_value = float(right[objective])
        if direction == "maximize":
            no_worse &= left_value >= right_value
            strictly_better |= left_value > right_value
        else:
            no_worse &= left_value <= right_value
            strictly_better |= left_value < right_value
    return no_worse and strictly_better


def _validate_direction(value: str) -> str:
    if value not in {"maximize", "minimize"}:
        raise ValueError(f"Unsupported objective direction: {value}")
    return value


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
