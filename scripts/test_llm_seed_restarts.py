#!/usr/bin/env python3
"""Restart llama-server for each seed and compare repeated LLM responses."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.llm import LLMClient, LLMServerError
from eagle.llm_stability import StabilityResult, run_stability_test, write_stability_matrix
from eagle.runtime import RuntimeManager, runtime_config_from_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Experiment YAML/JSON config")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="Exact prompt to repeat")
    prompt_group.add_argument("--prompt-file", type=Path, help="UTF-8 file containing the exact prompt")
    parser.add_argument("--seeds", required=True, help="Comma-separated seeds, for example 7,8,9")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Report directory (default: runs/llm_stability_restart/<UTC timestamp>)",
    )
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")
    seeds = _parse_seeds(args.seeds)

    config = ExperimentConfig.from_file(args.config)
    prompt = args.prompt if args.prompt is not None else args.prompt_file.read_text(encoding="utf-8")
    output_dir = args.output_dir or (
        config.runs_dir
        / "llm_stability_restart"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    runtime = runtime_config_from_experiment(config, phase="reflection")
    manager = RuntimeManager(runtime)
    metadata = {
        "config": str(args.config.resolve()),
        "endpoint": runtime.llm.base_url,
        "model": config.llm_model,
        "temperature": config.llm_temperature,
        "request_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "server_restart_per_seed": True,
        "repeats": args.repeats,
    }
    results: dict[int, StabilityResult] = {}
    lifecycle: list[dict[str, object]] = []
    try:
        manager.check()
        for index, seed in enumerate(seeds, start=1):
            started_at = datetime.now(timezone.utc).isoformat()
            print(f"[{index}/{len(seeds)}] starting llama-server seed={seed}", flush=True)
            status = manager.start()
            lifecycle_entry: dict[str, object] = {
                "seed": seed,
                "restart_index": index,
                "server_pid": status.pid,
                "started_at": started_at,
                "start_action": status.action,
            }
            try:
                client = LLMClient(
                    config.llm_base_url,
                    config.llm_model,
                    temperature=config.llm_temperature,
                    max_output_tokens=config.llm_max_tokens,
                    seed=seed,
                )
                backend = client.prompt_backend(operation="stability_restart_test")
                result = run_stability_test(
                    lambda backend=backend: backend.generate(prompt),
                    repeats=args.repeats,
                )
                results[seed] = result
                lifecycle_entry.update({
                    "status": "completed",
                    "stable_within_seed": result.stable,
                    "unique_response_count": len(set(result.response_hashes)),
                })
                print(
                    f"seed={seed} stable={result.stable} "
                    f"unique_responses={len(set(result.response_hashes))}",
                    flush=True,
                )
            finally:
                stopped_at = datetime.now(timezone.utc).isoformat()
                manager.stop_owned()
                lifecycle_entry["stopped_at"] = stopped_at
                lifecycle.append(lifecycle_entry)
                print(f"stopped llama-server seed={seed}", flush=True)
    except (OSError, RuntimeError, LLMServerError) as exc:
        try:
            manager.stop_owned()
        except RuntimeError:
            pass
        parser.exit(1, f"LLM seed-restart test failed: {exc}\n")

    matrix_path = write_stability_matrix(
        output_dir,
        results,
        metadata={**metadata, "seeds": seeds},
        matrix_metadata={"server_lifecycle": lifecycle},
    )
    first_hashes = [result.response_hashes[0] for result in results.values()]
    cross_seed_changed = len(set(first_hashes)) > 1
    print(
        f"same_seed_stable={all(result.stable for result in results.values())} "
        f"cross_seed_changed={cross_seed_changed} matrix={matrix_path}"
    )
    return 0 if all(result.stable for result in results.values()) and cross_seed_changed else 2


def _parse_seeds(raw: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise SystemExit(f"invalid --seeds value: {raw!r}") from exc
    if not seeds:
        raise SystemExit("--seeds must contain at least one integer")
    if len(set(seeds)) != len(seeds):
        raise SystemExit("--seeds must not contain duplicates")
    return seeds


if __name__ == "__main__":
    raise SystemExit(main())
