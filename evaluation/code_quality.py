"""Deterministic component scoring for the code_quality optimization objective."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from eagle.candidate import MODULE_NAMES
from generation.agent_template import PLACEHOLDER_PATTERN
from generation.java_module_validator import validate_function_module

from .compiler import CompileResult


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
class FunctionValidation:
    valid: bool
    errors: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": list(self.errors)}


@dataclass(frozen=True)
class FunctionScoreResult:
    function_score: float
    required_function_count: int
    valid_function_count: int
    function_validation: dict[str, FunctionValidation]
    unknown_function_names: tuple[str, ...] = ()
    parsing_errors: tuple[str, ...] = ()
    bodies: dict[str, str] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "function_score": self.function_score,
            "required_function_count": self.required_function_count,
            "valid_function_count": self.valid_function_count,
            "function_validation": {
                key: value.to_json_dict() for key, value in self.function_validation.items()
            },
            "unknown_function_names": list(self.unknown_function_names),
            "parsing_errors": list(self.parsing_errors),
        }


@dataclass(frozen=True)
class StaticCodeMetrics:
    analyzed_function_count: int
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
    function_score: float
    static_quality_score: float
    warning_count: int
    required_function_count: int
    valid_function_count: int
    compile_success: bool
    compile_error_count: int
    function_validation: dict[str, dict[str, Any]]
    compiler_errors: tuple[str, ...] = ()
    compiler_warnings: tuple[str, ...] = ()
    static_metrics: StaticCodeMetrics | None = None
    unknown_generated_functions: tuple[str, ...] = ()
    function_parsing_errors: tuple[str, ...] = ()

    @property
    def code_quality(self) -> float:
        return self.compilation_score + self.function_score + self.static_quality_score

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code_quality"] = self.code_quality
        payload["compiler_errors"] = list(self.compiler_errors)
        payload["compiler_warnings"] = list(self.compiler_warnings)
        payload["unknown_generated_functions"] = list(self.unknown_generated_functions)
        payload["function_parsing_errors"] = list(self.function_parsing_errors)
        return payload


def analyze_compilation(result: CompileResult | None) -> CompilerDiagnostics:
    if result is None:
        return CompilerDiagnostics(False, 1, 0, -1000.0, errors=("Compilation was not run.",))
    lines = (result.stdout + "\n" + result.stderr).splitlines()
    warnings = tuple(line.strip() for line in lines if "warning:" in line.lower() and "error:" not in line.lower())
    errors = tuple(line.strip() for line in lines if "error:" in line.lower())
    if not result.ok:
        return CompilerDiagnostics(
            False,
            max(1, len(errors)),
            len(warnings),
            -1000.0,
            errors=errors or ((result.stderr or "javac failed").strip(),),
            warnings=warnings,
        )
    return CompilerDiagnostics(
        True,
        0,
        len(warnings),
        0.0 if not warnings else -50.0 * len(warnings),
        warnings=warnings,
    )


_OUTER_JSON_FENCE = re.compile(
    r"\A\s*" + chr(96) * 3 + r"(?:json)?\s*(.*?)\s*" + chr(96) * 3 + r"\s*\Z",
    re.DOTALL | re.IGNORECASE,
)


def unwrap_outer_json_fence(raw: str) -> str:
    """Remove one fence only when it encloses the entire model response."""
    match = _OUTER_JSON_FENCE.fullmatch(raw)
    return match.group(1).strip() if match else raw


def evaluate_function_output(raw: str, behavior_template: str) -> FunctionScoreResult:
    parsing_errors: list[str] = []
    functions: dict[str, object] = {}
    try:
        payload = json.loads(unwrap_outer_json_fence(raw))
        if not isinstance(payload, dict) or not isinstance(payload.get("functions"), dict):
            parsing_errors.append("Generated behavior response must contain a functions object.")
        else:
            functions = payload["functions"]
            if set(payload) != {"functions"}:
                parsing_errors.append("Generated behavior response must contain only a functions object.")
    except json.JSONDecodeError as exc:
        parsing_errors.append(f"Generated behavior response is not valid JSON: {exc}")
    unknown = tuple(sorted(set(functions) - set(MODULE_NAMES)))
    if unknown:
        parsing_errors.append(f"Unknown behavior function keys: {', '.join(unknown)}")
    template_names = PLACEHOLDER_PATTERN.findall(behavior_template)
    validations: dict[str, FunctionValidation] = {}
    bodies: dict[str, str] = {}
    score_units = 0
    for name in MODULE_NAMES:
        errors: list[str] = []
        value = functions.get(name)
        if name not in functions:
            errors.append("Required function key is missing")
            score_units -= 1
        elif not isinstance(value, str):
            errors.append("Function body must be a string")
        elif not value.strip():
            errors.append("Function body is empty")
        else:
            bodies[name] = value
            try:
                validate_function_module(value, name)
            except ValueError as exc:
                errors.append(str(exc))
        if template_names.count(name) != 1:
            errors.append("Predefined template slot is missing or duplicated")
        if not errors:
            score_units += 1
        validations[name] = FunctionValidation(not errors, tuple(errors))
    valid_count = sum(item.valid for item in validations.values())
    required = len(MODULE_NAMES)
    return FunctionScoreResult(
        100.0 * score_units / required,
        required,
        valid_count,
        validations,
        unknown,
        tuple(parsing_errors),
        bodies,
    )


_ACTION_HELPERS = (
    "commandMove",
    "commandHarvest",
    "commandTrain",
    "commandBuild",
    "commandAttack",
    "commandIdle",
)
_STRATEGY_FUNCTIONS = ("economy", "combat", "expansion", "selectTarget", "findPath")
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


def analyze_static_code(module_bodies: dict[str, str]) -> StaticCodeMetrics:
    """Score generated strategy bodies using deterministic, explainable metrics."""
    bodies = [
        module_bodies.get(name, "")
        for name in MODULE_NAMES
        if module_bodies.get(name, "").strip()
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
    strategy_functions_called = tuple(
        name for name in _STRATEGY_FUNCTIONS if re.search(rf"\b{name}\s*\(", cleaned)
    )
    state_signals_used = tuple(
        name for name, pattern in _STATE_SIGNALS.items() if re.search(pattern, cleaned)
    )

    action_score = 20.0 * len(action_helpers_used) / len(_ACTION_HELPERS)
    connectivity_score = 10.0 * len(strategy_functions_called) / len(_STRATEGY_FUNCTIONS)
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
        analyzed_function_count=len(bodies),
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
    functions: FunctionScoreResult,
    module_bodies: dict[str, str],
) -> CodeQualityBreakdown:
    metrics = analyze_static_code(module_bodies)
    return CodeQualityBreakdown(
        compilation_score=compiler.compilation_score,
        function_score=functions.function_score,
        static_quality_score=metrics.static_quality_score,
        warning_count=compiler.warning_count,
        required_function_count=functions.required_function_count,
        valid_function_count=functions.valid_function_count,
        compile_success=compiler.compile_success,
        compile_error_count=compiler.compile_error_count,
        function_validation={
            key: value.to_json_dict()
            for key, value in functions.function_validation.items()
        },
        compiler_errors=compiler.errors,
        compiler_warnings=compiler.warnings,
        static_metrics=metrics,
        unknown_generated_functions=functions.unknown_function_names,
        function_parsing_errors=functions.parsing_errors,
    )
