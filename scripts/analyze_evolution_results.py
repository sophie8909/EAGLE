"""CLI wrapper for plotting EAGLE evolution and final-test results."""

from __future__ import annotations

import argparse
import sys


def _extract_eval_mode(argv: list[str]) -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--eval-mode",
        choices=["real", "surrogate", "round"],
        default="real",
    )

    known_args, remaining_argv = parser.parse_known_args(argv)
    return known_args.eval_mode, remaining_argv


def _patch_ea_log_parser(eval_mode: str) -> None:
    import eagle.analysis.evolution_result_analysis as analysis

    if eval_mode == "round":
        from eagle_round_evol.ea_log_parse import (
            parse_individuals_from_ea_log,
            parse_population_snapshot_from_ea_log,
        )
    else:
        from eagle.utils.ea_log_parse import (
            parse_individuals_from_ea_log,
            parse_population_snapshot_from_ea_log,
        )

    analysis.parse_individuals_from_ea_log = parse_individuals_from_ea_log
    analysis.parse_population_snapshot_from_ea_log = parse_population_snapshot_from_ea_log


def main() -> None:
    eval_mode, original_argv = _extract_eval_mode(sys.argv[1:])
    _patch_ea_log_parser(eval_mode)

    import eagle.analysis.evolution_result_analysis as analysis

    # Keep --eval-mode for the downstream analysis parser.
    sys.argv = [sys.argv[0], "--eval-mode", eval_mode, *original_argv]
    analysis.main()


if __name__ == "__main__":
    main()