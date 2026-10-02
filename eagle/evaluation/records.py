"""Typed results shared by EAGLE evaluation stages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eagle.candidate import Candidate
from eagle.evaluation.code_quality import CodeQualityBreakdown, StrategyRegionScoreResult
from eagle.evaluation.compiler import CompileResult
from eagle.evaluation.function_capability import FunctionCapabilityResult
from eagle.evaluation.game_metrics import GameMetrics
from eagle.evaluation.microrts_runner import IntegrationResult
from eagle.evaluation.runtime_evaluation import MatchResult
from eagle.evaluation.semantic_signature import SemanticSignatureResult
from eagle.evaluation.strategy_alignment import StrategyAlignmentResult
from eagle.generation.java_agent_generator import (
    GeneratedJavaAgent,
    JavaAgentGenerationResult,
    ValidationResult,
)


@dataclass(frozen=True)
class CandidateEvaluation:
    """In-memory envelope joining stage results for one evaluated candidate.

    ``candidate`` is the compact state passed back to search. The remaining
    fields are typed evidence needed by artifact writers and progress reports
    before large runtime payloads are compacted.
    """

    candidate: Candidate
    result: "CandidateResult"
    agent: GeneratedJavaAgent | None
    compile_result: CompileResult | None
    integration_result: IntegrationResult | None
    match_results: list[MatchResult]
    game_metrics: GameMetrics | None
    strategy_consistency_result: object | None
    code_quality_breakdown: CodeQualityBreakdown
    strategy_region_score_result: StrategyRegionScoreResult | None
    error: str | None = None
    function_capability_result: FunctionCapabilityResult | None = None
    strategy_alignment_result: StrategyAlignmentResult | None = None
    generation_timing: dict[str, object] | None = None
    generation_attempts: tuple["GenerationAttemptResult", ...] = ()
    semantic_signature_result: SemanticSignatureResult | None = None


@dataclass(frozen=True)
class GenerationAttemptResult:
    """One decoder-chain step with validation and at-most-once javac."""

    attempt: int
    request: str
    generation: JavaAgentGenerationResult
    compile_result: CompileResult | None
    compile_error: str | None
    generation_timing: dict[str, object]
    compilation_timing: dict[str, object]
    request_kind: str = "initial_decode"
    repair_parent_attempt: int | None = None
    repair_evidence: dict[str, object] | None = None
    selected: bool = False
    final: bool = False


@dataclass(frozen=True)
class BoundedGenerationResult:
    """Production result shared by smoke checks and full evaluation."""

    attempts: tuple[GenerationAttemptResult, ...]
    selected_attempt: int | None
    final_attempt: int
    max_attempts: int
    initial_seed_source: bool
    source_without_generation: bool

    @property
    def representative_attempt(self) -> GenerationAttemptResult:
        """Return the selected success or, on exhaustion, the final failure."""

        number = self.selected_attempt or self.final_attempt
        return next(item for item in self.attempts if item.attempt == number)

    @property
    def generation(self) -> JavaAgentGenerationResult:
        return self.representative_attempt.generation

    @property
    def compile_result(self) -> CompileResult | None:
        return self.representative_attempt.compile_result

    @property
    def compile_error(self) -> str | None:
        return self.representative_attempt.compile_error


@dataclass(frozen=True)
class EvaluationOpponent:
    opponent_id: str
    class_name: str
    classpath_entries: tuple[Path, ...] = ()
    weight: float = 1.0
    display_name: str | None = None
    source_generation: int | None = None
    source_candidate_id: str | None = None


@dataclass(frozen=True)
class CandidateResult:
    """Persistable result record produced by the complete child pipeline."""

    candidate_id: str
    parent_ids: tuple[str, ...]
    raw_llm_output: str = ""
    extracted_code: str = ""
    assembled_java: str = ""
    strategy_region: str = ""
    validation_result: ValidationResult | None = None
    strategy_region_validation: dict[str, dict] | None = None
    compile_result: CompileResult | None = None
    strategy_consistency: dict | None = None
    code_quality_breakdown: dict | None = None
    match_result: list[MatchResult] | None = None
    function_capability: dict | None = None
    strategy_alignment: dict | None = None
    game_metrics: dict[str, object] | None = None
    final_score: dict[str, float] | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    integration_result: IntegrationResult | None = None
    failure_stage: str | None = None
