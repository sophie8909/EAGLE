"""ECharts option builders for objective analysis views."""

from __future__ import annotations

import hashlib

import pandas as pd


def generation_distribution_options(frame: pd.DataFrame, objective: str, *, include_median: bool = True) -> dict:
    points = []
    for _, row in frame.dropna(subset=[objective]).iterrows():
        jitter = (_stable_fraction(str(row["candidate_id"])) - 0.5) * 0.28
        points.append({
            "name": str(row["candidate_id"]),
            "value": [float(row["generation"]) + jitter, float(row[objective])],
            "itemStyle": {"opacity": 0.45, "color": "#ef4444" if bool(row["failed"]) else "#38bdf8"},
        })
    grouped = frame.dropna(subset=[objective]).groupby("generation")[objective]
    mean = [[int(generation), float(value)] for generation, value in grouped.mean().items()]
    series = [
        {"name": "candidates", "type": "scatter", "symbolSize": 9, "data": points},
        {"name": "mean", "type": "line", "data": mean, "smooth": False, "symbolSize": 7},
    ]
    if include_median:
        series.append({"name": "median", "type": "line", "data": [[int(g), float(v)] for g, v in grouped.median().items()], "lineStyle": {"type": "dashed"}})
    return _base_xy("Generation", objective, series)


def objective_scatter_options(frame: pd.DataFrame, x_objective: str, y_objective: str, *, pareto_ids: set[str] | None = None) -> dict:
    pareto_ids = pareto_ids or set()
    points = []
    for _, row in frame.dropna(subset=[x_objective, y_objective]).iterrows():
        candidate_id = str(row["candidate_id"])
        failed = bool(row["failed"])
        points.append({
            "name": candidate_id,
            "value": [float(row[x_objective]), float(row[y_objective]), int(row["generation"]), str(row["status"])],
            "symbol": "diamond" if failed else "circle",
            "symbolSize": 16 if candidate_id in pareto_ids else 9,
            "itemStyle": {"color": "#ef4444" if failed else "#b08d57" if candidate_id in pareto_ids else "#38bdf8", "opacity": 0.75},
        })
    return _base_xy(x_objective, y_objective, [{"name": "candidates", "type": "scatter", "data": points}])


def _base_xy(x_name: str, y_name: str, series: list[dict]) -> dict:
    return {
        "backgroundColor": "transparent",
        "tooltip": {"trigger": "item"},
        "legend": {"textStyle": {"color": "#e5e7eb"}},
        "xAxis": {"type": "value", "name": x_name, "nameTextStyle": {"color": "#e5e7eb"}, "axisLabel": {"color": "#94a3b8"}},
        "yAxis": {"type": "value", "name": y_name, "nameTextStyle": {"color": "#e5e7eb"}, "axisLabel": {"color": "#94a3b8"}},
        "series": series,
    }


def _stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
