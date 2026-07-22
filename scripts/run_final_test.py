"""Run post-evolution EAGLE final tests against pinned champion agents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from eagle.final_test.runner import execute_final_test


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate already generated Java from a completed EAGLE run against pinned "
            "TMA, Mayari, and COAC opponents. No LLM or evolutionary operator is used."
        )
    )
    parser.add_argument("--run-dir", type=Path, required=True, help="Completed runs/<run_id> directory")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--candidate-id", help="Test exactly one evaluated candidate")
    selection.add_argument(
        "--selector",
        choices=("best-game-performance", "balanced", "pareto"),
        help="Select candidates using evolution artifacts only",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=REPOSITORY_ROOT / "configs" / "final_test_champions.yaml",
    )
    parser.add_argument("--final-test-id", help="Optional stable output directory name")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run all three opponents on the first map/seed and both player sides (6 matches)",
    )
    args = parser.parse_args()
    try:
        outcome = execute_final_test(
            run_dir=args.run_dir,
            config_path=args.config,
            repository_root=REPOSITORY_ROOT,
            selector=args.selector,
            candidate_id=args.candidate_id,
            final_test_id=args.final_test_id,
            smoke=args.smoke,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"final_test_dir={outcome.final_test_dir}")
    print(f"completed_matches={outcome.completed_matches}/{outcome.expected_matches}")
    return 0 if outcome.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
