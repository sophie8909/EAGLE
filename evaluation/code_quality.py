"""Component scoring for the code_quality optimization objective."""
from __future__ import annotations
import json
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
        payload = asdict(self); payload["errors"] = list(self.errors); payload["warnings"] = list(self.warnings); return payload

@dataclass(frozen=True)
class FunctionValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    def to_json_dict(self) -> dict[str, Any]: return {"valid": self.valid, "errors": list(self.errors)}

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
        return {"function_score": self.function_score, "required_function_count": self.required_function_count, "valid_function_count": self.valid_function_count, "function_validation": {k:v.to_json_dict() for k,v in self.function_validation.items()}, "unknown_function_names": list(self.unknown_function_names), "parsing_errors": list(self.parsing_errors)}

@dataclass(frozen=True)
class CodeQualityBreakdown:
    compilation_score: float
    function_score: float
    strategy_consistency_score: float
    warning_count: int
    required_function_count: int
    valid_function_count: int
    compile_success: bool
    compile_error_count: int
    function_validation: dict[str, dict[str, Any]]
    compiler_errors: tuple[str, ...] = ()
    compiler_warnings: tuple[str, ...] = ()
    judge_error: str | None = None
    unknown_generated_functions: tuple[str, ...] = ()
    function_parsing_errors: tuple[str, ...] = ()
    @property
    def code_quality(self) -> float: return self.compilation_score + self.function_score + self.strategy_consistency_score
    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self); payload["compiler_errors"] = list(self.compiler_errors); payload["compiler_warnings"] = list(self.compiler_warnings); payload["unknown_generated_functions"] = list(self.unknown_generated_functions); payload["function_parsing_errors"] = list(self.function_parsing_errors); return payload

def analyze_compilation(result: CompileResult | None) -> CompilerDiagnostics:
    if result is None: return CompilerDiagnostics(False, 1, 0, -1000.0, errors=("Compilation was not run.",))
    lines = (result.stdout + "\n" + result.stderr).splitlines()
    warnings = tuple(line.strip() for line in lines if "warning:" in line.lower() and "error:" not in line.lower())
    errors = tuple(line.strip() for line in lines if "error:" in line.lower())
    if not result.ok:
        return CompilerDiagnostics(False, max(1, len(errors)), len(warnings), -1000.0, errors=errors or ((result.stderr or "javac failed").strip(),), warnings=warnings)
    return CompilerDiagnostics(True, 0, len(warnings), 0.0 if not warnings else -50.0 * len(warnings), warnings=warnings)

def evaluate_function_output(raw: str, behavior_template: str) -> FunctionScoreResult:
    parsing_errors: list[str] = []
    functions: dict[str, object] = {}
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("functions"), dict):
            parsing_errors.append("Generated behavior response must contain a functions object.")
        else:
            functions = payload["functions"]
            if set(payload) != {"functions"}: parsing_errors.append("Generated behavior response must contain only a functions object.")
    except json.JSONDecodeError as exc:
        parsing_errors.append(f"Generated behavior response is not valid JSON: {exc}")
    unknown = tuple(sorted(set(functions) - set(MODULE_NAMES)))
    if unknown: parsing_errors.append(f"Unknown behavior function keys: {', '.join(unknown)}")
    template_names = PLACEHOLDER_PATTERN.findall(behavior_template)
    validations: dict[str, FunctionValidation] = {}; bodies: dict[str, str] = {}; score_units = 0
    for name in MODULE_NAMES:
        errors: list[str] = []
        value = functions.get(name)
        if name not in functions:
            errors.append("Required function key is missing")
            score_units -= 1
        elif not isinstance(value, str): errors.append("Function body must be a string")
        elif not value.strip(): errors.append("Function body is empty")
        else:
            bodies[name] = value
            try: validate_function_module(value, name)
            except ValueError as exc: errors.append(str(exc))
        if template_names.count(name) != 1: errors.append("Predefined template slot is missing or duplicated")
        if not errors: score_units += 1
        validations[name] = FunctionValidation(not errors, tuple(errors))
    valid_count = sum(item.valid for item in validations.values()); required = len(MODULE_NAMES)
    return FunctionScoreResult(100.0 * score_units / required, required, valid_count, validations, unknown, tuple(parsing_errors), bodies)

def build_code_quality(compiler: CompilerDiagnostics, functions: FunctionScoreResult, strategy_score: float | None, judge_error: str | None = None) -> CodeQualityBreakdown:
    score = 0.0 if strategy_score is None else float(strategy_score)
    if not 0.0 <= score <= 10.0: raise ValueError("strategy_consistency_score must be between 0 and 10.")
    return CodeQualityBreakdown(compiler.compilation_score, functions.function_score, score, compiler.warning_count, functions.required_function_count, functions.valid_function_count, compiler.compile_success, compiler.compile_error_count, {k:v.to_json_dict() for k,v in functions.function_validation.items()}, compiler.errors, compiler.warnings, judge_error, functions.unknown_function_names, functions.parsing_errors)
