"""Complete Java source generation and external runtime-contract validation."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from eagle.candidate import Candidate
from evaluation.code_quality import StrategyRegionScoreResult, evaluate_agent_strategy_region
from .agent_template import JavaTemplatePaths, extract_strategy_region
from .backend import GenerationBackend


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str = ""
    passed_checks: tuple[str, ...] = ()
    failed_checks: tuple[dict[str, str], ...] = ()
    blocked_checks: tuple[dict[str, str], ...] = ()
    failure_reason: str | None = None

    @property
    def status(self) -> str:
        return "passed" if self.ok else "failed"

    def to_json_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "ok": self.ok,
            "passed_checks": list(self.passed_checks),
            "failed_checks": [dict(item) for item in self.failed_checks],
            "blocked_checks": [dict(item) for item in self.blocked_checks],
            "failure_reason": self.failure_reason or self.error or None,
            "error": self.error,
        }


@dataclass(frozen=True)
class GeneratedJavaAgent:
    class_name: str
    package_name: str
    source: str
    source_path: Path
    raw_llm_output: str = ""
    extracted_code: str = ""
    strategy_region: str = ""
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
    strategy_region: str = ""
    assembled_java: str = ""
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(False, "not_run"))
    strategy_region_score_result: StrategyRegionScoreResult | None = None
    agent: GeneratedJavaAgent | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    failure_stage: str | None = None
    validation_timing: dict[str, object] = field(default_factory=dict)


VALIDATION_CHECK_NAMES = ("package", "public_class", "superclass", "constructors", "callable_methods", "forbidden_behaviors", "runtime_contract")

FORBIDDEN_BEHAVIOR_PATTERNS = (
    ("network_import", r"\bimport\s+java\.(?:net|nio\.channels)\b"),
    ("file_io_import", r"\bimport\s+java\.(?:io|nio\.file)\b"),
    ("network_api", r"\b(?:URL|URI|Socket|HttpClient|URLConnection)\b"),
    ("file_io_api", r"\b(?:File|Files|FileInputStream|FileOutputStream|RandomAccessFile|PrintWriter|BufferedReader|BufferedWriter|InputStream|OutputStream|Paths)\b"),
    ("process_creation", r"\b(?:ProcessBuilder|Runtime\.getRuntime)\b"),
    ("environment_access", r"\bSystem\.(?:getenv|getProperty|setProperty)\s*\("),
    ("process_control", r"\bSystem\.(?:exit|load|loadLibrary)\s*\("),
    ("llm_endpoint", r"/v1/chat/completions|\b(?:OpenAI|ChatCompletion)\b"),
    ("reflection_api", r"\b(?:setAccessible|MethodHandles|Unsafe)\b"),
    ("class_loading_api", r"\b(?:ClassLoader|URLClassLoader)\b"),
)

ALLOWED_IMPORT_PREFIXES = ("ai.", "rts.", "util.", "java.util.", "java.lang.")


def generate_java_agent(candidate: Candidate, backend: GenerationBackend, workspace_dir: Path, *, template_paths: JavaTemplatePaths | None = None) -> GeneratedJavaAgent:
    result = generate_java_agent_result(candidate, backend, workspace_dir, template_paths=template_paths)
    if result.agent is None:
        raise ValueError(result.failure_reason or "Java agent generation failed.")
    return result.agent


def generate_java_agent_result(candidate: Candidate, backend: GenerationBackend, workspace_dir: Path, *, template_paths: JavaTemplatePaths | None = None) -> JavaAgentGenerationResult:
    try:
        raw = backend.generate(candidate, "CandidateAgent")
    except (RuntimeError, OSError, ValueError) as exc:
        reason = str(exc)
        blocked = blocked_validation_result("Source validation was blocked because Java generation failed.")
        return JavaAgentGenerationResult(validation_result=blocked, strategy_region_score_result=evaluate_agent_strategy_region("", error=reason), failure_category=classify_generation_error(reason), failure_reason=reason, failure_stage="generation", validation_timing=validation_timing("blocked", blocked.error))
    try:
        source = normalize_java_agent_source(extract_code_from_output(raw))
    except (ValueError, OSError) as exc:
        reason = str(exc)
        blocked = blocked_validation_result("Source validation was blocked because no complete Java source was generated.")
        return JavaAgentGenerationResult(raw_llm_output=raw, validation_result=blocked, strategy_region_score_result=evaluate_agent_strategy_region("", error=reason), failure_category=classify_generation_error(reason), failure_reason=reason, failure_stage="generation", validation_timing=validation_timing("blocked", blocked.error))

    started_at = _utc_now()
    started = time.monotonic()
    validation = validate_generated_java_source(source, "CandidateAgent")
    finished_at = _utc_now()
    validation_record = validation_timing("success" if validation.ok else "failed", validation.failure_reason or validation.error, started_at=started_at, finished_at=finished_at, duration_seconds=max(0.0, time.monotonic() - started))
    try:
        strategy_region = extract_strategy_region(source)
    except ValueError:
        strategy_region = ""
    region_score = evaluate_agent_strategy_region(strategy_region, error=validation.failure_reason if not validation.ok else None)
    if not validation.ok:
        reason = validation.failure_reason or validation.error
        return JavaAgentGenerationResult(raw_llm_output=raw, extracted_code=source, strategy_region=strategy_region, assembled_java=source, validation_result=validation, strategy_region_score_result=region_score, failure_category="Java validation failure", failure_reason=reason, failure_stage="validation", validation_timing=validation_record)

    package_dir = workspace_dir / candidate.id
    package_dir.mkdir(parents=True, exist_ok=True)
    source_path = package_dir / "CandidateAgent.java"
    source_path.write_text(source, encoding="utf-8")
    agent = GeneratedJavaAgent("CandidateAgent", "ai.generated", source, source_path, raw, source, strategy_region, validation)
    return JavaAgentGenerationResult(raw_llm_output=raw, extracted_code=source, strategy_region=strategy_region, assembled_java=source, validation_result=validation, strategy_region_score_result=region_score, agent=agent, validation_timing=validation_record)


def extract_code_from_output(raw_output: str) -> str:
    stripped = raw_output.strip()
    fence_marker = re.escape(chr(96) * 3)
    fence = re.fullmatch(rf"{fence_marker}(?:java)?\s*(.*?)\s*{fence_marker}", stripped, re.DOTALL | re.IGNORECASE)
    if fence:
        stripped = fence.group(1).strip()
    elif chr(96) * 3 in stripped:
        raise ValueError("Complete Java response must not contain partial markdown fences or surrounding text.")
    if not stripped:
        raise ValueError("Generated Java response is empty.")
    return stripped


def clean_generated_java_output(output: str) -> str:
    return extract_code_from_output(output)


def normalize_java_agent_source(source: str) -> str:
    return source.lstrip("\ufeff").strip()


def validate_generated_java_source(source: str, class_name: str) -> ValidationResult:
    if not source.strip():
        return blocked_validation_result("Generated Java source is empty.")
    passed: list[str] = []
    failed: list[dict[str, str]] = []
    def check(name: str, condition: bool, reason: str) -> None:
        if condition:
            passed.append(name)
        else:
            failed.append({"check": name, "reason": reason})

    package_match = re.search(r"(?m)^\s*package\s+([\w.]+)\s*;", source)
    check("package", bool(package_match and package_match.group(1) == "ai.generated"), "package must be ai.generated")
    public_class = re.search(rf"\bpublic\s+(?:final\s+)?class\s+{re.escape(class_name)}\b", source)
    check("public_class", public_class is not None, f"public class {class_name} is required")
    superclass = re.search(rf"\bclass\s+{re.escape(class_name)}\b[^{{]*\bextends\s+AbstractionLayerAI\b", source)
    check("superclass", superclass is not None, "class must extend AbstractionLayerAI")
    constructor_one = re.search(rf"\bpublic\s+{re.escape(class_name)}\s*\(\s*UnitTypeTable\s+\w+\s*\)", source)
    constructor_two = re.search(rf"\bpublic\s+{re.escape(class_name)}\s*\(\s*UnitTypeTable\s+\w+\s*,\s*AStarPathFinding\s+\w+\s*\)", source)
    check("constructors", constructor_one is not None and constructor_two is not None, "both required constructors are required")
    methods_ok = all(re.search(pattern, source) is not None for pattern in (r"\bpublic\s+PlayerAction\s+getAction\s*\(\s*int\s+\w+\s*,\s*GameState\s+\w+\s*\)", r"\bpublic\s+void\s+reset\s*\(\s*\)", r"\bpublic\s+AI\s+clone\s*\(\s*\)"))
    check("callable_methods", methods_ok, "public getAction, reset, and clone methods are required")
    imports = re.findall(r"(?m)^\s*import\s+(?:static\s+)?([\w]+(?:\.[\w]+)*)", source)
    unavailable_imports = sorted(name for name in imports if not any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in ALLOWED_IMPORT_PREFIXES))
    forbidden = [name for name, pattern in FORBIDDEN_BEHAVIOR_PATTERNS if re.search(pattern, source)]
    if unavailable_imports:
        forbidden.append(f"unavailable_dependencies:{','.join(unavailable_imports)}")
    check("forbidden_behaviors", not forbidden, f"forbidden runtime behavior: {', '.join(forbidden)}")
    runtime_contract_ok = bool(package_match and public_class and superclass and constructor_one and constructor_two and methods_ok)
    check("runtime_contract", runtime_contract_ok, "the complete external MicroRTS runtime contract is not satisfied")
    failure_reason = failed[0]["reason"] if failed else None
    return ValidationResult(ok=not failed, error=failure_reason or "", passed_checks=tuple(passed), failed_checks=tuple(failed), failure_reason=failure_reason)


def blocked_validation_result(reason: str) -> ValidationResult:
    return ValidationResult(ok=False, error=reason, blocked_checks=tuple({"check": name, "reason": reason} for name in VALIDATION_CHECK_NAMES), failure_reason=reason)


def validate_java_agent_source(source: str, class_name: str) -> None:
    result = validate_generated_java_source(source, class_name)
    if not result.ok:
        raise ValueError(result.failure_reason or result.error or "Java source validation failed.")


def validate_assembled_java(source: str, class_name: str) -> ValidationResult:
    return validate_generated_java_source(source, class_name)


def validation_timing(status: str, error: str | None, *, started_at: str | None = None, finished_at: str | None = None, duration_seconds: float | None = None) -> dict[str, object]:
    return {"started_at": started_at, "finished_at": finished_at, "duration_seconds": duration_seconds, "status": status, "error": error or None}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_generation_error(reason: str) -> str:
    lowered = reason.lower()
    if "timeout" in lowered:
        return "Timeout"
    if "backend" in lowered or "http" in lowered:
        return "Backend request failure"
    return "Java validation failure"
