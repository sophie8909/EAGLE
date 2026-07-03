"""Run the minimal EAGLE prompt-to-Java pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eagle.config import ExperimentConfig
from eagle.search import run_search


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EAGLE generated-agent search.")
    parser.add_argument("--config", default="configs/eagle_minimal.yaml")
    parser.add_argument("--mock", action="store_true", help="Use mock generation, compile, and MicroRTS evaluation.")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    config_path = Path(args.config)
    config = ExperimentConfig.from_file(config_path)
    result = run_search(config, config_path=config_path, mock=args.mock, run_id=args.run_id)
    best = result.best_candidate
    best_text = "none" if best is None else f"{best.id} fitness={best.fitness}"
    print(f"run_dir={result.run_dir}")
    print(f"best_candidate={best_text}")


if __name__ == "__main__":
    main()
