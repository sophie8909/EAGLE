"""Complete Java source generation, validation, extraction, and persistence."""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from eagle.candidate import Candidate, MODULE_NAMES
from eagle.module_contract import MODULE_METHOD_CONTRACTS, ModuleMethodContract
from evaluation.code_quality import FunctionScoreResult, evaluate_function_output

from .agent_template import ACTION_HELPER_METHODS, JavaTemplatePaths, load_java_template, render_agent_template
from .backend import GenerationBackend
from .java_module_validator import validate_function_module


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str = ""


@dataclass(frozen=True)
class GeneratedJavaAgent:
    class_name: str
    package_name: str
    source: str
    source_path: Path
    raw_llm_output: str = ""
    extracted_code: str = ""
    module_raw_outputs: dict[str, str] = field(default_factory=dict)
    module_bodies: dict[str, str] = field(default_factory=dict)
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(True))

    @property
    def qualified_class_name(self) -> str:
        return f"{self.package_name}.{self.class_name}"

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return (self.source_path,)

    @property
    def behavior_source(self) -> str:
        return self.source

    @property
    def behavior_source_path(self) -> Path:
        return self.source_path


@dataclass(frozen=True)
class JavaAgentGenerationResult:
    class_name: str = "CandidateAgent"
    package_name: str = "ai.generated"
    raw_llm_output: str = ""
    extracted_code: str = ""
    module_raw_outputs: dict[str, str] = field(default_factory=dict)
    module_bodies: dict[str, str] = field(default_factory=dict)
    assembled_java: str = ""
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(False, "not_run"))
    function_score_result: FunctionScoreResult | None = None
    agent: GeneratedJavaAgent | None = None
    failure_category: str | None = None
    failure_reason: str | None = None


def generate_java_agent(
    candidate: Candidate,
    backend: GenerationBackend,
    workspace_dir: Path,
    *,
    template_paths: JavaTemplatePaths | None = None,
) -> GeneratedJavaAgent:
    result = generate_java_agent_result(candidate, backend, workspace_dir, template_paths=template_paths)
    if result.agent is None:
        raise ValueError(result.failure_reason or "Java agent generation failed.")
    return result.agent


def generate_java_agent_result(
    candidate: Candidate,
    backend: GenerationBackend,
    workspace_dir: Path,
    *,
    template_paths: JavaTemplatePaths | None = None,
) -> JavaAgentGenerationResult:
    paths = template_paths or JavaTemplatePaths()
    try:
        template = load_java_template(paths)
        raw = backend.generate(candidate, "CandidateAgent")
        source = normalize_java_agent_source(extract_code_from_output(raw))
        bodies = extract_behavior_functions_from_java(source)
    except (RuntimeError, ValueError, OSError) as exc:
        reason = str(exc)
        return JavaAgentGenerationResult(
            raw_llm_output=locals().get("raw", ""),
            extracted_code=locals().get("source", ""),
            module_raw_outputs={"all": locals().get("raw", "")},
            module_bodies=locals().get("bodies", {}),
            validation_result=ValidationResult(False, reason),
            failure_category=classify_generation_error(reason),
            failure_reason=reason,
        )

    functions = evaluate_function_output(json.dumps({"functions": bodies}), template)
    errors = function_output_errors(functions)
    try:
        if errors:
            raise ValueError("; ".join(errors))
        validate_java_agent_source(source, "CandidateAgent")
    except ValueError as exc:
        reason = str(exc)
        return JavaAgentGenerationResult(
            raw_llm_output=raw,
            extracted_code=source,
            module_raw_outputs={"all": raw},
            module_bodies=bodies,
            assembled_java=source,
            validation_result=ValidationResult(False, reason),
            function_score_result=functions,
            failure_category="Java validation failure",
            failure_reason=reason,
        )

    package_dir = workspace_dir / candidate.id
    package_dir.mkdir(parents=True, exist_ok=True)
    source_path = package_dir / "CandidateAgent.java"
    source_path.write_text(source, encoding="utf-8")
    validation = ValidationResult(True, "")
    agent = GeneratedJavaAgent(
        "CandidateAgent",
        "ai.generated",
        source,
        source_path,
        raw,
        source,
        {"all": raw},
        bodies,
        validation,
    )
    return JavaAgentGenerationResult(
        raw_llm_output=raw,
        extracted_code=source,
        module_raw_outputs={"all": raw},
        module_bodies=bodies,
        assembled_java=source,
        validation_result=validation,
        function_score_result=functions,
        agent=agent,
    )


def function_output_errors(functions: FunctionScoreResult) -> list[str]:
    return list(functions.parsing_errors) + [
        f"{name}: {error}"
        for name, item in functions.function_validation.items()
        for error in item.errors
    ]


