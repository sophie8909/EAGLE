"""Fitness calculation for generated Java agent candidates."""

from __future__ import annotations

from .compiler import CompileResult
from .microrts_runner import MatchResult


def calculate_fitness(compile_result: CompileResult, match_results: list[MatchResult]) -> float:
    if not compile_result.ok:
        return 0.0
    successful_scores = [result.score for result in match_results if result.ok]
    if not successful_scores:
        return 0.0
    return sum(successful_scores) / len(successful_scores)
