"""Backward-compatible re-exports for helpers moved into parsing/evaluation modules."""

from .ea_log_parse import (
    extract_prompts_from_ea_log,
    parse_individuals_from_ea_log,
)
from .final_evaluation import (
    run_final_test_suite,
)


if __name__ == "__main__":
    current_log_dir = "20240930_123456"
    last_gen = 10
    run_final_test_suite(current_log_dir, last_gen)
