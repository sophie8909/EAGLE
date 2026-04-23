"""Shared helpers for replay-style evaluation flows."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import EAConfig, clone_config, load_config_from_json
from ..project import DEFAULT_FINAL_TEST_CONFIG_PATH


def load_override_payload(config_path: str | Path | None = None) -> dict:
    """Load the optional replay/final-test override JSON payload."""
    candidate_path = Path(config_path) if config_path is not None else DEFAULT_FINAL_TEST_CONFIG_PATH
    if not candidate_path.exists():
        return {}
    return json.loads(candidate_path.read_text(encoding="utf-8"))


def load_runtime_config(log_dir: str | Path, config_path: str | Path | None = None) -> EAConfig:
    """Load the saved run config and overlay replay-specific runtime settings."""
    run_config = load_config_from_json(log_dir)
    return apply_runtime_overrides(run_config, config_path)


def apply_runtime_overrides(
    base_config: EAConfig,
    config_path: str | Path | None = None,
) -> EAConfig:
    """Apply replay/final-test-specific runtime overrides onto one base config."""
    payload = load_override_payload(config_path)
    resolved = clone_config(base_config)
    if "run_time_per_game_sec" in payload:
        resolved.run_time_per_game_sec = int(payload["run_time_per_game_sec"])
    if "llm_interval" in payload:
        resolved.llm_interval = int(payload["llm_interval"])
    if "save_trace_on_test" in payload:
        resolved.save_trace_on_test = bool(payload["save_trace_on_test"])
    resolved.validate()
    return resolved


def build_interval_runs(config_path: str | Path | None, fallback_llm_interval: int) -> list[dict[str, int | str]]:
    """Resolve the replay llm-interval sweep from config or fallback value."""
    payload = load_override_payload(config_path)
    configured_intervals = payload.get("llm_intervals")
    if configured_intervals is None:
        configured_intervals = [int(fallback_llm_interval)]

    interval_runs: list[dict[str, int | str]] = []
    seen_intervals: set[int] = set()
    for llm_interval in configured_intervals:
        interval_value = int(llm_interval)
        if interval_value in seen_intervals:
            continue
        seen_intervals.add(interval_value)
        interval_runs.append(
            {
                "label": f"interval_{interval_value}",
                "llm_interval": interval_value,
            }
        )
    return interval_runs


def write_results_snapshot(results: dict, destination: str | Path) -> None:
    """Write one replay/final-test result payload to disk."""
    output_path = Path(destination)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
