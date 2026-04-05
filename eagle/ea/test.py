"""Backward-compatible re-exports for helpers that now live in final_evaluation."""

from .final_evaluation import (
    extract_prompts_from_ea_log,
    parse_individuals_from_ea_log,
    run_final_test_suite,
)


if __name__ == "__main__":
    current_log_dir = "20240930_123456"
    last_gen = 10
    run_final_test_suite(current_log_dir, last_gen)
