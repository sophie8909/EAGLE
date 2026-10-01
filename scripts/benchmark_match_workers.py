#!/usr/bin/env python3
"""Benchmark mock evaluation throughput for match worker counts 2 through 16."""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import evaluate_matches, preflight_evaluation_opponents
from evaluation.compiler import compile_generated_agent
from generation.java_agent_generator import GeneratedJavaAgent


def benchmark(workers: int, repeats: int, mode: str) -> tuple[float, ...]:
    durations: list[float] = []
    with tempfile.TemporaryDirectory(prefix=f"eagle-match-workers-{workers}-") as temp:
        root = Path(temp)
        source = root / "CandidateAgent.java"
        if mode == "real":
            seed = Path("eagle/java_seeds/worker_rush/CandidateAgent.java")
            shutil.copyfile(seed, source)
        else:
            source.write_text(
                "package ai.generated; public class CandidateAgent {}\n",
                encoding="utf-8",
            )
        classes = root / "classes" / "candidate"
        if mode == "real":
            compile_result = compile_generated_agent(
                source,
                microrts_dir=Path("third_party/microrts"),
                output_dir=classes,
            )
            if not compile_result.ok:
                raise RuntimeError(
                    f"benchmark candidate compilation failed: {compile_result.stderr}"
                )
        else:
            classes.mkdir(parents=True)
            (classes / "CandidateAgent.class").write_bytes(b"benchmark")
        agent = GeneratedJavaAgent(
            class_name="CandidateAgent",
            package_name="ai.generated",
            source=source.read_text(encoding="utf-8"),
            source_path=source,
        )
        config = ExperimentConfig.from_mapping(
            {"evaluation": {"match_workers": workers}}
        )
        for repeat in range(repeats):
            started = time.perf_counter()
            results, error = evaluate_matches(
                candidate=Candidate(id="candidate"),
                agent=agent,
                config=config,
                classes_dir=root / "classes",
                match_artifacts_dir=root / f"matches-{repeat}",
                mock=mode == "mock",
                ordinal=repeat,
            )
            if error is not None or len(results) != config.expected_match_count:
                raise RuntimeError(
                    f"worker benchmark failed for {workers}: "
                    f"error={error!r}, results={len(results)}"
                )
            durations.append(time.perf_counter() - started)
    return tuple(durations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-workers", type=int, default=2)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--mode", choices=("mock", "real"), default="mock")
    args = parser.parse_args()
    if not 1 <= args.min_workers <= args.max_workers:
        parser.error("worker range must satisfy 1 <= min-workers <= max-workers")
    if args.repeats < 1:
        parser.error("repeats must be at least 1")
    if args.mode == "real":
        preflight_evaluation_opponents(
            ExperimentConfig.from_mapping({}),
            mock=False,
            repository_root=Path.cwd(),
        )

    measurements: list[tuple[int, tuple[float, ...], float]] = []
    for workers in range(args.min_workers, args.max_workers + 1):
        durations = benchmark(workers, args.repeats, args.mode)
        median = statistics.median(durations)
        measurements.append((workers, durations, median))
        values = ", ".join(f"{value:.3f}s" for value in durations)
        print(
            f"mode={args.mode} workers={workers:2d} "
            f"median={median:.3f}s samples=[{values}]"
        )

    best_workers, _, best_median = min(measurements, key=lambda item: item[2])
    print(f"mode={args.mode} best_workers={best_workers} median={best_median:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
