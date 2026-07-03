"""Shared project-level paths for the EAGLE repository."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = PROJECT_ROOT / "configs"
EVOLUTION_CONFIGS_DIR = CONFIGS_DIR / "evolution"
EVALUATION_CONFIGS_DIR = CONFIGS_DIR / "evaluation"
EXPERIMENT_CONFIGS_DIR = CONFIGS_DIR / "experiments"
LOGS_DIR = PROJECT_ROOT / "logs"
EAGLE_LOGS_DIR = LOGS_DIR / "eagle"
MICRORTS_LOGS_DIR = LOGS_DIR / "microrts"
RESPONSES_DIR = LOGS_DIR / "responses"
RESULTS_DIR = PROJECT_ROOT / "results"
HISTORY_DIR = PROJECT_ROOT / "history"
THIRD_PARTY_DIR = PROJECT_ROOT / "third_party"
MICRORTS_ROOT = THIRD_PARTY_DIR / "microrts"
PROMPTS_DIR = PROJECT_ROOT / "eagle" / "prompts"
DEFAULT_EVOLUTION_CONFIG_PATH = EVOLUTION_CONFIGS_DIR / "default.json"
DEFAULT_SURROGATE_VALIDATION_CONFIG_PATH = EVALUATION_CONFIGS_DIR / "surrogate_validation.json"
DEFAULT_FINAL_TEST_CONFIG_PATH = EVALUATION_CONFIGS_DIR / "final_test.json"


def ensure_directory(path: Path, *, tolerate_file: bool = False) -> Path:
    """Create one directory unless a file already occupies the path."""
    if path.exists():
        if path.is_dir():
            return path
        if tolerate_file:
            return path
        raise NotADirectoryError(
            f"Expected directory at {path}, but found a file. "
            "Rename or move the file before using this path as a directory."
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_project_directories(*, include_responses: bool = False) -> None:
    """Create the standard output directories when they are missing."""
    for path in (LOGS_DIR, EAGLE_LOGS_DIR, MICRORTS_LOGS_DIR, RESULTS_DIR, HISTORY_DIR):
        ensure_directory(path)
    if include_responses:
        ensure_directory(RESPONSES_DIR)
