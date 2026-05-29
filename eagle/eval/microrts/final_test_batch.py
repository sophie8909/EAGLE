"""Compatibility wrapper for MicroRTS final-test batches."""

from eagle.plugins.microrts.evaluation.final_test_batch import *  # noqa: F403
from eagle.plugins.microrts.evaluation.final_test_batch import (
    _build_failed_result_record,
    _build_raw_result_record,
)

__all__ = [
    name
    for name in globals()
    if not name.startswith("_") or name in {"_build_failed_result_record", "_build_raw_result_record"}
]
