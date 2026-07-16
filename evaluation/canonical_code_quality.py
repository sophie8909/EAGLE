"""Canonical failure-aware and successful Code Quality scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .compiler import CompileResult, parse_compiler_diagnostics
from .function_capability import FunctionCapabilityResult
from .strategy_alignment import StrategyAlignmentResult


SUCCESSFUL_BASE = 500.0
OBJECTIVE_FORMULA_VERSION = "eagle-objectives-phase4-v1"


@dataclass(frozen=True)
class CompilerDiagnostics:
    compile_success: bool
    compile_error_count: int
    warning_count: int
    compilation_score: float
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["errors"] = list(self.errors)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class CodeQualityBreakdown:
    compilation_score: float
    function_score: float
    strategy_alignment_score: float
    successful_base: float
    score: float
    warning_count: int
    compile_success: bool
    compile_error_count: int
    failure_stage: str | None = None
    compiler_errors: tuple[str, ...] = ()
    compiler_warnings: tuple[str, ...] = ()
    function_capability: dict[str, Any] | None = None
    strategy_alignment: dict[str, Any] | None = None
    objective_formula_version: str = OBJECTIVE_FORMULA_VERSION
    strategy_region_score: float = 0.0
    static_quality_score: float = 0.0
    required_region_count: int = 0
    valid_region_count: int = 0
    strategy_region_validation: dict[str, Any] | None = None
    static_metrics: Any | None = None

    @property
    def code_quality(self) -> float:
        return round(self.score, 6)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code_quality"] = self.code_quality
        payload["compiler_errors"] = list(self.compiler_errors)
        payload["compiler_warnings"] = list(self.compiler_warnings)
        return payload


def analyze_compilation(result: CompileResult | None) -> CompilerDiagnostics:
    if result is None:
        return CompilerDiagnostics(
            False,
            0,
            0,
            0.0,
            errors=("Compilation was not run.",),
        )
    diagnostics = result.diagnostics or parse_compiler_diagnostics(f"{result.stdout}\n{result.stderr}")
    warning_items = tuple(item for item in diagnostics if item.severity == "warning")
    error_items = tuple(item for item in diagnostics if item.severity == "error")
    warnings = tuple(item.message for item in warning_items)
    errors = tuple(item.message for item in error_items)
    warning_count = len(warning_items)
    compilation_score = max(-500.0, -50.0 * warning_count) if result.ok else 0.0
    return CompilerDiagnostics(
        compile_success=result.ok,
        compile_error_count=len(error_items),
        warning_count=warning_count,
        compilation_score=compilation_score,
        errors=errors or (() if result.ok else ((result.stderr or "javac failed").strip(),)),
        warnings=warnings,
    )


def build_successful_code_quality(
    compiler: CompilerDiagnostics,
    capability: FunctionCapabilityResult,
    alignment: StrategyAlignmentResult,
) -> CodeQualityBreakdown:
    if not compiler.compile_success:
        raise ValueError("successful Code Quality requires successful compilation")
    score = SUCCESSFUL_BASE + compiler.compilation_score + capability.function_score + alignment.score
    return CodeQualityBreakdown(
        compilation_score=compiler.compilation_score,
        function_score=float(capability.function_score),
        strategy_alignment_score=float(alignment.score),
        successful_base=SUCCESSFUL_BASE,
        score=score,
        warning_count=compiler.warning_count,
        compile_success=True,
        compile_error_count=0,
        compiler_errors=compiler.errors,
        compiler_warnings=compiler.warnings,
        function_capability=capability.to_json_dict(),
        strategy_alignment=alignment.to_json_dict(),
    )


def build_failure_code_quality(
    failure_stage: str,
    *,
    compiler: CompilerDiagnostics | None = None,
    integration_pass_ratio: float = 0.0,
    completed_matches: int = 0,
) -> CodeQualityBreakdown:
    diagnostics = compiler or CompilerDiagnostics(False, 0, 0, 0.0)
    score = failure_code_quality(
        failure_stage,
        error_count=diagnostics.compile_error_count,
        integration_pass_ratio=integration_pass_ratio,
        completed_matches=completed_matches,
    )
    return CodeQualityBreakdown(
        compilation_score=diagnostics.compilation_score,
        function_score=0.0,
        strategy_alignment_score=0.0,
        successful_base=0.0,
        score=score,
        warning_count=diagnostics.warning_count,
        compile_success=diagnostics.compile_success,
        compile_error_count=diagnostics.compile_error_count,
        failure_stage=failure_stage,
        compiler_errors=diagnostics.errors,
        compiler_warnings=diagnostics.warnings,
    )


def failure_code_quality(
    failure_stage: str,
    *,
    error_count: int = 0,
    integration_pass_ratio: float = 0.0,
    completed_matches: int = 0,
) -> float:
    if failure_stage == "generation":
        return -1000.0
    if failure_stage == "validation":
        return -950.0
    if failure_stage == "compilation":
        return float(-800 - min(max(0, error_count) * 5, 100))
    if failure_stage == "integration":
        ratio = min(1.0, max(0.0, integration_pass_ratio))
        return float(-600 + round(ratio * 100))
    if failure_stage == "runtime":
        progress = min(9, max(0, completed_matches)) / 10.0
        return float(-400 + round(progress * 199))
    raise ValueError(f"Unknown failure stage: {failure_stage}")


def build_code_quality(
    compiler: CompilerDiagnostics,
    *_: Any,
    capability: FunctionCapabilityResult | None = None,
    alignment: StrategyAlignmentResult | None = None,
) -> CodeQualityBreakdown:
    """Compatibility entrypoint; orchestration should use the explicit builders."""

    if not compiler.compile_success:
        return build_failure_code_quality("compilation", compiler=compiler)
    if capability is None or alignment is None:
        return CodeQualityBreakdown(
            compilation_score=compiler.compilation_score,
            function_score=0.0,
            strategy_alignment_score=0.0,
            successful_base=SUCCESSFUL_BASE,
            score=SUCCESSFUL_BASE + compiler.compilation_score,
            warning_count=compiler.warning_count,
            compile_success=True,
            compile_error_count=0,
            compiler_errors=compiler.errors,
            compiler_warnings=compiler.warnings,
        )
    return build_successful_code_quality(compiler, capability, alignment)
