"""Complete Java source generation, validation, strategy-region extraction, and persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from eagle.candidate import Candidate
from evaluation.code_quality import StrategyRegionScoreResult, evaluate_agent_strategy_region
from .agent_template import (
    ACTION_HELPER_METHODS,
    ACTION_HELPERS_END_MARKER,
    ACTION_HELPERS_START_MARKER,
    STRATEGY_END_MARKER,
    STRATEGY_START_MARKER,
    JavaTemplatePaths,
    extract_strategy_region,
    load_java_template,
)
from .backend import GenerationBackend


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


def generate_java_agent(
    candidate: Candidate,
    backend: GenerationBackend,
    workspace_dir: Path,
    *,
    template_paths: JavaTemplatePaths | None = None,
) -> GeneratedJavaAgent:
    result = generate_java_agent_result(
        candidate, backend, workspace_dir, template_paths=template_paths
    )
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
        load_java_template(paths)
        raw = backend.generate(candidate, "CandidateAgent")
        source = normalize_java_agent_source(extract_code_from_output(raw))
        validate_java_agent_source(source, "CandidateAgent")
        strategy_region = extract_strategy_region(source)
        region_score = evaluate_agent_strategy_region(strategy_region)
    except (RuntimeError, ValueError, OSError) as exc:
        reason = str(exc)
        strategy_region = locals().get("strategy_region", "")
        region_score = evaluate_agent_strategy_region(strategy_region, error=reason)
        return JavaAgentGenerationResult(
            raw_llm_output=locals().get("raw", ""),
            extracted_code=locals().get("source", ""),
            strategy_region=strategy_region,
            assembled_java=locals().get("source", ""),
            validation_result=ValidationResult(False, reason),
            strategy_region_score_result=region_score,
            failure_category=classify_generation_error(reason),
            failure_reason=reason,
        )

    package_dir = workspace_dir / candidate.id
    package_dir.mkdir(parents=True, exist_ok=True)
    source_path = package_dir / "CandidateAgent.java"
    source_path.write_text(source, encoding="utf-8")
    validation = ValidationResult(True, "")
    agent = GeneratedJavaAgent(
        "CandidateAgent", "ai.generated", source, source_path, raw, source,
        strategy_region, validation,
    )
    return JavaAgentGenerationResult(
        raw_llm_output=raw,
        extracted_code=source,
        strategy_region=strategy_region,
        assembled_java=source,
        validation_result=validation,
        strategy_region_score_result=region_score,
        agent=agent,
    )


def extract_code_from_output(raw_output: str) -> str:
    stripped = raw_output.strip()
    fence_marker = re.escape(chr(96) * 3)
    fence = re.fullmatch(
        rf"{fence_marker}(?:java)?\s*(.*?)\s*{fence_marker}",
        stripped,
        re.DOTALL | re.IGNORECASE,
    )
    if fence:
        stripped = fence.group(1).strip()
    elif chr(96) * 3 in stripped:
        raise ValueError(
            "Complete Java response must not contain partial markdown fences or surrounding text."
        )
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
        STRATEGY_START_MARKER,
        STRATEGY_END_MARKER,
        ACTION_HELPERS_START_MARKER,
        ACTION_HELPERS_END_MARKER,
    )
    missing = [token for token in required if token not in source]
    if missing:
        raise ValueError(f"Complete Java source is missing required content: {', '.join(missing)}")
    if not source.startswith("package ai.generated;"):
        raise ValueError("Complete Java source must start with package ai.generated;.")
    if "EAGLE_BODY:" in source:
        raise ValueError(
            "Complete Java source must use one marked strategy region, not EAGLE_BODY placeholders."
        )
    if not (
        source.index(STRATEGY_START_MARKER)
        < source.index(STRATEGY_END_MARKER)
        < source.index(ACTION_HELPERS_START_MARKER)
        < source.index(ACTION_HELPERS_END_MARKER)
    ):
        raise ValueError(
            "Complete Java source must keep the strategy region before the fixed action-helper region."
        )
    for marker in (
        STRATEGY_START_MARKER,
        STRATEGY_END_MARKER,
        ACTION_HELPERS_START_MARKER,
        ACTION_HELPERS_END_MARKER,
    ):
        if source.count(marker) != 1:
            raise ValueError(f"Complete Java source must preserve {marker} exactly once.")
    for helper in ACTION_HELPER_METHODS:
        count = len(re.findall(rf"\bprivate\s+boolean\s+{helper}\s*\(", source))
        if count != 1:
            raise ValueError(
                f"Complete Java source must preserve action helper {helper} exactly once; found {count}."
            )
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
        raise ValueError(
            "Complete Java source uses forbidden runtime I/O, process, or LLM APIs."
        )
    extract_strategy_region(source)


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
