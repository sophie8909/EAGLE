"""Deterministic component scoring for the code_quality optimization objective."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any


from .compiler import CompileResult, parse_compiler_diagnostics


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

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action_helpers_used"] = list(self.action_helpers_used)
        payload["strategy_functions_called"] = list(self.strategy_functions_called)
        payload["state_signals_used"] = list(self.state_signals_used)
        return payload


@dataclass(frozen=True)
class CodeQualityBreakdown:
    compilation_score: float
    strategy_region_score: float
    static_quality_score: float
    warning_count: int
    required_region_count: int
    valid_region_count: int
    compile_success: bool
    compile_error_count: int
    strategy_region_validation: dict[str, dict[str, Any]]
    compiler_errors: tuple[str, ...] = ()
    compiler_warnings: tuple[str, ...] = ()
    static_metrics: StaticCodeMetrics | None = None

    @property
    def code_quality(self) -> float:
        return round(
            self.compilation_score
            + self.strategy_region_score
            + self.static_quality_score,
            6,
        )

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code_quality"] = self.code_quality
        payload["compiler_errors"] = list(self.compiler_errors)
        payload["compiler_warnings"] = list(self.compiler_warnings)
        return payload


def analyze_compilation(result: CompileResult | None) -> CompilerDiagnostics:
    if result is None:
        return CompilerDiagnostics(False, 1, 0, -1000.0, errors=("Compilation was not run.",))
    diagnostics = result.diagnostics or parse_compiler_diagnostics(result.stdout + "\n" + result.stderr)
    warning_items = tuple(item for item in diagnostics if item.severity == "warning")
    error_items = tuple(item for item in diagnostics if item.severity == "error")
    warnings = tuple(item.message for item in warning_items)
    errors = tuple(item.message for item in error_items)
    if not result.ok:
        return CompilerDiagnostics(
            False,
            max(1, len(error_items)),
            len(warning_items),
            -1000.0,
            errors=errors or ((result.stderr or "javac failed").strip(),),
            warnings=warnings,
        )
    return CompilerDiagnostics(
        True,
        0,
        len(warning_items),
        0.0 if not warning_items else -50.0 * len(warning_items),
        warnings=warnings,
    )

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
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0,
            (), (), (),
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
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


def build_code_quality(
    compiler: CompilerDiagnostics,
    strategy_region: StrategyRegionScoreResult,
    strategy_regions: dict[str, str],
) -> CodeQualityBreakdown:
    metrics = analyze_static_code(strategy_regions)
    return CodeQualityBreakdown(
        compilation_score=compiler.compilation_score,
        strategy_region_score=strategy_region.strategy_region_score,
        static_quality_score=metrics.static_quality_score,
        warning_count=compiler.warning_count,
        required_region_count=strategy_region.required_region_count,
        valid_region_count=strategy_region.valid_region_count,
        compile_success=compiler.compile_success,
        compile_error_count=compiler.compile_error_count,
        strategy_region_validation={
            key: value.to_json_dict()
            for key, value in strategy_region.strategy_region_validation.items()
        },
        compiler_errors=compiler.errors,
        compiler_warnings=compiler.warnings,
        static_metrics=metrics,
    )
