"""Repository-backed single-file Java template rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from eagle.candidate import DEFAULT_MODULE_BODIES, MODULE_NAMES


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_TEMPLATE_PATH = REPOSITORY_ROOT / "eagle" / "java_templates" / "CandidateAgent.java"
PLACEHOLDER_PATTERN = re.compile(r"/\*\s*EAGLE_BODY:([A-Za-z0-9_]+)\s*\*/")
ACTION_HELPER_METHODS: tuple[str, ...] = (
    "commandMove",
    "commandHarvest",
    "commandTrain",
    "commandBuild",
    "commandAttack",
    "commandIdle",
)
MICRORTS_BLANK_STRATEGY_PROMPT = """Describe one complete MicroRTS strategy implemented in one CandidateAgent.java file. six predefined behavior functions are evolvable: controller, economy, combat, expansion, target selection, and path selection. The fixed agent supplies six typed action helpers: commandMove, commandHarvest, commandTrain, commandBuild, commandAttack, and commandIdle. Generated code fills only the six predefined method bodies and must use the provided helpers instead of assembling PlayerAction directly."""


@dataclass(frozen=True)
class JavaTemplatePaths:
    agent_template_path: Path = DEFAULT_AGENT_TEMPLATE_PATH


def validate_java_template(paths: JavaTemplatePaths) -> None:
    path = paths.agent_template_path
    if not path.is_file():
        raise ValueError(f"Java agent template does not exist: {path}")
    template = path.read_text(encoding="utf-8")
    if "public final class CandidateAgent extends AbstractionLayerAI" not in template:
        raise ValueError("Java agent template must declare CandidateAgent as an AbstractionLayerAI.")
    found = PLACEHOLDER_PATTERN.findall(template)
    for name in MODULE_NAMES:
        count = found.count(name)
        if count != 1:
            raise ValueError(f"Agent placeholder EAGLE_BODY:{name} must exist exactly once; found {count}.")
    unknown = sorted(set(found) - set(MODULE_NAMES))
    if unknown:
        raise ValueError(f"Unknown agent placeholders: {', '.join(unknown)}")
    for helper in ACTION_HELPER_METHODS:
        count = len(re.findall(rf"\bprivate\s+boolean\s+{helper}\s*\(", template))
        if count != 1:
            raise ValueError(f"Action helper {helper} must exist exactly once; found {count}.")
    if "return translateActions(player, gs);" not in template:
        raise ValueError("Java agent template must translate AbstractionLayerAI actions.")


def load_java_template(paths: JavaTemplatePaths) -> str:
    validate_java_template(paths)
    return paths.agent_template_path.read_text(encoding="utf-8")


def render_agent_template(template: str, module_bodies: dict[str, str]) -> str:
    unknown = sorted(set(module_bodies) - set(MODULE_NAMES))
    missing = sorted(set(MODULE_NAMES) - set(module_bodies))
    if unknown:
        raise ValueError(f"Unknown generated function names: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"Missing generated function names: {', '.join(missing)}")
    rendered = template
    for name in MODULE_NAMES:
        marker = f"/* EAGLE_BODY:{name} */"
        count = rendered.count(marker)
        if count != 1:
            raise ValueError(f"Agent placeholder EAGLE_BODY:{name} must exist exactly once; found {count}.")
        rendered = rendered.replace(marker, indent_body(module_bodies[name], 8), 1)
    if "EAGLE_BODY" in rendered:
        raise ValueError("Rendered Java agent contains unresolved EAGLE_BODY placeholders.")
    return rendered


def indent_body(body: str, spaces: int = 8) -> str:
    if not body.strip():
        raise ValueError("Generated function body must not be empty.")
    prefix = " " * spaces
    return "\n".join(prefix + line.rstrip() for line in body.strip().splitlines())


def get_seed_prompt_template(name: str) -> str:
    if name == "microrts_blank_strategy_agent":
        return MICRORTS_BLANK_STRATEGY_PROMPT
    raise ValueError(f"Unknown seed_prompt_template: {name}")


def microrts_blank_strategy_prompt() -> str:
    return MICRORTS_BLANK_STRATEGY_PROMPT


def render_blank_strategy_agent(class_name: str = "CandidateAgent") -> str:
    return render_function_agent(class_name, DEFAULT_MODULE_BODIES)


def render_function_agent(class_name: str, module_bodies: dict[str, str]) -> str:
    if class_name != "CandidateAgent":
        raise ValueError("Repository template declares only CandidateAgent.")
    template = load_java_template(JavaTemplatePaths())
    return render_agent_template(template, module_bodies)