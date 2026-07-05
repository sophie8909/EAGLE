"""Prompt-to-Java generation wrapper and source validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from eagle.candidate import Candidate

from .backend import GenerationBackend, generated_class_name
from .parsing import extract_java_source


@dataclass(frozen=True)
class GeneratedJavaAgent:
    class_name: str
    package_name: str
    source: str
    source_path: Path

    @property
    def qualified_class_name(self) -> str:
        return f"{self.package_name}.{self.class_name}"


def generate_java_agent(
    candidate: Candidate,
    backend: GenerationBackend,
    workspace_dir: Path,
) -> GeneratedJavaAgent:
    """Generate, validate, and persist one isolated Java source file."""

    class_name = generated_class_name(candidate.id)
    raw_output = backend.generate(candidate, class_name)
    source = extract_java_source(raw_output)
    source = normalize_java_agent_source(source)
    validate_java_agent_source(source, class_name)
    package_dir = workspace_dir / candidate.id / "src" / "ai" / "generated"
    package_dir.mkdir(parents=True, exist_ok=True)
    source_path = package_dir / f"{class_name}.java"
    source_path.write_text(source, encoding="utf-8")
    return GeneratedJavaAgent(
        class_name=class_name,
        package_name="ai.generated",
        source=source,
        source_path=source_path,
    )


def normalize_java_agent_source(source: str) -> str:
    """Repair small, common MicroRTS import/annotation mistakes in LLM output."""

    source = source.replace("import ai.UnitTypeTable;", "import rts.units.UnitTypeTable;")
    source = source.replace("import ai.core.UnitTypeTable;", "import rts.units.UnitTypeTable;")
    source = re.sub(r"(?m)^\s*@Override\s*\n\s*public\s+void\s+act\s*\(", "    public void act(", source)

    if "UnitTypeTable" in source and "import rts.units.UnitTypeTable;" not in source:
        source = re.sub(
            r"(?m)^(package\s+ai\.generated;\s*)$",
            "\\1\n\nimport rts.units.UnitTypeTable;",
            source,
            count=1,
        )
    return source


def validate_java_agent_source(source: str, class_name: str) -> None:
    required_tokens = [
        "package ai.generated;",
        f"public class {class_name}",
        "UnitTypeTable",
        f"public {class_name}(UnitTypeTable",
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
    ]
    if any(re.search(pattern, source) for pattern in forbidden_patterns):
        raise ValueError("Generated Java agent must not call network, file, process, or runtime LLM APIs.")
