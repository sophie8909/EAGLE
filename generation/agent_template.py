"""Repository-backed complete single-file Java template."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_TEMPLATE_PATH = (
    REPOSITORY_ROOT / "eagle" / "java_templates" / "CandidateAgent.java"
)
STRATEGY_START_MARKER = "// EAGLE_AGENT_STRATEGY_START"
STRATEGY_END_MARKER = "// EAGLE_AGENT_STRATEGY_END"
ACTION_HELPERS_START_MARKER = "// EAGLE_ACTION_HELPERS_START"
ACTION_HELPERS_END_MARKER = "// EAGLE_ACTION_HELPERS_END"
ACTION_HELPER_METHODS: tuple[str, ...] = (
    "commandMove",
    "commandHarvest",
    "commandTrain",
    "commandBuild",
    "commandAttack",
    "commandIdle",
)
MICRORTS_BLANK_STRATEGY_PROMPT = (
    "Design one complete MicroRTS strategy in one CandidateAgent.java file. "
    "The Java template marks the editable strategy region with "
    "EAGLE_AGENT_STRATEGY_START and EAGLE_AGENT_STRATEGY_END comments. "
    "Control units through the six fixed action helpers: commandMove, "
    "commandHarvest, commandTrain, commandBuild, commandAttack, and commandIdle. "
    "Return the entire compilable Java source file, not JSON or partial method bodies."
)


@dataclass(frozen=True)
class JavaTemplatePaths:
    agent_template_path: Path = DEFAULT_AGENT_TEMPLATE_PATH


def validate_java_template(paths: JavaTemplatePaths) -> None:
    path = paths.agent_template_path
    if not path.is_file():
        raise ValueError(f"Java agent template does not exist: {path}")
    template = path.read_text(encoding="utf-8")
    if "public final class CandidateAgent extends AbstractionLayerAI" not in template:
        raise ValueError(
            "Java agent template must declare CandidateAgent as an AbstractionLayerAI."
        )
    _validate_marker_pair(
        template,
        STRATEGY_START_MARKER,
        STRATEGY_END_MARKER,
        "Agent strategy",
    )
    _validate_marker_pair(
        template,
        ACTION_HELPERS_START_MARKER,
        ACTION_HELPERS_END_MARKER,
        "Action helper",
    )
    if "EAGLE_BODY:" in template:
        raise ValueError("Java agent template must not contain EAGLE_BODY placeholders.")
    for helper in ACTION_HELPER_METHODS:
        count = len(re.findall(rf"\bprivate\s+boolean\s+{helper}\s*\(", template))
        if count != 1:
            raise ValueError(f"Action helper {helper} must exist exactly once; found {count}.")
    if "return translateActions(player, gs);" not in template:
        raise ValueError("Java agent template must translate AbstractionLayerAI actions.")


def _validate_marker_pair(
    source: str,
    start_marker: str,
    end_marker: str,
    label: str,
) -> None:
    start_count = source.count(start_marker)
    end_count = source.count(end_marker)
    if start_count != 1 or end_count != 1:
        raise ValueError(
            f"{label} markers must each exist exactly once; "
            f"found start={start_count}, end={end_count}."
        )
    if source.index(start_marker) >= source.index(end_marker):
        raise ValueError(f"{label} start marker must appear before its end marker.")


def load_java_template(paths: JavaTemplatePaths) -> str:
    validate_java_template(paths)
    return paths.agent_template_path.read_text(encoding="utf-8")


def extract_strategy_region(source: str) -> str:
    _validate_marker_pair(
        source,
        STRATEGY_START_MARKER,
        STRATEGY_END_MARKER,
        "Agent strategy",
    )
    start = source.index(STRATEGY_START_MARKER) + len(STRATEGY_START_MARKER)
    end = source.index(STRATEGY_END_MARKER)
    region = source[start:end].strip()
    if not region:
        raise ValueError("Agent strategy region must not be empty.")
    return region


def get_seed_prompt_template(name: str) -> str:
    if name == "microrts_blank_strategy_agent":
        return MICRORTS_BLANK_STRATEGY_PROMPT
    raise ValueError(f"Unknown seed_prompt_template: {name}")


def microrts_blank_strategy_prompt() -> str:
    return MICRORTS_BLANK_STRATEGY_PROMPT


def render_blank_strategy_agent(class_name: str = "CandidateAgent") -> str:
    if class_name != "CandidateAgent":
        raise ValueError("Repository template declares only CandidateAgent.")
    return load_java_template(JavaTemplatePaths())
