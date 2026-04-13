"""Evaluation, replay, and final-test utilities for EAGLE."""

from .evaluator import Evaluator
from .final_test_report import (
    format_final_test_summary,
    load_results_file,
    summarize_final_test_results,
)
from .final_test_runner import run_final_test_suite
from .generation_replay import (
    build_result_record,
    extract_individual_ids_up_to_front,
    run_generation_result_test,
)

__all__ = [
    "Evaluator",
    "build_result_record",
    "extract_individual_ids_up_to_front",
    "format_final_test_summary",
    "load_results_file",
    "run_final_test_suite",
    "run_generation_result_test",
    "summarize_final_test_results",
]
