"""Structured behavior generation, validation, rendering, and persistence."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from eagle.candidate import Candidate, MODULE_NAMES
from .agent_template import behavior_class_name, render_agent_wrapper, render_behavior_class
from .backend import GenerationBackend, generated_class_name
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
    behavior_source: str
    behavior_source_path: Path
    raw_llm_output: str = ""
    extracted_code: str = ""
    module_raw_outputs: dict[str, str] = field(default_factory=dict)
    module_bodies: dict[str, str] = field(default_factory=dict)
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(ok=True))
    @property
    def qualified_class_name(self) -> str: return f"{self.package_name}.{self.class_name}"
    @property
    def source_paths(self) -> tuple[Path, Path]: return (self.source_path, self.behavior_source_path)

@dataclass(frozen=True)
class JavaAgentGenerationResult:
    class_name: str
    package_name: str = "ai.generated"
    raw_llm_output: str = ""
    extracted_code: str = ""
    module_raw_outputs: dict[str, str] = field(default_factory=dict)
    module_bodies: dict[str, str] = field(default_factory=dict)
    assembled_java: str = ""
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(False, "not_run"))
    agent: GeneratedJavaAgent | None = None
    failure_category: str | None = None
    failure_reason: str | None = None

def generate_java_agent(candidate: Candidate, backend: GenerationBackend, workspace_dir: Path) -> GeneratedJavaAgent:
    result = generate_java_agent_result(candidate, backend, workspace_dir)
    if result.agent is None:
        raise ValueError(result.failure_reason or "Java agent generation failed.")
    return result.agent

def generate_java_agent_result(candidate: Candidate, backend: GenerationBackend, workspace_dir: Path) -> JavaAgentGenerationResult:
    class_name = generated_class_name(candidate.id)
    try:
        raw = backend.generate(candidate, class_name)
        bodies = parse_behavior_functions(raw)
        for name in MODULE_NAMES: validate_function_module(bodies[name], name)
        wrapper = render_agent_wrapper(class_name)
        behaviors = render_behavior_class(class_name, bodies)
    except (RuntimeError, ValueError, OSError) as exc:
        reason = str(exc)
        return JavaAgentGenerationResult(class_name=class_name, raw_llm_output=locals().get("raw", ""), module_bodies=locals().get("bodies", {}), validation_result=ValidationResult(False, reason), failure_category=classify_generation_error(reason), failure_reason=reason)
    package_dir = workspace_dir / candidate.id / "src" / "ai" / "generated"
    package_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = package_dir / f"{class_name}.java"
    behavior_path = package_dir / f"{behavior_class_name(class_name)}.java"
    wrapper_path.write_text(wrapper, encoding="utf-8")
    behavior_path.write_text(behaviors, encoding="utf-8")
    agent = GeneratedJavaAgent(class_name, "ai.generated", wrapper, wrapper_path, behaviors, behavior_path, raw, json.dumps({"functions": bodies}, ensure_ascii=False), {"all": raw}, bodies)
    return JavaAgentGenerationResult(class_name=class_name, raw_llm_output=raw, extracted_code=agent.extracted_code, module_raw_outputs={"all": raw}, module_bodies=bodies, assembled_java=behaviors, validation_result=ValidationResult(True), agent=agent)

def parse_behavior_functions(raw: str) -> dict[str, str]:
    if "```" in raw: raise ValueError("Generated behavior response must not contain markdown fences.")
    try: payload = json.loads(raw)
    except json.JSONDecodeError as exc: raise ValueError(f"Generated behavior response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"functions"} or not isinstance(payload["functions"], dict):
        raise ValueError("Generated behavior response must contain only a functions object.")
    functions = payload["functions"]
    unknown = set(functions) - set(MODULE_NAMES)
    missing = set(MODULE_NAMES) - set(functions)
    if unknown: raise ValueError(f"Unknown behavior function keys: {', '.join(sorted(unknown))}")
    if missing: raise ValueError(f"Missing behavior function keys: {', '.join(sorted(missing))}")
    if any(not isinstance(value, str) for value in functions.values()): raise ValueError("Every behavior function body must be a string.")
    return {name: functions[name] for name in MODULE_NAMES}

def assemble_java_agent(class_name: str, module_bodies: dict[str, str]) -> str:
    for name in MODULE_NAMES: validate_function_module(module_bodies[name], name)
    return render_behavior_class(class_name, module_bodies)

def extract_code_from_output(raw_output: str) -> str: return json.dumps({"functions": parse_behavior_functions(raw_output)}, ensure_ascii=False)
def clean_generated_java_output(output: str) -> str: return output.strip()
def normalize_java_agent_source(source: str) -> str: return source
def validate_java_agent_source(source: str, class_name: str) -> None:
    if f"public final class {class_name}" not in source: raise ValueError("Fixed wrapper class declaration is missing.")
def validate_assembled_java(source: str, class_name: str) -> ValidationResult: return ValidationResult(True)
def classify_generation_error(reason: str) -> str:
    lowered = reason.lower()
    if "timeout" in lowered: return "Timeout"
    if "backend" in lowered or "http" in lowered: return "Backend request failure"
    return "Java validation failure"
