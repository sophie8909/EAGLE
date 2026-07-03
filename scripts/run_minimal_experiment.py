"""Run the minimal prompt-to-Java EAGLE experiment."""

from __future__ import annotations

import argparse
import json

from eagle.config import ExperimentConfig
from eagle.experiment import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal EAGLE prompt-to-Java experiment.")
    parser.add_argument("--config", default="configs/minimal_experiment.json")
    args = parser.parse_args()

    config = ExperimentConfig.from_json(args.config)
    results = run_experiment(config)
    payload = [
        {
            "candidate_id": result.candidate.candidate_id,
            "fitness": result.fitness,
            "artifacts": result.artifacts,
        }
        for result in results
    ]
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

