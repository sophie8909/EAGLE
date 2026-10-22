"""Read-only experiment browsing and validated configuration editing for the local GUI."""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig
from eagle.experiment_index import is_experiment_run_index
from eagle.run_artifacts import GENERATION_SCHEMA_VERSION, RUN_SCHEMA_VERSION


def _config_path(root: Path, path: str) -> Path:
    root = root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root / "configs") or target.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Choose a YAML file inside the repository configs directory.")
    if target.exists():
        try:
            is_index = is_experiment_run_index(target)
        except ValueError as exc:
            raise ValueError("Generated experiment indices cannot be edited as configs.") from exc
        if is_index:
            raise ValueError("Generated experiment indices cannot be edited as configs.")
    return target


def config_choices(root: Path) -> list[str]:
    root = root.resolve()
    choices = []
    for path in sorted((root / "configs").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            target = _config_path(root, str(path))
        except ValueError:
            continue
        choices.append(target.relative_to(root).as_posix())
    return choices


def _config_payload(text: str) -> dict:
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Config must contain a YAML mapping.")
    return payload


def read_config(root: Path, path: str) -> dict:
    target = _config_path(root, path)
    text = target.read_text(encoding="utf-8")
    return {"path": target.relative_to(root.resolve()).as_posix(), "text": text, "payload": _config_payload(text)}


def validate_config(root: Path, text: str) -> ExperimentConfig:
    try:
        config = ExperimentConfig.from_mapping(_config_payload(text), base_dir=root.resolve())
        config.validate()
        return config
    except (TypeError, AttributeError, KeyError, OverflowError) as exc:
        raise ValueError(f"Invalid config: {exc}") from exc


def save_config(root: Path, path: str, text: str) -> dict:
    target = _config_path(root, path)
    validate_config(root, text)
    payload = _config_payload(text)
    if target.name == "experiment.yaml" and "schema_version" not in payload and all(
        isinstance(name, str) and Path(name).suffix.lower() in {".yaml", ".yml"}
        and isinstance(run_dir, str) for name, run_dir in payload.items()
    ):
        raise ValueError("experiment.yaml is reserved for generated indices when its content has index form.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return read_config(root, str(target))


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def list_runs(runs_root: Path) -> list[dict]:
    runs = []
    for path in sorted(runs_root.glob("*/manifest.json"), reverse=True):
        manifest = _read_object(path)
        if manifest.get("schema_version") != RUN_SCHEMA_VERSION:
            continue
        runs.append({
            "path": str(path.parent.resolve()), "name": path.parent.name,
            "status": manifest.get("status", "unknown"),
            "latest_generation": manifest.get("latest_generation"),
        })
    return runs


def inspect_run(run_dir: Path) -> dict:
    if _read_object(run_dir / "manifest.json").get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError("Choose a canonical eagle-run-v2 run directory.")
    candidates = {}
    for path in sorted((run_dir / "candidates").glob("*/candidate.json")):
        payload = _read_object(path)
        candidate_id = payload.get("candidate_id")
        if candidate_id != path.parent.name or payload.get("candidate_schema_version") not in ("eagle-candidate-v6", "eagle-candidate-v7", "eagle-candidate-v8"):
            continue
        candidates[candidate_id] = payload

    def row(candidate_id: str, snapshot: dict | None = None) -> dict:
        payload = candidates.get(candidate_id, {})
        source = run_dir / "candidates" / candidate_id / "phenotype" / "CandidateAgent.java"
        item = {
            "candidate_id": candidate_id,
            "status": (snapshot or {}).get("status", payload.get("status", "unknown")),
            "watchable": bool(payload) and source.is_file(),
        }
        score = payload.get("aggregate_game_performance")
        if isinstance(score, (int, float)) and math.isfinite(score):
            item["score"] = score
        return item

    generations = []
    referenced = set()
    for path in sorted((run_dir / "generations").glob("generation_*.json")):
        match = re.fullmatch(r"generation_(\d+)\.json", path.name)
        if match is None:
            continue
        snapshot = _read_object(path)
        number = snapshot.get("generation")
        if snapshot.get("schema_version") != GENERATION_SCHEMA_VERSION or type(number) is not int or number != int(match[1]) or not isinstance(snapshot.get("population"), list):
            continue
        population = []
        for member in snapshot["population"]:
            if not isinstance(member, dict):
                continue
            candidate_id = member.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id or Path(candidate_id).name != candidate_id or candidate_id in {".", ".."} or "/" in candidate_id or "\\" in candidate_id:
                continue
            population.append(row(candidate_id, member))
            referenced.add(candidate_id)
        generations.append({"generation": number, "population": population})
    generations.sort(key=lambda item: item["generation"])
    pending = []
    for candidate_id, payload in candidates.items():
        born = payload.get("generation")
        if candidate_id not in referenced and type(born) is int and payload.get("operator") != "code_check":
            pending.append({**row(candidate_id), "generation": born})
    return {"generations": generations, "pending": pending}
