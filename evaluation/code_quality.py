"""Deterministic Java metrics used by the canonical simplicity objective."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any


from .compiler import CompileResult, parse_compiler_diagnostics
from .function_capability import FunctionCapabilityResult
from .strategy_alignment import StrategyAlignmentResult


@dataclass(frozen=True)
class StrategyRegionValidation:
    valid: bool
    errors: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": list(self.errors)}


@dataclass(frozen=True)
class StrategyRegionScoreResult:
    strategy_region_score: float
    required_region_count: int
    valid_region_count: int
    strategy_region_validation: dict[str, StrategyRegionValidation]
    strategy_region: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy_region_score": self.strategy_region_score,
            "required_region_count": self.required_region_count,
            "valid_region_count": self.valid_region_count,
            "strategy_region_validation": {
                key: value.to_json_dict()
                for key, value in self.strategy_region_validation.items()
            },
        }


@dataclass(frozen=True)
class StaticCodeMetrics:
    analyzed_region_count: int
    effective_line_count: int
    effective_character_count: int
    statement_count: int
    branch_count: int
    loop_count: int
    cyclomatic_complexity: int
    max_nesting_depth: int
    duplicate_line_count: int
    duplicate_line_ratio: float
    max_line_length: int
    action_helpers_used: tuple[str, ...]
    strategy_functions_called: tuple[str, ...]
    state_signals_used: tuple[str, ...]
    action_coverage_score: float
    strategy_connectivity_score: float
    state_usage_score: float
    control_flow_score: float
    implementation_substance_score: float
    maintainability_score: float
    static_quality_score: float
    logical_loc: int = 0
    longest_function_loc: int = 0

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action_helpers_used"] = list(self.action_helpers_used)
        payload["strategy_functions_called"] = list(self.strategy_functions_called)
        payload["state_signals_used"] = list(self.state_signals_used)
        return payload


def evaluate_agent_strategy_region(
    strategy_region: str,
    *,
    error: str | None = None,
) -> StrategyRegionScoreResult:
    """Score the one marked strategy region from a complete Java source file."""
    errors: list[str] = []
    if error:
        errors.append(error)
    if not strategy_region.strip():
        errors.append("Complete Java source is missing a non-empty Agent strategy region.")
    valid = not errors
    validation = StrategyRegionValidation(valid, tuple(errors))
    return StrategyRegionScoreResult(
        strategy_region_score=100.0 if valid else -100.0,
        required_region_count=1,
        valid_region_count=1 if valid else 0,
        strategy_region_validation={"agent_strategy_region": validation},
        strategy_region=strategy_region,
    )


_ACTION_HELPERS = (
    "commandMove",
    "commandHarvest",
    "commandTrain",
    "commandBuild",
    "commandAttack",
    "commandIdle",
)
_STATE_SIGNALS: dict[str, str] = {
    "units": r"\bcontext\.units\b",
    "game_state": r"\bcontext\.gs\b",
    "player": r"\bcontext\.player\b",
    "enemy": r"\bcontext\.enemy\b",
    "resources": r"\bgetResources\s*\(",
    "unit_type": r"\bgetType\s*\(",
    "position": r"\bget[XY]\s*\(",
    "hit_points": r"\bgetHitPoints\s*\(",
    "ownership": r"\bgetPlayer\s*\(",
    "action_assignment": r"\bgetActionAssignment\s*\(",
}


def analyze_static_code(strategy_regions: dict[str, str]) -> StaticCodeMetrics:
    """Score the marked Java strategy region using deterministic metrics."""
    bodies = [
        body
        for body in strategy_regions.values()
        if isinstance(body, str) and body.strip()
    ]
    if not bodies:
        return StaticCodeMetrics(
            analyzed_region_count=0,
            effective_line_count=0,
            effective_character_count=0,
            statement_count=0,
            branch_count=0,
            loop_count=0,
            cyclomatic_complexity=0,
            max_nesting_depth=0,
            duplicate_line_count=0,
            duplicate_line_ratio=0.0,
            max_line_length=0,
            action_helpers_used=(),
            strategy_functions_called=(),
            state_signals_used=(),
            action_coverage_score=0.0,
            strategy_connectivity_score=0.0,
            state_usage_score=0.0,
            control_flow_score=0.0,
            implementation_substance_score=0.0,
            maintainability_score=0.0,
            static_quality_score=0.0,
            logical_loc=0,
            longest_function_loc=0,
        )

    cleaned_bodies = [_strip_comments_and_literals(body) for body in bodies]
    cleaned = "\n".join(cleaned_bodies)
    meaningful_lines = [
        re.sub(r"\s+", " ", line.strip())
        for line in cleaned.splitlines()
        if line.strip() and line.strip() not in {"{", "}"}
    ]
    effective_character_count = sum(1 for character in cleaned if not character.isspace())
    statement_count = cleaned.count(";")
    branch_count = len(re.findall(r"\b(?:if|case|catch)\b|&&|\|\||\?", cleaned))
    loop_count = len(re.findall(r"\b(?:for|while|do)\b", cleaned))
    cyclomatic_complexity = len(bodies) + branch_count + loop_count
    max_nesting_depth = max((_max_brace_depth(body) for body in cleaned_bodies), default=0)
    duplicate_candidates = [line for line in meaningful_lines if len(line) >= 16]
    duplicate_line_count = sum(
        count - 1 for count in Counter(duplicate_candidates).values() if count > 1
    )
    duplicate_line_ratio = duplicate_line_count / max(1, len(meaningful_lines))
    max_line_length = max((len(line) for line in meaningful_lines), default=0)
    logical_loc = len(meaningful_lines)
    longest_function_loc = max((_longest_function_loc(body) for body in cleaned_bodies), default=0)

    action_helpers_used = tuple(
        name for name in _ACTION_HELPERS if re.search(rf"\b{name}\s*\(", cleaned)
    )
    declared_strategy_methods = set(
        re.findall(
            r"\bprivate\s+(?:static\s+)?[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\(",
            cleaned,
        )
    )
    call_counts = Counter(re.findall(r"\b([A-Za-z_]\w*)\s*\(", cleaned))
    strategy_functions_called = tuple(
        sorted(
            name
            for name in declared_strategy_methods
            if call_counts[name] > 1 and name not in _ACTION_HELPERS
        )
    )
    state_signals_used = tuple(
        name for name, pattern in _STATE_SIGNALS.items() if re.search(pattern, cleaned)
    )

    action_score = 20.0 * len(action_helpers_used) / len(_ACTION_HELPERS)
    connectivity_score = min(10.0, 2.0 * len(strategy_functions_called))
    state_score = 15.0 * len(state_signals_used) / len(_STATE_SIGNALS)
    control_score = (
        10.0 * (1.0 - math.exp(-branch_count / 8.0))
        + 5.0 * (1.0 - math.exp(-loop_count / 3.0))
    )
    # Real executable content length changes this score smoothly. Comments and whitespace do not.
    substance_score = (
        10.0 * (1.0 - math.exp(-statement_count / 30.0))
        + 5.0 * (1.0 - math.exp(-effective_character_count / 2500.0))
    )

    complexity_penalty = max(0, cyclomatic_complexity - 30) * 0.35
    nesting_penalty = max(0, max_nesting_depth - 5) * 2.0
    duplication_penalty = min(10.0, duplicate_line_ratio * 20.0)
    size_penalty = max(0, effective_character_count - 12000) / 1000.0
    line_length_penalty = max(0, max_line_length - 160) * 0.02
    maintainability_score = max(
        0.0,
        25.0
        - complexity_penalty
        - nesting_penalty
        - duplication_penalty
        - size_penalty
        - line_length_penalty,
    )
    static_quality_score = (
        action_score
        + connectivity_score
        + state_score
        + control_score
        + substance_score
        + maintainability_score
    )

    rounded = lambda value: round(value, 6)
    return StaticCodeMetrics(
        analyzed_region_count=len(bodies),
        effective_line_count=len(meaningful_lines),
        effective_character_count=effective_character_count,
        statement_count=statement_count,
        branch_count=branch_count,
        loop_count=loop_count,
        cyclomatic_complexity=cyclomatic_complexity,
        max_nesting_depth=max_nesting_depth,
        duplicate_line_count=duplicate_line_count,
        duplicate_line_ratio=rounded(duplicate_line_ratio),
        max_line_length=max_line_length,
        action_helpers_used=action_helpers_used,
        strategy_functions_called=strategy_functions_called,
        state_signals_used=state_signals_used,
        action_coverage_score=rounded(action_score),
        strategy_connectivity_score=rounded(connectivity_score),
        state_usage_score=rounded(state_score),
        control_flow_score=rounded(control_score),
        implementation_substance_score=rounded(substance_score),
        maintainability_score=rounded(maintainability_score),
        static_quality_score=rounded(static_quality_score),
        logical_loc=logical_loc,
        longest_function_loc=longest_function_loc,
    )


def _strip_comments_and_literals(source: str) -> str:
    output: list[str] = []
    index = 0
    state = "code"
    while index < len(source):
        character = source[index]
        next_character = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if character == "/" and next_character == "/":
                state = "line_comment"
                output.extend("  ")
                index += 2
                continue
            if character == "/" and next_character == "*":
                state = "block_comment"
                output.extend("  ")
                index += 2
                continue
            if character == '"':
                state = "string"
                output.append(" ")
                index += 1
                continue
            if character == "'":
                state = "character"
                output.append(" ")
                index += 1
                continue
            output.append(character)
            index += 1
            continue
        if state == "line_comment":
            output.append("\n" if character == "\n" else " ")
            if character == "\n":
                state = "code"
            index += 1
            continue
        if state == "block_comment":
            if character == "*" and next_character == "/":
                output.extend("  ")
                index += 2
                state = "code"
                continue
            output.append("\n" if character == "\n" else " ")
            index += 1
            continue
        if character == "\\" and next_character:
            output.extend((" ", " "))
            index += 2
            continue
        output.append("\n" if character == "\n" else " ")
        if (
            (state == "string" and character == '"')
            or (state == "character" and character == "'")
        ):
            state = "code"
        index += 1
    return "".join(output)


def _max_brace_depth(source: str) -> int:
    depth = 0
    maximum = 0
    for character in source:
        if character == "{":
            depth += 1
            maximum = max(maximum, depth)
        elif character == "}":
            depth = max(0, depth - 1)
    return maximum


_METHOD_PATTERN = re.compile(
    r"\b(?:public|protected|private|static|final|synchronized|native|abstract|default)\s+"
    r"[\w<>,.?\[\] ]+\s+[A-Za-z_]\w*\s*\([^;{}]*\)\s*\{"
)


def _longest_function_loc(source: str) -> int:
    """Return a bounded, lexical estimate of the longest Java method size."""
    longest = 0
    for match in _METHOD_PATTERN.finditer(source):
        opening = source.find("{", match.start(), match.end())
        if opening < 0:
            continue
        depth = 0
        closing = None
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            continue
        longest = max(longest, source[match.start():closing + 1].count("\n") + 1)
    return longest


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
