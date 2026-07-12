"""Repository-backed Java template loading and behavior-body rendering."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from eagle.candidate import MODULE_NAMES
from eagle.module_contract import MODULE_METHOD_CONTRACTS

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_TEMPLATE_PATH = REPOSITORY_ROOT / "eagle" / "java_templates" / "CandidateAgent.java"
DEFAULT_BEHAVIORS_TEMPLATE_PATH = REPOSITORY_ROOT / "eagle" / "java_templates" / "CandidateBehaviors.java"
PLACEHOLDER_PATTERN = re.compile(r"/\*\s*EAGLE_BODY:([A-Za-z0-9_]+)\s*\*/")
MICRORTS_BLANK_STRATEGY_PROMPT = """Describe one complete MicroRTS strategy implemented by six predefined behavior functions: controller, economy, combat, expansion, target selection, and path selection. The generator returns one JSON object containing all six Java method bodies. The fixed wrapper owns framework lifecycle, context collection, legality handling, and PlayerAction assembly. Generated code cannot add methods, fields, types, imports, package declarations, or markdown."""

@dataclass(frozen=True)
class JavaTemplatePaths:
    agent_template_path: Path = DEFAULT_AGENT_TEMPLATE_PATH
    behaviors_template_path: Path = DEFAULT_BEHAVIORS_TEMPLATE_PATH

def validate_java_templates(paths: JavaTemplatePaths) -> None:
    for label, path in (("agent", paths.agent_template_path), ("behaviors", paths.behaviors_template_path)):
        if not path.is_file(): raise ValueError(f"Java {label} template does not exist: {path}")
    agent = paths.agent_template_path.read_text(encoding="utf-8")
    behaviors = paths.behaviors_template_path.read_text(encoding="utf-8")
    if "public final class CandidateAgent" not in agent: raise ValueError("Java agent template must declare public final class CandidateAgent.")
    if "public final class CandidateBehaviors" not in behaviors: raise ValueError("Java behaviors template must declare public final class CandidateBehaviors.")
    found = PLACEHOLDER_PATTERN.findall(behaviors)
    for name in MODULE_NAMES:
        count = found.count(name)
        if count != 1: raise ValueError(f"Behavior placeholder EAGLE_BODY:{name} must exist exactly once; found {count}.")
    unknown = sorted(set(found) - set(MODULE_NAMES))
    if unknown: raise ValueError(f"Unknown behavior placeholders: {', '.join(unknown)}")
    allowed = {contract.method_name for contract in MODULE_METHOD_CONTRACTS.values()}
    called = set(re.findall(r"\bbehaviors\.([A-Za-z_$][\w$]*)\s*\(", agent))
    if called - allowed: raise ValueError(f"CandidateAgent calls unknown behavior methods: {', '.join(sorted(called - allowed))}")
    if allowed - called: raise ValueError(f"CandidateAgent must call every predefined behavior method; missing: {', '.join(sorted(allowed - called))}")
    if "EAGLE_BODY" in agent: raise ValueError("CandidateAgent must not contain EAGLE_BODY placeholders.")

def load_java_templates(paths: JavaTemplatePaths) -> tuple[str, str]:
    validate_java_templates(paths)
    return paths.agent_template_path.read_text(encoding="utf-8"), paths.behaviors_template_path.read_text(encoding="utf-8")

def render_behavior_template(template: str, module_bodies: dict[str, str]) -> str:
    unknown = sorted(set(module_bodies) - set(MODULE_NAMES))
    missing = sorted(set(MODULE_NAMES) - set(module_bodies))
    if unknown: raise ValueError(f"Unknown generated function names: {', '.join(unknown)}")
    if missing: raise ValueError(f"Missing generated function names: {', '.join(missing)}")
    rendered = template
    for name in MODULE_NAMES:
        marker = f"/* EAGLE_BODY:{name} */"
        count = rendered.count(marker)
        if count != 1: raise ValueError(f"Behavior placeholder EAGLE_BODY:{name} must exist exactly once; found {count}.")
        rendered = rendered.replace(marker, indent_body(module_bodies[name], 8), 1)
    if "EAGLE_BODY" in rendered: raise ValueError("Rendered behavior source contains unresolved EAGLE_BODY placeholders.")
    return rendered

def indent_body(body: str, spaces: int = 8) -> str:
    if not body.strip(): raise ValueError("Generated function body must not be empty.")
    prefix = " " * spaces
    return "\n".join(prefix + line.rstrip() for line in body.strip().splitlines())

def get_seed_prompt_template(name: str) -> str:
    if name == "microrts_blank_strategy_agent": return MICRORTS_BLANK_STRATEGY_PROMPT
    raise ValueError(f"Unknown seed_prompt_template: {name}")

def microrts_blank_strategy_prompt() -> str:
    return MICRORTS_BLANK_STRATEGY_PROMPT


def render_blank_strategy_agent(class_name: str = "CandidateAgent") -> str:
    if class_name != "CandidateAgent":
        raise ValueError("Repository template declares only CandidateAgent.")
    agent, _ = load_java_templates(JavaTemplatePaths())
    return agent


def render_function_agent(class_name: str, module_bodies: dict[str, str]) -> str:
    if class_name != "CandidateAgent":
        raise ValueError("Repository template declares only CandidateAgent.")
    _, template = load_java_templates(JavaTemplatePaths())
    return render_behavior_template(template, module_bodies)
