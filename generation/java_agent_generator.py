"""Structured behavior generation, validation, single-file rendering, and persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from eagle.candidate import Candidate, MODULE_NAMES
from evaluation.code_quality import FunctionScoreResult, evaluate_function_output

from .agent_template import JavaTemplatePaths, load_java_template, render_agent_template
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
        """Compatibility alias for evaluators that score the generated behavior code."""
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
    except (RuntimeError, ValueError, OSError) as exc:
        reason = str(exc)
        return JavaAgentGenerationResult(
            raw_llm_output=locals().get("raw", ""),
            validation_result=ValidationResult(False, reason),
            failure_category=classify_generation_error(reason),
            failure_reason=reason,
        )

    functions = evaluate_function_output(raw, template)
    errors = function_output_errors(functions)
    if errors:
        reason = "; ".join(errors)
        return JavaAgentGenerationResult(
            raw_llm_output=raw,
            module_raw_outputs={"all": raw},
            module_bodies=functions.bodies,
            validation_result=ValidationResult(False, reason),
            function_score_result=functions,
            failure_category="Java validation failure",
            failure_reason=reason,
        )

    try:
        source = render_agent_template(template, functions.bodies)
    except ValueError as exc:
        reason = str(exc)
        return JavaAgentGenerationResult(
            raw_llm_output=raw,
            module_bodies=functions.bodies,
            function_score_result=functions,
            validation_result=ValidationResult(False, reason),
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
        json.dumps({"functions": functions.bodies}, ensure_ascii=False),
        {"all": raw},
        functions.bodies,
        validation,
    )
    return JavaAgentGenerationResult(
        raw_llm_output=raw,
        extracted_code=agent.extracted_code,
        module_raw_outputs={"all": raw},
        module_bodies=functions.bodies,
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


def parse_behavior_functions(raw: str) -> dict[str, str]:
    template = load_java_template(JavaTemplatePaths())
    result = evaluate_function_output(raw, template)
    errors = list(result.parsing_errors) + [
        error for item in result.function_validation.values() for error in item.errors
    ]
    if errors:
        raise ValueError("; ".join(errors))
    return {name: result.bodies[name] for name in MODULE_NAMES}


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
    return json.dumps({"functions": parse_behavior_functions(raw_output)}, ensure_ascii=False)


def clean_generated_java_output(output: str) -> str:
    return output.strip()


def normalize_java_agent_source(source: str) -> str:
    return source


def validate_java_agent_source(source: str, class_name: str) -> None:
    if f"public final class {class_name} extends AbstractionLayerAI" not in source:
        raise ValueError("Fixed single-file agent class declaration is missing.")


def validate_assembled_java(source: str, class_name: str) -> ValidationResult:
    return ValidationResult(
        "EAGLE_BODY" not in source,
        "Unresolved EAGLE_BODY placeholder." if "EAGLE_BODY" in source else "",
    )


def classify_generation_error(reason: str) -> str:
    lowered = reason.lower()
    if "timeout" in lowered:
        return "Timeout"
    if "backend" in lowered or "http" in lowered:
        return "Backend request failure"
    return "Java validation failure"