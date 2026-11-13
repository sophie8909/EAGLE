"""Build a disposable experiment catalog from batch indices and local assignments."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig
from eagle.experiment_index import EXPERIMENT_INDEX_SCHEMA_VERSION, decode_experiment_run_index
from eagle.run_artifacts import RUN_SCHEMA_VERSION

SETTINGS_PATH = "logs/experiment-analysis.yaml"
SETTINGS_SCHEMA = "eagle-analysis-settings-v1"
CATALOG_SCHEMA = "eagle-experiment-catalog-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_READ_ERRORS = (OSError, ValueError, TypeError, yaml.YAMLError)


def _mapping(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Expected a mapping.")
    return value


def _yaml(path: Path) -> dict:
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("IDs must contain only letters, numbers, underscores, and hyphens.")
    return value


def _default_id(value: str) -> str:
    if _ID.fullmatch(value):
        return value
    prefix = re.sub(r"[^A-Za-z0-9_-]", "-", value).strip("-_")[:110] or "item"
    suffix = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{prefix}-{suffix}"


def _relocate(value: str, root: Path, mappings: dict) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty artifact path.")
    normalized = value.replace("\\", "/")
    for source in sorted(mappings, key=len, reverse=True):
        prefix = source.replace("\\", "/").rstrip("/")
        windows = re.match(r"^[A-Za-z]:/", prefix) or prefix.startswith("//")
        left, right = (normalized.casefold(), prefix.casefold()) if windows else (normalized, prefix)
        if left == right or left.startswith(right + "/"):
            destination = (root / mappings[source]).expanduser().resolve()
            target = (destination / normalized[len(prefix):].lstrip("/")).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Relocated path escapes its mapped directory.")
            return target
    path = Path(normalized).expanduser()
    if (normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized)) and not path.is_absolute():
        raise ValueError("Foreign absolute path needs an explicit path mapping.")
    return (root / path).resolve()


def _settings(path: Path) -> tuple[dict, dict, list]:
    payload = _yaml(path)
    if payload.get("schema_version") != SETTINGS_SCHEMA:
        raise ValueError(f"Expected settings schema {SETTINGS_SCHEMA}.")
    mappings = _mapping(payload.get("path_mappings", {}))
    if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
           for key, value in mappings.items()):
        raise ValueError("Path mappings require nonempty source and destination strings.")
    batches = _mapping(payload.get("batches", {}))
    runs = payload.get("runs", [])
    if not isinstance(runs, list):
        raise ValueError("The runs field must be a list.")
    return mappings, batches, runs


def _benchmarks(value: object, root: Path, mappings: dict) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("The benchmarks field must be a list.")
    items = []
    for raw in value:
        item = {"path": raw} if isinstance(raw, str) else _mapping(raw)
        path = _relocate(item.get("path"), root, mappings)
        if path.is_dir():
            path /= "fixed_evaluation_summary.json"
        entry = {"path": str(path)}
        if item.get("protocol") is not None:
            entry["protocol"] = str(_relocate(item["protocol"], root, mappings))
        if item.get("label") is not None:
            if not isinstance(item["label"], str):
                raise ValueError("Benchmark label must be a string.")
            entry["label"] = item["label"]
        if item.get("population_size") is not None:
            size = item["population_size"]
            if type(size) is not int or size < 1:
                raise ValueError("Benchmark population_size must be a positive integer.")
            entry["population_size"] = size
        items.append(entry)
    return items


def _planned_seeds(path: Path) -> tuple[int, ...]:
    # Cataloging archived runs should not require the launcher's model or bundle files.
    payload = _yaml(path)
    repeats = int(payload.get("runs", 1))
    raw_seeds = payload.get("random_seeds") or ()
    if not isinstance(raw_seeds, (list, tuple)) or repeats < 1:
        raise ValueError("Expected a list of random_seeds and a positive runs count.")
    return ExperimentConfig(
        seed_prompts=(), runs=repeats,
        random_seed=int(payload.get("random_seed", 7)),
        random_seeds=tuple(int(seed) for seed in raw_seeds),
    ).seed_schedule


def _run_metadata(path: Path) -> dict:
    manifest = _mapping(json.loads((path / "manifest.json").read_text(encoding="utf-8")))
    if manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError(f"Expected run schema {RUN_SCHEMA_VERSION}.")
    config = _yaml(path / "config.yaml")
    seed = config.get("random_seed")
    if type(seed) is not int:
        raise ValueError("Resolved config.yaml has no integer random_seed.")
    generation = manifest.get("latest_generation")
    planned = config.get("generations")
    return {
        "run_id": _identifier(manifest.get("run_id") or path.name),
        "path": str(path),
        "seed": seed,
        "status": manifest.get("status", "unknown"),
        "latest_generation": generation if type(generation) is int and generation >= 0 else None,
        "planned_generation": planned if type(planned) is int and planned >= 0 else None,
    }


def _availability(run: dict) -> dict:
    path = Path(run["path"])
    latest = run["latest_generation"]
    generation = path / "generations" / f"generation_{latest:04d}.json" if latest is not None else None
    return {
        "committed_generation": bool(generation and generation.is_file()),
        "fixed": any(Path(item["path"]).is_file() for item in run["benchmarks"]) or any(
            (path / folder / "fixed_evaluation_summary.json").is_file()
            for folder in ("fixed_evaluation", "final_test/cross_generation")
        ) or any((path / "final_test").glob("cross_generation_retry_*/fixed_evaluation_summary.json")),
        "final": (path / "final_test/final_test_summary.json").is_file(),
    }


def discover(root: Path, runs_roots) -> dict:
    """Read source metadata only. Never modify a run or launcher index."""
    root = root.resolve()
    issues = []

    def issue(source: object, reason: object) -> None:
        issues.append({"source": str(source), "reason": str(reason)})

    settings_path = root / SETTINGS_PATH
    mappings, batches, registrations = {}, {}, []
    if settings_path.exists():
        try:
            mappings, batches, registrations = _settings(settings_path)
        except _READ_ERRORS as exc:
            issue(settings_path, exc)

    # A path can occur in multiple source indices. Require an explicit assignment
    # whenever those indices disagree about its experiment or treatment.
    claims = defaultdict(list)
    treatments = {}
    indices = set((root / "configs").rglob("experiment.yaml"))
    batch_options = {}
    for source, raw in batches.items():
        try:
            index = _relocate(source, root, mappings)
            if index.name != "experiment.yaml":
                raise ValueError("A batch index must be named experiment.yaml.")
            indices.add(index)
            batch_options[index] = _mapping(raw)
        except _READ_ERRORS as exc:
            issue(source, exc)

    def treatment(experiment: str, identity: str, label: str, seeds=()) -> None:
        key = experiment, identity
        item = treatments.setdefault(key, {
            "experiment": experiment, "treatment": identity, "label": label, "expected_seeds": set(),
        })
        if label != item["label"]:
            issue(f"{experiment}/{identity}", f"Conflicting treatment labels: {item['label']} and {label}.")
        item["expected_seeds"].update(seeds)

    for index in sorted(indices):
        try:
            payload = _yaml(index) if index.exists() or index not in batch_options else {
                "schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION, "runs": {},
            }
            if payload.get("schema_version") == "experiment-v2":
                if index in batch_options:
                    raise ValueError("This experiment.yaml is an input config, not a batch index.")
                continue
            entries = decode_experiment_run_index(payload, index)
            options = batch_options.get(index, {})
            overrides = _mapping(options.get("treatments", {}))
            if index.parent.is_relative_to(root / "configs/experiments"):
                batch_id = index.parent.relative_to(root / "configs/experiments").as_posix()
            elif index.parent.is_relative_to(root):
                batch_id = index.parent.relative_to(root).as_posix()
            else:
                batch_id = index.parent.name
            experiment = _identifier(options.get("experiment", _default_id(batch_id)))
            filenames = set(entries) | set(overrides)
            filenames.update(
                path.name for path in index.parent.iterdir()
                if path.is_file() and path != index and path.suffix.lower() in {".yaml", ".yml"}
            )
        except _READ_ERRORS as exc:
            issue(index, exc)
            continue
        for name in sorted(filenames, key=str):
            source = f"{index} ({name})"
            try:
                if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
                    raise ValueError("Expected an exact config filename.")
                override = _mapping(overrides.get(name, {}))
                stem = Path(name).stem
                if sum(isinstance(filename, str) and Path(filename).stem == stem
                       for filename in filenames) > 1:
                    stem = name
                identity = _identifier(override.get("id", _default_id(stem)))
                label = override.get("label", identity)
                if not isinstance(label, str) or not label.strip():
                    raise ValueError("Treatment label must be a nonempty string.")
            except _READ_ERRORS as exc:
                issue(source, exc)
                continue
            seeds = ()
            try:
                seeds = _planned_seeds(index.parent / name)
            except _READ_ERRORS as exc:
                issue(source, f"Unable to read planned seeds: {exc}")
            treatment(experiment, identity, label, seeds)
            for replicate, folder in enumerate(entries.get(name, ())):
                try:
                    path = _relocate(folder, root, mappings)
                    claims[path].append({
                        "experiment": experiment, "treatment": identity, "label": label,
                        "indexed": True, "source": source, "replicate_index": replicate, "benchmarks": [],
                    })
                except _READ_ERRORS as exc:
                    issue(f"{source}[{replicate}] {folder}", exc)

    manual = defaultdict(list)
    external = {}
    for registration in registrations:
        source = settings_path
        try:
            item = _mapping(registration)
            path = _relocate(item.get("path"), root, mappings)
            source = path
            experiment = _identifier(item.get("experiment"))
            identity = _identifier(item.get("treatment"))
            label = item.get("label", treatments.get((experiment, identity), {}).get("label", identity))
            if not isinstance(label, str) or not label.strip():
                raise ValueError("Treatment label must be a nonempty string.")
            benchmarks = _benchmarks(item.get("benchmarks", []), root, mappings)
            if item.get("run_id") is not None or item.get("seed") is not None:
                run_id, seed = _identifier(item.get("run_id")), item.get("seed")
                if type(seed) is not int or not benchmarks:
                    raise ValueError("An external-only run requires an integer seed and registered benchmarks.")
                external[path] = {
                    "run_id": run_id, "path": str(path), "seed": seed, "status": "archived",
                    "latest_generation": None, "planned_generation": None,
                }
            treatment(experiment, identity, label)
            manual[path].append({
                "experiment": experiment, "treatment": identity, "label": label,
                "indexed": False, "source": str(settings_path), "replicate_index": None,
                "benchmarks": benchmarks,
            })
        except _READ_ERRORS as exc:
            issue(source, exc)

    paths = set(claims) | set(manual)
    for runs_root in runs_roots:
        paths.update(path.parent.resolve() for path in Path(runs_root).glob("*/manifest.json"))
    rows = []
    for path in sorted(paths):
        try:
            row = _run_metadata(path)
        except _READ_ERRORS as exc:
            for claim in claims.get(path, ()):
                issue(f"{claim['source']}[{claim['replicate_index']}] {path}", exc)
            if len(manual.get(path, ())) == 1 and path in external:
                row = external[path]
                issue(path, f"Canonical run artifacts unavailable: {exc}")
            else:
                if path not in claims:
                    issue(path, exc)
                continue
        assignments = manual.get(path) or claims.get(path) or []
        groups = {(item["experiment"], item["treatment"]) for item in assignments}
        if not groups:
            issue(path, f"Unassigned run {row['run_id']} (seed {row['seed']}); register it in {SETTINGS_PATH}.")
            continue
        if len(groups) != 1 or len(manual.get(path, ())) > 1:
            issue(path, f"Ambiguous run {row['run_id']}; assign it once in {SETTINGS_PATH}.")
            continue
        assignment = dict(assignments[0])
        matching = [claim for claim in claims.get(path, ()) if
                    (claim["experiment"], claim["treatment"]) in groups]
        if matching:
            assignment["indexed"] = True
            assignment["replicate_index"] = matching[0]["replicate_index"]
            assignment["source"] = matching[0]["source"]
        row.update(assignment)
        row["availability"] = _availability(row)
        rows.append(row)
        treatment(row["experiment"], row["treatment"], row["label"], [row["seed"]])

    # Identical copies share their portable run ID. Require a single canonical
    # location when registered copies with the same ID have conflicting paths.
    duplicates = defaultdict(list)
    for row in rows:
        duplicates[row["run_id"]].append(row)
    unique = []
    for identity, copies in duplicates.items():
        if len(copies) == 1:
            unique.append(copies[0])
            continue
        indexed = [row for row in copies if row["indexed"]]
        if len(indexed) == 1:
            unique.append(indexed[0])
        issue(identity, "Duplicate run ID found at " + ", ".join(row["path"] for row in copies))

    for item in treatments.values():
        item["expected_seeds"] = sorted(item["expected_seeds"])
    return {
        "schema_version": CATALOG_SCHEMA,
        "runs": unique,
        "treatments": [treatments[key] for key in sorted(treatments)],
        "issues": issues,
    }
