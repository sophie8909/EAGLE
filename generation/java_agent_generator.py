"""Prompt-to-Java generation wrapper and source validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from eagle.candidate import Candidate

from .backend import GenerationBackend, generated_class_name
from .agent_template import render_get_parameters_method, render_operation_helper_methods
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
    source = re.sub(r"(?m)^\s*//\s*Helper methods\.\.\.\s*$\n?", "", source)

    if "UnitTypeTable" in source and "import rts.units.UnitTypeTable;" not in source:
        source = re.sub(
            r"(?m)^(package\s+ai\.generated;\s*)$",
            "\\1\n\nimport rts.units.UnitTypeTable;",
            source,
            count=1,
        )
    source = repair_abstraction_agent_source(source)
    return source


def repair_abstraction_agent_source(source: str) -> str:
    """Restore required helper methods if an LLM elides the template tail."""

    if "extends AbstractionLayerAI" not in source:
        return source

    required_imports = [
        "import ai.abstraction.AbstractionLayerAI;",
        "import ai.abstraction.pathfinding.AStarPathFinding;",
        "import ai.abstraction.pathfinding.PathFinding;",
        "import ai.core.AI;",
        "import ai.core.ParameterSpecification;",
        "import java.util.ArrayList;",
        "import java.util.List;",
        "import rts.GameState;",
        "import rts.PhysicalGameState;",
        "import rts.PlayerAction;",
        "import rts.units.Unit;",
        "import rts.units.UnitType;",
        "import rts.units.UnitTypeTable;",
    ]
    for import_line in required_imports:
        source = ensure_import(source, import_line)

    methods_to_append: list[str] = []
    if "private boolean commandMove(" not in source or "private void applyAutoDefense(" not in source:
        methods_to_append.append(render_operation_helper_methods())
    if "List<ParameterSpecification> getParameters()" not in source:
        methods_to_append.append(render_get_parameters_method())
    if not methods_to_append:
        return source
    return insert_before_final_class_brace(source, "\n".join(methods_to_append))


def ensure_import(source: str, import_line: str) -> str:
    if import_line in source:
        return source
    package_match = re.search(r"(?m)^package\s+ai\.generated;\s*$", source)
    if package_match:
        insert_at = package_match.end()
        return source[:insert_at] + "\n\n" + import_line + source[insert_at:]
    return import_line + "\n" + source


def insert_before_final_class_brace(source: str, block: str) -> str:
    stripped = source.rstrip()
    if not stripped.endswith("}"):
        return source + "\n" + block + "\n"
    prefix = stripped[:-1].rstrip()
    return prefix + "\n" + block.rstrip() + "\n}\n"


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
