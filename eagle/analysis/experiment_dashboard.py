"""Seed-level experiment comparisons and portable dashboard exports."""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

from eagle.analysis.experiment_catalog import discover
from eagle.analysis.experiment_metrics import read_metrics

BUNDLE_SCHEMA = "eagle-experiment-results-v1"
TABLES = ("points", "aggregates", "deltas", "opponents", "fixed_coverage")
COUNTS = ("wins", "draws", "losses", "errors")
METRICS = ("self_play", "fixed", "diversity")


def _bundle_dir(root, experiment):
    if not isinstance(experiment, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", experiment):
        raise ValueError("Invalid experiment ID.")
    destination = root / "results" / experiment
    if destination.resolve() != destination:
        raise ValueError("Result destination must be inside the repository without symlinks.")
    if not (destination / "manifest.json").is_file():
        legacy = root / "reports" / "experiments" / experiment
        if (legacy / "manifest.json").is_file():
            return legacy
    return destination


def _diagnostics(local):
    return [f"{item['source']}: {item['reason']}" for item in local["issues"]]


def catalog(root, runs_roots):
    local = discover(root, runs_roots)
    experiments = {row["experiment"] for row in local["treatments"] + local["runs"]}
    result_manifests = sorted((root / "results").glob("*/manifest.json"))
    # Keep old local exports readable while moving new exports to results/.
    result_manifests += sorted((root / "reports/experiments").glob("*/manifest.json"))
    return {
        "schema_version": local["schema_version"],
        "experiments": [{"id": name, "label": name} for name in sorted(experiments)]
        + [{"id": path.parent.name, "label": path.parent.name, "bundle": True}
           for path in result_manifests],
        "issues": _diagnostics(local),
    }


def _selected(runs, filters):
    by_seed = defaultdict(list)
    for run in runs:
        if type(run["seed"]) is int:
            by_seed[run["treatment"], run["seed"]].append(run)
    treatments = filters.get("treatments")
    seeds = filters.get("seeds")
    attempts = filters.get("attempts", {})
    result = []
    for (treatment, seed), options in sorted(by_seed.items()):
        if (treatments is not None and treatment not in treatments) or (seeds is not None and seed not in seeds):
            continue
        preferred = attempts.get(f"{treatment}:{seed}")
        result.append(max(options, key=lambda row: (
            row["run_id"] == preferred, row["indexed"], row["run_id"],
        )))
    return result


def _public_run(run):
    return {key: run.get(key) for key in (
        "experiment", "treatment", "label", "seed", "run_id", "status",
        "latest_generation", "planned_generation", "indexed", "replicate_index", "availability",
    )}


def _stats(values):
    return {"value": statistics.fmean(values), "n": len(values),
            "min": min(values), "max": max(values),
            "sd": statistics.stdev(values) if len(values) > 1 else None}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _rate(row):
    counted = sum(row[key] for key in COUNTS[:3])
    return {**row, "counted": counted, "win_rate": row["wins"] / counted if counted else None}


def _key(row):
    return (row["metric"], row["statistic"], row["generation"],
            row.get("protocol"), row.get("opponent"))


def _summary(points, selected, fixed_cohort, baseline, paired, issues):
    groups = defaultdict(dict)
    series = defaultdict(list)
    for row in points:
        metric, statistic, generation, protocol, opponent = _key(row)
        if not protocol:
            continue
        key = (row["treatment"], metric, statistic, protocol, opponent)
        groups[key][generation] = groups[key].get(generation, {}) | {row["seed"]: row}
    expected = defaultdict(set)
    for row in selected:
        expected[row["treatment"]].add(row["seed"])
    aggregates = []
    for (treatment, metric, statistic, protocol, opponent), generations in groups.items():
        cohort = set.intersection(*(set(rows) for rows in generations.values()))
        for generation, rows in sorted(generations.items()):
            membership = sorted(rows.keys() & cohort if fixed_cohort and metric != "final" else rows)
            if not membership:
                continue
            identity = dict(metric=metric, statistic=statistic, generation=generation,
                            protocol=protocol, opponent=opponent)
            aggregates.append(dict(treatment=treatment, **identity, seeds=membership,
                                   missing_seeds=sorted(expected[treatment] - set(membership)),
                                   **_stats([rows[seed]["value"] for seed in membership])))
            if not protocol:
                continue
            for seed in membership:
                series[metric, statistic, generation, protocol, opponent].append(rows[seed])
    endpoints = defaultdict(list)
    for row in points:
        if row["metric"] == "final" and row.get("protocol"):
            endpoints[row["treatment"], row["statistic"], row["protocol"]].append(row)
    for (treatment, statistic, protocol), rows in endpoints.items():
        generations = sorted({row["generation"] for row in rows})
        if len(generations) < 2:
            continue
        seeds = sorted(row["seed"] for row in rows)
        aggregates.append(dict(treatment=treatment, metric="final", statistic=statistic,
                               generation=None, evaluated_generations=generations, protocol=protocol,
                               seeds=seeds, missing_seeds=sorted(expected[treatment] - set(seeds)),
                               comparison="run_endpoint",
                               **_stats([row["value"] for row in rows])))
    deltas = []
    if not paired or not baseline:
        return aggregates, deltas
    for (metric, statistic, generation, protocol, opponent), rows in series.items():
        baseline_rows = {row["seed"]: row for row in rows if row["treatment"] == baseline}
        for treatment in sorted(expected.keys() - {baseline}):
            matching = [row for row in rows if row["treatment"] == treatment and row["seed"] in baseline_rows]
            identity = dict(treatment=treatment, baseline=baseline, metric=metric, statistic=statistic,
                            generation=generation, protocol=protocol, opponent=opponent)
            values = []
            for row in matching:
                other = baseline_rows[row["seed"]]
                delta = row["value"] - other["value"]
                values.append(delta)
                deltas.append(dict(**identity, seed=row["seed"], value=delta,
                                   run_id=row["run_id"], baseline_run_id=other["run_id"],
                                   source=row.get("source"), baseline_source=other.get("source")))
            seeds = sorted(row["seed"] for row in matching)
            deltas.append(dict(**identity, seed=None, seeds=seeds,
                               missing_seeds=sorted((expected[treatment] & expected[baseline]) - set(seeds)),
                               **(_stats(values) if values else {"value": None, "n": 0})))
    if not any(row.get("n", 0) for row in deltas):
        issues.append("No compatible same-generation observations for the selected baseline and seeds.")
    if any(row["metric"] == "final" for row in points) and not any(
        row["metric"] == "final" and row["statistic"] == "score" and row.get("n", 0) for row in deltas
    ):
        issues.append("Final-test score: no compatible score at the same evaluated checkpoint for any selected seed pair.")
    return aggregates, deltas


def _opponent_totals(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.get("protocol"):
            groups[row["treatment"], row["opponent"], row["protocol"]].append(row)
    result = [_rate(row) for row in rows]
    for (treatment, opponent, protocol), members in groups.items():
        rates = [item["win_rate"] for item in map(_rate, members) if item["win_rate"] is not None]
        result.append(_rate(dict(
            treatment=treatment, opponent=opponent, protocol=protocol, seed=None,
            seeds=sorted(row["seed"] for row in members),
            **{key: sum(row[key] for row in members) for key in COUNTS},
            faults=sum(row.get("faults", row.get("opponent_fault_contained", 0)) or 0 for row in members)
            if any(row.get("faults", row.get("opponent_fault_contained")) is not None for row in members) else None,
            mean_seed_win_rate=statistics.fmean(rates) if rates else None,
            mean_match_score=statistics.fmean(
                [row["mean_match_score"] for row in members
                 if _number(row.get("mean_match_score"))]
            ) if any(_number(row.get("mean_match_score")) for row in members) else None,
            score_count=sum(row.get("score_count", 0) or 0 for row in members),
        )))
    return result


def view(root, runs_roots, filters):
    experiment = filters["experiment"]
    bundle_filters = {}
    fixed_opponent = filters.get("fixed_opponent") or None
    fixed_coverage, fixed_opponents = [], set()
    if filters.get("bundle"):
        path = _bundle_dir(root, experiment) / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != BUNDLE_SCHEMA or manifest.get("experiment") != experiment:
            raise ValueError("Unsupported experiment result manifest.")
        data = manifest["dashboard"]
        bundle_filters = manifest.get("filters", {})
        filters = {**bundle_filters, **filters}
        fixed_opponent = filters.get("fixed_opponent") or None
        treatments = data["treatments"]
        fixed_coverage = data.get("fixed_coverage", [])
        fixed_opponents = set(data.get("fixed_opponents", []))
        runs = data["selected"]
        source_points = data["points"]
        source_opponents = [row for row in data["opponents"] if row["seed"] is not None]
        protocols = data["protocols"]
        issues = list(data["issues"])
    else:
        local = discover(root, runs_roots)
        runs = [row for row in local["runs"] if row["experiment"] == experiment]
        source_points, source_opponents, protocols = [], [], {}
        treatments = [row for row in local["treatments"] if row["experiment"] == experiment]
        if not runs and not treatments:
            raise ValueError("Choose an experiment from the catalog.")
        issues = _diagnostics(local)
    selected = _selected(runs, filters)
    by_treatment = defaultdict(set)
    for run in selected:
        by_treatment[run["treatment"]].add(run["seed"])
    paired = bool(filters.get("paired"))
    if paired and by_treatment:
        requested_treatments = filters.get("treatments")
        if requested_treatments is None:
            requested_treatments = [row["treatment"] for row in treatments]
        common = set.intersection(*(by_treatment[key] for key in requested_treatments)) if requested_treatments else set()
        selected = [run for run in selected if run["seed"] in common]
        if not selected:
            issues.append("No selected seeds are shared across the treatments.")
    if not filters.get("bundle"):
        for run in selected:
            evidence = read_metrics(run, fixed_opponent=fixed_opponent)
            identity = {key: run[key] for key in ("experiment", "treatment", "seed", "run_id")}
            source_points.extend({**row, **identity} for row in evidence["points"])
            source_opponents.extend({**row, **identity} for row in evidence["opponents"])
            protocols.update(evidence["protocols"])
            issues.extend(f"{run['run_id']}: {issue}" for issue in evidence["issues"])
            fixed_coverage.extend({**row, **identity} for row in evidence.get("fixed_coverage", []))
            fixed_opponents.update(evidence.get("fixed_opponents", []))
            # Keep a separate cross-generation curve for every opponent in the
            # portable package, in addition to the all-opponent aggregate.
            if fixed_opponent is None:
                for opponent in evidence.get("fixed_opponents", []):
                    detail = read_metrics(run, fixed_opponent=opponent)
                    source_points.extend(
                        {**row, **identity} for row in detail["points"]
                        if row.get("metric") == "fixed"
                    )
                    fixed_coverage.extend(
                        {**row, **identity} for row in detail.get("fixed_coverage", [])
                        if row.get("metric") == "fixed"
                    )
    selected_ids = {(run["treatment"], run["seed"], run["run_id"]) for run in selected}

    def included(row):
        return (row["treatment"], row["seed"], row["run_id"]) in selected_ids

    observed = [run["latest_generation"] for run in selected]
    planned = [run["planned_generation"] for run in selected]

    def common_horizon(values):
        return min(values) if values and all(type(value) is int for value in values) else None

    horizon = {"observed": common_horizon(observed), "planned": common_horizon(planned)}
    minimum = filters.get("minimum")
    maximum = filters.get("maximum")
    if paired and horizon["observed"] is not None:
        maximum = horizon["observed"] if maximum is None else min(maximum, horizon["observed"])
    points = [
        row for row in source_points if included(row) and (
            row["metric"] == "final"
            or (row["metric"] != "fixed" or fixed_opponent is None or row.get("opponent") == fixed_opponent)
            and (minimum is None or row["generation"] >= minimum)
            and (maximum is None or row["generation"] <= maximum)
        )
    ]
    fixed_coverage = [
        row for row in fixed_coverage if included(row)
        and (minimum is None or row["generation"] >= minimum)
        and (maximum is None or row["generation"] <= maximum)
    ]
    if len({value for value in planned if value is not None}) > 1:
        issues.append("Final-test scores are run endpoints with different planned budgets. Paired deltas require an actual shared evaluated generation.")
    incompatible = defaultdict(set)
    for row in points:
        incompatible[row["metric"], row["statistic"]].add(row.get("protocol"))
    for (metric, statistic), ids in incompatible.items():
        if None in ids:
            issues.append(f"{metric}/{statistic}: recorded protocol or metric definition is incomplete.")
        if len(ids - {None}) > 1:
            definitions = [protocols.get(identity, {}) for identity in sorted(ids - {None})]
            fields = sorted(key for key in set().union(*(item.keys() for item in definitions))
                            if any(item.get(key) != definitions[0].get(key) for item in definitions[1:]))
            mismatch = ", ".join(fields) or "definition IDs"
            issues.append(f"{metric}/{statistic}: incompatible recorded definitions differ in {mismatch}.")
    baseline = filters.get("baseline") or next(iter(by_treatment), None)
    aggregates, deltas = _summary(points, selected, filters.get("fixed_cohort"), baseline, paired, issues)
    opponents = _opponent_totals([row for row in source_opponents if included(row)])
    return {
        "experiment": experiment, "runs": [_public_run(row) for row in runs],
        "selected": [_public_run(row) for row in selected], "points": points, "aggregates": aggregates,
        "deltas": deltas, "opponents": opponents, "protocols": protocols, "issues": sorted(set(issues)),
        "horizon": horizon, "baseline": baseline, "treatments": treatments,
        "fixed_opponents": sorted(fixed_opponents), "fixed_coverage": fixed_coverage,
        "filters": bundle_filters,
    }


def export(root, runs_roots, filters):
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
    except ImportError as exc:
        raise ValueError("PNG export requires Matplotlib in the GUI's Python environment.") from exc

    data = view(root, runs_roots, filters)
    if not data["selected"]:
        raise ValueError("Select at least one available run to export.")
    destination = _bundle_dir(root, data["experiment"])
    # Diagnostic text from local readers can contain absolute machine paths.
    data["issues"] = []
    data["runs"] = data["selected"]
    data["fixed_opponents"] = [filters["fixed_opponent"]] if filters.get("fixed_opponent") else []
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        stage = Path(temporary)
        files = {}
        for table in TABLES:
            name = f"{table}.csv"
            rows = data[table]
            fields = sorted({"experiment", *(key for row in rows for key in row)})
            with (stage / name).open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fields)
                writer.writeheader()
                writer.writerows({
                    "experiment": data["experiment"],
                    **{key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                       for key, value in row.items()},
                } for row in rows)
            files[table] = name
        for metric in METRICS:
            figure = Figure(figsize=(9, 4.5), layout="constrained")
            FigureCanvasAgg(figure)
            groups = defaultdict(dict)
            primary = filters.get("statistics", {}).get(metric, "best" if metric == "self_play" else "mean")
            for row in data["aggregates"]:
                if row["metric"] == metric and row["statistic"] == primary:
                    groups[row.get("protocol")].setdefault((row["treatment"], None), {})[row["generation"]] = row
            for row in data["points"]:
                if row["metric"] != metric or row["statistic"] != primary:
                    continue
                group = groups[row.get("protocol")]
                if (row["treatment"], None) not in group:
                    group.setdefault((row["treatment"], row["seed"]), {})[row["generation"]] = row
            axes = figure.subplots(max(1, len(groups)), squeeze=False)[:, 0]
            labels = {item["treatment"]: item["label"] for item in data["treatments"]}
            if not groups:
                axes[0].text(.5, .5, "No observations", ha="center", transform=axes[0].transAxes)
            for axis in axes:
                axis.set(xlabel="Generation", ylabel=metric.replace("_", " ").title())
            if len(groups) > 1:
                figure.set_figheight(4 * len(groups))
            for axis, (protocol, group) in zip(axes, groups.items()):
                axis.set_title(f"Protocol {protocol[:12]}" if protocol else "Protocol unrecorded")
                checkpoints = sorted({g for rows in group.values() for g in rows})
                if metric == "fixed":
                    checkpoints = sorted(set(checkpoints) | {
                        row["generation"] for row in data["fixed_coverage"]
                        if row["statistic"] == primary and row.get("protocol") == protocol
                    })
                else:
                    checkpoints = range(min(checkpoints), max(checkpoints) + 1)
                for (treatment, seed), rows in group.items():
                    label = labels.get(treatment, treatment)
                    if seed is not None:
                        label += f" · seed {seed}"
                    axis.plot(checkpoints, [rows[g]["value"] if g in rows else float("nan") for g in checkpoints],
                              marker=".", label=label)
                    axis.fill_between(checkpoints, *[
                        [rows[g][key] if g in rows and rows[g].get("n", 0) >= 2 else float("nan") for g in checkpoints]
                        for key in ("min", "max")
                    ], alpha=.16)
                axis.legend()
            name = f"{metric}.png"
            figure.savefig(stage / name, dpi=144)
            files[metric] = name
        manifest = {"schema_version": BUNDLE_SCHEMA, "experiment": data["experiment"],
                    "files": files, "dashboard": data,
                    "definitions": {
                        "generation": "Committed search population generation or evaluated benchmark checkpoint.",
                        "aggregation": "Equal-weight seed mean; sample standard deviation; observed min and max.",
                        "delta": "Treatment minus baseline for the same seed and evaluated generation.",
                        "win_rate": "Wins divided by wins, draws and losses. Errors are counted separately.",
                    },
                    "filters": {key: filters[key] for key in (
                        "paired", "fixed_cohort", "minimum", "maximum", "baseline", "fixed_opponent", "statistics",
                    ) if key in filters}}
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                             encoding="utf-8")
        for name in [*files.values(), "manifest.json"]:
            (stage / name).replace(destination / name)
    return {"path": destination.relative_to(root).as_posix()}