def extract_behavior_functions_from_java(source: str) -> dict[str, str]:
    bodies: dict[str, str] = {}
    for name, contract in MODULE_METHOD_CONTRACTS.items():
        pattern = _contract_pattern(contract)
        matches = list(pattern.finditer(source))
        if len(matches) != 1:
            raise ValueError(
                f"Complete Java source must contain {contract.declaration} exactly once; found {len(matches)}."
            )
        open_brace = source.find("{", matches[0].start(), matches[0].end())
        close_brace = _matching_brace(source, open_brace)
        body = textwrap.dedent(source[open_brace + 1 : close_brace]).strip()
        validate_function_module(body, name)
        bodies[name] = body
    return bodies


def _contract_pattern(contract: ModuleMethodContract) -> re.Pattern[str]:
    parameters = r"\s*,\s*".join(
        rf"{re.escape(parameter_type)}\s+{re.escape(name)}"
        for parameter_type, name in contract.parameters
    )
    return re.compile(
        rf"\bprivate\s+{re.escape(contract.return_type)}\s+{re.escape(contract.method_name)}"
        rf"\s*\(\s*{parameters}\s*\)\s*\{{"
    )


def _matching_brace(source: str, open_brace: int) -> int:
    if open_brace < 0 or source[open_brace] != "{":
        raise ValueError("Generated Java method opening brace is missing.")
    depth = 0
    state = "code"
    index = open_brace
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "/" and next_char == "/":
                state = "line_comment"
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                index += 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        elif state == "string":
            if char == "\\":
                index += 1
            elif char == '"':
                state = "code"
        elif state == "char":
            if char == "\\":
                index += 1
            elif char == "'":
                state = "code"
        elif state == "line_comment":
            if char in "\r\n":
                state = "code"
        elif state == "block_comment" and char == "*" and next_char == "/":
            state = "code"
            index += 1
        index += 1
    raise ValueError("Generated Java method has unbalanced braces.")


def parse_behavior_functions(raw: str) -> dict[str, str]:
    source = normalize_java_agent_source(extract_code_from_output(raw))
    validate_java_agent_source(source, "CandidateAgent")
    return extract_behavior_functions_from_java(source)


def assemble_java_agent(
    class_name: str,
    module_bodies: dict[str, str],
    *,
    template_paths: JavaTemplatePaths | None = None,
) -> str:
    if class_name != "CandidateAgent":
        raise ValueError("Repository template declares only CandidateAgent.")
    for name in MODULE_NAMES:
        validate_function_module(module_bodies[name], name)
    template = load_java_template(template_paths or JavaTemplatePaths())
    return render_agent_template(template, module_bodies)


def extract_code_from_output(raw_output: str) -> str:
    stripped = raw_output.strip()
    fence = re.fullmatch(r"```(?:java)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fence:
        stripped = fence.group(1).strip()
    elif "```" in stripped:
        raise ValueError("Complete Java response must not contain partial markdown fences or surrounding text.")
    if not stripped:
        raise ValueError("Generated Java response is empty.")
    return stripped


def clean_generated_java_output(output: str) -> str:
    return extract_code_from_output(output)


def normalize_java_agent_source(source: str) -> str:
    return source.lstrip("\ufeff").strip()


def validate_java_agent_source(source: str, class_name: str) -> None:
    required = (
        "package ai.generated;",
        f"public final class {class_name} extends AbstractionLayerAI",
        f"public {class_name}(UnitTypeTable utt)",
        "public PlayerAction getAction(int player, GameState gs)",
        "return translateActions(player, gs);",
    )
    missing = [token for token in required if token not in source]
    if missing:
        raise ValueError(f"Complete Java source is missing required content: {', '.join(missing)}")
    if not source.startswith("package ai.generated;"):
        raise ValueError("Complete Java source must start with package ai.generated;.")
    if "EAGLE_BODY" in source:
        raise ValueError("Complete Java source contains unresolved EAGLE_BODY placeholders.")
    for helper in ACTION_HELPER_METHODS:
        count = len(re.findall(rf"\bprivate\s+boolean\s+{helper}\s*\(", source))
        if count != 1:
            raise ValueError(f"Complete Java source must preserve action helper {helper} exactly once; found {count}.")
    forbidden_patterns = (
        r"\bSystem\.getenv\b",
        r"\bURL\b",
        r"\bHttpClient\b",
        r"/v1/chat/completions",
        r"\bSocket\b",
        r"\bFiles\.",
        r"\bProcessBuilder\b",
        r"\bRuntime\.getRuntime\b",
    )
    if any(re.search(pattern, source) for pattern in forbidden_patterns):
        raise ValueError("Complete Java source uses forbidden runtime I/O, process, or LLM APIs.")
    extract_behavior_functions_from_java(source)


def validate_assembled_java(source: str, class_name: str) -> ValidationResult:
    try:
        validate_java_agent_source(source, class_name)
    except ValueError as exc:
        return ValidationResult(False, str(exc))
    return ValidationResult(True, "")


def classify_generation_error(reason: str) -> str:
    lowered = reason.lower()
    if "timeout" in lowered:
        return "Timeout"
    if "backend" in lowered or "http" in lowered:
        return "Backend request failure"
    return "Java validation failure"