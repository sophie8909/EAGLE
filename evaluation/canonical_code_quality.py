"""Canonical Code Quality / Simplicity objective scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .code_quality import StaticCodeMetrics, analyze_static_code
from .compiler import CompileResult, parse_compiler_diagnostics
from .function_capability import FunctionCapabilityResult
from .strategy_alignment import StrategyAlignmentResult


FAILED_CODE_QUALITY = -1000.0
OBJECTIVE_FORMULA_VERSION = "eagle-objectives-simplicity-v1"
METRIC_VERSION = "1"
MEASURED_SOURCE = "candidate_generated_methods"


@dataclass(frozen=True)
class CompilerDiagnostics:
    compile_success: bool
    compile_error_count: int
    warning_count: int
    # Retained as a diagnostic compatibility field; it is not part of valid scoring.
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
    # These fields remain persisted diagnostics, not score components.
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
    static_metrics: StaticCodeMetrics | None = None
    complexity_penalty: float = 0.0
    cyclomatic_complexity: int = 0
    maximum_nesting_depth: int = 0
    logical_loc: int = 0
    longest_function_loc: int = 0
    cyclomatic_penalty: float = 0.0
    nesting_penalty: float = 0.0
    logical_loc_penalty: float = 0.0
    longest_function_penalty: float = 0.0
    metric_version: str = METRIC_VERSION
    measured_source: str = MEASURED_SOURCE

    @property
    def code_quality(self) -> float:
        return round(self.score, 6)

    @property
    def code_quality_details(self) -> dict[str, Any]:
        return {
            "complexity_penalty": self.complexity_penalty,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "maximum_nesting_depth": self.maximum_nesting_depth,
            "logical_loc": self.logical_loc,
            "longest_function_loc": self.longest_function_loc,
            "cyclomatic_penalty": self.cyclomatic_penalty,
            "nesting_penalty": self.nesting_penalty,
            "logical_loc_penalty": self.logical_loc_penalty,
            "longest_function_penalty": self.longest_function_penalty,
            "metric_version": self.metric_version,
            "measured_source": self.measured_source,
        }

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code_quality"] = self.code_quality
        payload["code_quality_details"] = self.code_quality_details
        payload["compiler_errors"] = list(self.compiler_errors)
        payload["compiler_warnings"] = list(self.compiler_warnings)
        return payload


def analyze_compilation(result: CompileResult | None) -> CompilerDiagnostics:
    if result is None:
        return CompilerDiagnostics(False, 0, 0, 0.0, errors=("Compilation was not run.",))
    diagnostics = result.diagnostics or parse_compiler_diagnostics(f"{result.stdout}\n{result.stderr}")
    warning_items = tuple(item for item in diagnostics if item.severity == "warning")
    error_items = tuple(item for item in diagnostics if item.severity == "error")
    warnings = tuple(item.message for item in warning_items)
    errors = tuple(item.message for item in error_items)
    return CompilerDiagnostics(
        compile_success=result.ok,
        compile_error_count=len(error_items),
        warning_count=len(warning_items),
        compilation_score=0.0,
        errors=errors or (() if result.ok else ((result.stderr or "javac failed").strip(),)),
        warnings=warnings,
    )


def _clamp_normalized(value: float, upper: float) -> float:
    return min(1.0, max(0.0, value / upper))


def _complexity_details(metrics: StaticCodeMetrics) -> dict[str, Any]:
    normalized_cyclomatic = _clamp_normalized(max(0, metrics.cyclomatic_complexity - 1), 39.0)
    normalized_nesting = _clamp_normalized(max(0, metrics.max_nesting_depth - 1), 9.0)
    normalized_logical_loc = _clamp_normalized(max(0, metrics.logical_loc - 1), 299.0)
    normalized_longest_function = _clamp_normalized(max(0, metrics.longest_function_loc - 1), 119.0)
    penalties = {
        "cyclomatic_penalty": round(40.0 * normalized_cyclomatic, 6),
        "nesting_penalty": round(25.0 * normalized_nesting, 6),
        "logical_loc_penalty": round(20.0 * normalized_logical_loc, 6),
        "longest_function_penalty": round(15.0 * normalized_longest_function, 6),
    }
    penalties["complexity_penalty"] = round(min(100.0, max(0.0, sum(penalties.values()))), 6)
    return {
        **penalties,
        "cyclomatic_complexity": metrics.cyclomatic_complexity,
        "maximum_nesting_depth": metrics.max_nesting_depth,
        "logical_loc": metrics.logical_loc,
        "longest_function_loc": metrics.longest_function_loc,
    }


def _build_breakdown(
    *,
    compiler: CompilerDiagnostics,
    metrics: StaticCodeMetrics | None,
    score: float,
    failure_stage: str | None,
    capability: FunctionCapabilityResult | None = None,
    alignment: StrategyAlignmentResult | None = None,
    strategy_region: Any | None = None,
) -> CodeQualityBreakdown:
    metrics = metrics or analyze_static_code({})
    details = _complexity_details(metrics)
    return CodeQualityBreakdown(
        compilation_score=0.0,
        function_score=0.0 if capability is None else float(capability.function_score),
        strategy_alignment_score=0.0 if alignment is None else float(alignment.score),
        successful_base=0.0,
        score=round(score, 6),
        warning_count=compiler.warning_count,
        compile_success=compiler.compile_success,
        compile_error_count=compiler.compile_error_count,
        failure_stage=failure_stage,
        compiler_errors=compiler.errors,
        compiler_warnings=compiler.warnings,
        function_capability=None if capability is None else capability.to_json_dict(),
        strategy_alignment=None if alignment is None else alignment.to_json_dict(),
        strategy_region_score=0.0 if strategy_region is None else float(strategy_region.strategy_region_score),
        static_quality_score=metrics.static_quality_score,
        required_region_count=0 if strategy_region is None else strategy_region.required_region_count,
        valid_region_count=0 if strategy_region is None else strategy_region.valid_region_count,
        strategy_region_validation=None if strategy_region is None else {
            key: value.to_json_dict() for key, value in strategy_region.strategy_region_validation.items()
        },
        static_metrics=metrics,
        complexity_penalty=details["complexity_penalty"],
        cyclomatic_complexity=details["cyclomatic_complexity"],
        maximum_nesting_depth=details["maximum_nesting_depth"],
        logical_loc=details["logical_loc"],
        longest_function_loc=details["longest_function_loc"],
        cyclomatic_penalty=details["cyclomatic_penalty"],
        nesting_penalty=details["nesting_penalty"],
        logical_loc_penalty=details["logical_loc_penalty"],
        longest_function_penalty=details["longest_function_penalty"],
    )


def build_successful_code_quality(
    compiler: CompilerDiagnostics,
    capability: FunctionCapabilityResult | None = None,
    alignment: StrategyAlignmentResult | None = None,
    *,
    strategy_regions: dict[str, str] | None = None,
    strategy_region: Any | None = None,
) -> CodeQualityBreakdown:
    if not compiler.compile_success:
        raise ValueError("successful Code Quality requires successful compilation")
    metrics = analyze_static_code(strategy_regions or {})
    details = _complexity_details(metrics)
    return _build_breakdown(
        compiler=compiler,
        metrics=metrics,
        score=100.0 - details["complexity_penalty"],
        failure_stage=None,
        capability=capability,
        alignment=alignment,
        strategy_region=strategy_region,
    )


def build_failure_code_quality(
    failure_stage: str,
    *,
    compiler: CompilerDiagnostics | None = None,
    integration_pass_ratio: float = 0.0,
    completed_matches: int = 0,
    strategy_regions: dict[str, str] | None = None,
    strategy_region: Any | None = None,
) -> CodeQualityBreakdown:
    del integration_pass_ratio, completed_matches
    diagnostics = compiler or CompilerDiagnostics(False, 0, 0, 0.0)
    return _build_breakdown(
        compiler=diagnostics,
        metrics=analyze_static_code(strategy_regions or {}),
        score=FAILED_CODE_QUALITY,
        failure_stage=failure_stage,
        strategy_region=strategy_region,
    )


def failure_code_quality(
    failure_stage: str,
    *,
    error_count: int = 0,
    integration_pass_ratio: float = 0.0,
    completed_matches: int = 0,
) -> float:
    del error_count, integration_pass_ratio, completed_matches
    if failure_stage not in {"generation", "extraction", "validation", "compilation", "integration", "runtime", "timeout", "incomplete"}:
        raise ValueError(f"Unknown failure stage: {failure_stage}")
    return FAILED_CODE_QUALITY


def build_code_quality(
    compiler: CompilerDiagnostics,
    *legacy_args: Any,
    capability: FunctionCapabilityResult | None = None,
    alignment: StrategyAlignmentResult | None = None,
    strategy_regions: dict[str, str] | None = None,
) -> CodeQualityBreakdown:
    if strategy_regions is None:
        strategy_regions = next(
            (item for item in legacy_args if isinstance(item, dict)),
            None,
        )
    if not compiler.compile_success:
        return build_failure_code_quality("compilation", compiler=compiler, strategy_regions=strategy_regions)
    return build_successful_code_quality(
        compiler,
        capability,
        alignment,
        strategy_regions=strategy_regions,
    )
