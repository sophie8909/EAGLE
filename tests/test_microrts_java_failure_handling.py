"""Tests for controlled MicroRTS Java process failure handling."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from eagle.eval.microrts.evaluator_parts import (
    MICRORTS_JAVA_FAILURE_TYPE,
    JavaMatchEvaluator,
)


def _evaluator() -> JavaMatchEvaluator:
    evaluator = JavaMatchEvaluator.__new__(JavaMatchEvaluator)
    evaluator.config = SimpleNamespace(win_bonus=100.0)
    evaluator.config.set_active_llm_interval = lambda value: setattr(evaluator.config, "_active_llm_interval", value)
    return evaluator


def test_java_process_failure_becomes_failed_match_result(caplog: pytest.LogCaptureFixture) -> None:
    evaluator = _evaluator()

    def callback() -> tuple[dict[str, float], dict]:
        raise RuntimeError("MicroRTS Java process failed.\nexit_code=1\nlog_path=D:/run.log")

    with caplog.at_level(logging.WARNING):
        match_score, simulation_meta = evaluator._with_llm_interval(
            None,
            callback,
            opponent="bad",
            individual_id="ind-1",
            generation=3,
        )

    assert match_score == {"win_score": -1.0, "raw_resource_advantage_score": -100.0}
    assert simulation_meta["failed"] is True
    assert simulation_meta["failure_type"] == MICRORTS_JAVA_FAILURE_TYPE
    assert simulation_meta["exit_code"] == 1
    assert simulation_meta["log_path"] == "D:/run.log"
    assert "individual_id=ind-1" in caplog.text
    assert "generation=3" in caplog.text
    assert "opponent=bad" in caplog.text
    assert "log_path=D:/run.log" in caplog.text
    assert "exit_code=1" in caplog.text


def test_unrelated_runtime_error_still_propagates() -> None:
    evaluator = _evaluator()

    def callback() -> tuple[dict[str, float], dict]:
        raise RuntimeError("unexpected parser bug")

    with pytest.raises(RuntimeError, match="unexpected parser bug"):
        evaluator._with_llm_interval(
            None,
            callback,
            opponent="bad",
            individual_id="ind-1",
            generation=3,
        )
