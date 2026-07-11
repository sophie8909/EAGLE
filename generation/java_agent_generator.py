"""Prompt-to-Java generation wrapper and source validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from eagle.candidate import Candidate, MODULE_NAMES

from .backend import GenerationBackend, generated_class_name
from .java_module_validator import validate_function_module
from .agent_template import render_function_agent


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
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(ok=True))

    @property
    def qualified_class_name(self) -> str:
        return f"{self.package_name}.{self.class_name}"


@dataclass(frozen=True)
class JavaAgentGenerationResult:
    class_name: str
    package_name: str = "ai.generated"
    raw_llm_output: str = ""
    extracted_code: str = ""
    module_raw_outputs: dict[str, str] = field(default_factory=dict)
    module_bodies: dict[str, str] = field(default_factory=dict)
    assembled_java: str = ""
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(ok=False, error="not_run"))
    agent: GeneratedJavaAgent | None = None
    failure_category: str | None = None
    failure_reason: str | None = None


def generate_java_agent(
    candidate: Candidate,
    backend: GenerationBackend,
    workspace_dir: Path,
) -> GeneratedJavaAgent:
    """Generate, validate, and persist one isolated Java source file."""

    result = generate_java_agent_result(candidate, backend, workspace_dir)
    if result.agent is None:
        message = result.failure_reason or "Java agent generation failed."
        if result.failure_category == "Backend request failure" or result.failure_category == "Timeout":
            raise RuntimeError(message)
        raise ValueError(message)
    return result.agent


def generate_java_agent_result(
    candidate: Candidate,
    backend: GenerationBackend,
    workspace_dir: Path,
) -> JavaAgentGenerationResult:
    """Run LLM output, extraction, assembly, validation, and source writing."""

    class_name = generated_class_name(candidate.id)
    module_raw_outputs: dict[str, str] = {}
    module_bodies: dict[str, str] = {}
    source = ""

    try:
        for module_name in MODULE_NAMES:
            raw_output = request_module_body(candidate, backend, class_name, module_name)
            module_raw_outputs[module_name] = raw_output
            module_bodies[module_name] = extract_code_from_output(raw_output)
    except (RuntimeError, ValueError, OSError) as exc:
        reason = str(exc)
        return JavaAgentGenerationResult(
            class_name=class_name,
            raw_llm_output=join_module_text(module_raw_outputs),
            module_raw_outputs=module_raw_outputs,
            module_bodies=module_bodies,
            failure_category=classify_generation_error(reason),
            failure_reason=reason,
        )

    try:
        source = assemble_java_agent(class_name, module_bodies)
        validation = validate_assembled_java(source, class_name)
        if not validation.ok:
            return JavaAgentGenerationResult(
                class_name=class_name,
                raw_llm_output=join_module_text(module_raw_outputs),
                extracted_code=join_module_text(module_bodies),
                module_raw_outputs=module_raw_outputs,
                module_bodies=module_bodies,
                assembled_java=source,
                validation_result=validation,
                failure_category="Java validation failure",
                failure_reason=validation.error,
            )
    except ValueError as exc:
        reason = str(exc)
        return JavaAgentGenerationResult(
            class_name=class_name,
            raw_llm_output=join_module_text(module_raw_outputs),
            extracted_code=join_module_text(module_bodies),
            module_raw_outputs=module_raw_outputs,
            module_bodies=module_bodies,
            assembled_java=source,
            validation_result=ValidationResult(ok=False, error=reason),
            failure_category="Java validation failure",
            failure_reason=reason,
        )

    package_dir = workspace_dir / candidate.id / "src" / "ai" / "generated"
    package_dir.mkdir(parents=True, exist_ok=True)
    source_path = package_dir / f"{class_name}.java"
    source_path.write_text(source, encoding="utf-8")
    agent = GeneratedJavaAgent(
        class_name=class_name,
        package_name="ai.generated",
        source=source,
        source_path=source_path,
        raw_llm_output=join_module_text(module_raw_outputs),
        extracted_code=join_module_text(module_bodies),
        module_raw_outputs=module_raw_outputs,
        module_bodies=module_bodies,
        validation_result=validation,
    )
    return JavaAgentGenerationResult(
        class_name=class_name,
        raw_llm_output=join_module_text(module_raw_outputs),
        extracted_code=join_module_text(module_bodies),
        module_raw_outputs=module_raw_outputs,
        module_bodies=module_bodies,
        assembled_java=source,
        validation_result=validation,
        agent=agent,
    )


def request_module_body(candidate: Candidate, backend: GenerationBackend, class_name: str, module_name: str) -> str:
    """Ask the backend for one module body text."""

    return backend.generate_module(candidate, class_name, module_name)


def extract_code_from_output(raw_output: str) -> str:
    """Clean wrapper text and extract the strategy-body code."""

    return clean_generated_java_output(raw_output)


def assemble_java_agent(class_name: str, module_bodies: dict[str, str]) -> str:
    """Insert function bodies into the fixed Java scaffold."""

    for module_name in MODULE_NAMES:
        validate_function_module(module_bodies[module_name], module_name)
    return render_function_agent(class_name, module_bodies)


def join_module_text(values: dict[str, str]) -> str:
    return "\n\n".join(f"// {name}\n{values.get(name, '')}" for name in MODULE_NAMES)


def validate_assembled_java(source: str, class_name: str) -> ValidationResult:
    """Validate the assembled Java source without compiling it."""

    try:
        validate_java_agent_source(source, class_name)
    except ValueError as exc:
        return ValidationResult(ok=False, error=str(exc))
    return ValidationResult(ok=True)


def classify_generation_error(reason: str) -> str:
    lowered = reason.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "Timeout"
    if "backend" in lowered or "http error" in lowered or "http 400" in lowered:
        return "Backend request failure"
    return "Other"


def clean_generated_java_output(output: str) -> str:
    """Keep the Java source and remove common LLM wrapper text."""

    source = output.strip()

    fence_match = re.search(r"```(?:java)?\s*(.*?)```", source, re.DOTALL | re.IGNORECASE)
    if fence_match:
        source = fence_match.group(1).strip()

    starts = [
        match.start()
        for pattern in (r"(?m)^package\s+", r"(?m)^import\s+", r"(?m)^(?:public\s+)?class\s+")
        if (match := re.search(pattern, source))
    ]
    if starts:
        source = source[min(starts) :].strip()

    final_brace = source.rfind("}")
    if final_brace != -1:
        source = source[: final_brace + 1].strip()

    return source


def normalize_java_agent_source(source: str) -> str:
    """Repair small, common MicroRTS import/annotation mistakes in LLM output."""

    source = source.replace("import ai.UnitTypeTable;", "import rts.units.UnitTypeTable;")
    source = source.replace("import ai.core.UnitTypeTable;", "import rts.units.UnitTypeTable;")
    source = re.sub(r"(?m)^\s*@Override\s*\n\s*public\s+void\s+act\s*\(", "    public void act(", source)
    source = re.sub(r"(?m)^\s*//\s*Helper methods\.\.\.\s*$\n?", "", source)

    if "UnitTypeTable" in source and "import rts.units.UnitTypeTable;" not in source:
        source = re.sub(
            r"(?m)^(package\s+ai\.generated;\s*)$",
            "\\1\n\nimport rts.units.UnitTypeTable;",
            source,
            count=1,
        )
    return source


def validate_java_agent_source(source: str, class_name: str) -> None:
    if "```" in source:
        raise ValueError("Generated Java source still contains markdown code fences.")
    if not re.search(r"\bclass\s+\w+", source):
        raise ValueError("Generated Java source does not contain a Java class declaration.")
    first_line = next((line.strip() for line in source.splitlines() if line.strip()), "")
    if first_line and not first_line.startswith(("package ", "import ", "public class ", "class ")):
        raise ValueError("Generated Java source appears to start with explanation text instead of Java.")
    if "nearestIdleAlly(" in source:
        raise ValueError("Generated Java agent must not call nonexistent helper nearestIdleAlly().")

    unsafe_iteration_patterns = [
        r"for\s*\([^:]+:\s*gs\.getUnits\(\)\s*\)",
        r"for\s*\([^:]+:\s*gs\.getPhysicalGameState\(\)\.getUnits\(\)\s*\)",
        r"for\s*\([^:]+:\s*pgs\.getUnits\(\)\s*\)",
    ]
    if any(re.search(pattern, source) for pattern in unsafe_iteration_patterns):
        raise ValueError(
            "Generated Java agent must not iterate directly over gs.getUnits() or pgs.getUnits()."
        )

    required_tokens = [
        "package ai.generated;",
        f"public class {class_name}",
        "UnitTypeTable",
        f"public {class_name}(UnitTypeTable",
        "private Decision decide(AgentContext context)",
        "private List<ActionProposal> economy(AgentContext context)",
        "private List<ActionProposal> combat(AgentContext context)",
        "private List<ActionProposal> expansion(AgentContext context)",
        "private Unit selectTarget(AgentContext context, Unit actor, List<Unit> candidates)",
        "private PathChoice findPath(AgentContext context, Unit unit, int targetX, int targetY)",
    ]
    missing = [token for token in required_tokens if token not in source]
    if missing:
        raise ValueError(f"Generated Java source is missing required tokens: {', '.join(missing)}")
    forbidden_patterns = [
        r"\bSystem\.getenv\b",
        r"\bURL\b",
        r"\bHttpClient\b",
        r"/v1/chat/completions",
        r"\bSocket\b",
        r"\bFiles\.read",
        r"\bProcessBuilder\b",
        r"\bRuntime\.getRuntime\b",
        r"\bOptional\b",
        r"\bStrategyTable\b",
        r"\.stream\s*\(",
        r"->",
    ]
    if any(re.search(pattern, source) for pattern in forbidden_patterns):
        raise ValueError(
            "Generated Java agent must not use forbidden APIs, custom strategy classes, "
            "streams, lambdas, network, file, process, or runtime LLM APIs."
        )
