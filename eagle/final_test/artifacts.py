"""Versioned final-test artifact writers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def create_final_test_directory(run_dir: Path, output_directory: str, final_test_id: str) -> Path:
    root = (run_dir / output_directory / final_test_id).resolve()
    expected_parent = (run_dir / output_directory).resolve()
    if root.parent != expected_parent:
        raise ValueError("final_test_id must be one safe path component.")
    root.mkdir(parents=True, exist_ok=False)
    return root


def copy_input_config(config_path: Path, final_test_dir: Path) -> Path:
    destination = final_test_dir / "config.yaml"
    shutil.copy2(config_path, destination)
    return destination


def copy_candidate_source(source_path: Path, final_test_dir: Path, candidate_id: str) -> Path:
    destination = final_test_dir / "candidate_sources" / candidate_id / "CandidateAgent.java"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return destination


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")
        handle.flush()

