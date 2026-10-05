#!/usr/bin/env python3
"""Check whether repeated identical requests produce identical LLM responses."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from eagle.config import ExperimentConfig
from eagle.llm import LLMClient
from eagle.llm_stability import run_stability_test, write_stability_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Experiment YAML/JSON config")
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="Exact prompt to repeat")
    prompt_group.add_argument("--prompt-file", type=Path, help="UTF-8 file containing the exact prompt")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Report directory (default: runs/llm_stability/<UTC timestamp>)",
    )
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")

    config = ExperimentConfig.from_file(args.config)
    prompt = args.prompt if args.prompt is not None else args.prompt_file.read_text(encoding="utf-8")
    output_dir = args.output_dir or (
        config.runs_dir
        / "llm_stability"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    client = LLMClient(
        config.llm_base_url,
        config.llm_model,
        temperature=config.llm_temperature,
        max_output_tokens=config.llm_max_tokens,
        seed=config.random_seed,
    )
    backend = client.prompt_backend(operation="stability_test")
    result = run_stability_test(lambda: backend.generate(prompt), repeats=args.repeats)
    report_path = write_stability_report(
        output_dir,
        result,
        metadata={
            "config": str(args.config.resolve()),
            "endpoint": client.base_url,
            "model": client.model,
            "temperature": client.temperature,
            "sampling_seed": client.seed,
            "request_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        },
    )
    print(
        f"stable={result.stable} repeats={result.repeats} "
        f"unique_responses={len(set(result.response_hashes))} report={report_path}"
    )
    return 0 if result.stable else 2


if __name__ == "__main__":
    raise SystemExit(main())
