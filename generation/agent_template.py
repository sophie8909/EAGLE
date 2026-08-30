"""Repository-backed complete single-file Java template."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_TEMPLATE_PATH = (
    REPOSITORY_ROOT / "eagle" / "java_templates" / "CandidateAgent.java"
)
DEFAULT_INITIAL_JAVA_SEED_PATH = (
    REPOSITORY_ROOT / "eagle" / "java_seeds" / "CandidateAgent.java"
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

_JAVA_TOKEN_PATTERN = re.compile(
    r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*.*?\*/|'''
    r'''[A-Za-z_$][A-Za-z0-9_$]*|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[fFdDlL]?|'''
    r'''>=|<=|==|!=|&&|\|\||\+\+|--|<<|>>>|>>|->|::|\+=|-=|\*=|/=|%=|&=|\|=|\^=|'''
    r'''[^\s]''',
    re.DOTALL,
)
_JAVA_NON_CODE_PATTERN = re.compile(
    r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*.*?\*/''',
    re.DOTALL,
)
_PRIVATE_METHOD_PATTERN = re.compile(
    r"\bprivate\s+(?:static\s+)?(?:final\s+)?"
    r"[A-Za-z_$][A-Za-z0-9_$<>,.?\[\]\s]*\s+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*"
    r"\((?P<parameters>[^()]*)\)\s*(?:throws\s+[^\{]+)?\{",
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


def assemble_canonical_java_source(source: str, scaffold: str) -> str:
    """Rebuild a complete source from the scaffold and generated strategy region.

    The Generator still has to return a structurally complete CandidateAgent.
    Callers must validate that envelope before using this function.  This helper
    owns only the deterministic normalization step that prevents harmless model
    edits outside the strategy markers from becoming part of the phenotype.
    """

    strategy_region = extract_strategy_region(source)
    _validate_marker_pair(
        scaffold,
        STRATEGY_START_MARKER,
        STRATEGY_END_MARKER,
        "Agent strategy",
    )
    strategy_start = scaffold.index(STRATEGY_START_MARKER) + len(
        STRATEGY_START_MARKER
    )
    end_marker = scaffold.index(STRATEGY_END_MARKER)
    end_line_start = scaffold.rfind("\n", 0, end_marker) + 1
    return (
        scaffold[:strategy_start]
        + "\n"
        + strategy_region
        + "\n\n"
        + scaffold[end_line_start:]
    )


def fixed_scaffold_equivalent(source: str, scaffold: str) -> bool:
    """Compare every Java token outside the single editable strategy region."""

    return _fixed_source_tokens(source) == _fixed_source_tokens(scaffold)


def strategy_contract_errors(source: str) -> tuple[str, ...]:
    """Return deterministic Java-shape violations inside the editable region."""

    strategy = extract_strategy_region(source)
    code = _JAVA_NON_CODE_PATTERN.sub(" ", strategy)
    errors: list[str] = []
    if re.search(
        r"\bint\s*\[\s*\]\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*"
        r"(?:new\s+int\s*\[\s*\]\s*)?\{\s*\{",
        code,
    ):
        errors.append("nested coordinate pairs must be declared as int[][], not int[]")
    if re.search(r"\.getUnitAt\s*\(", code):
        errors.append("getUnitAt is not an available MicroRTS API; use isFreeCell(context, x, y)")
    if re.search(r"\.free\s*\(", code):
        errors.append(
            "strategy code must not call GameState.free directly; use isFreeCell(context, x, y)"
        )
    if re.search(r"\.getTerrain\s*\(", code):
        errors.append(
            "strategy code must not call PhysicalGameState.getTerrain directly; use isFreeCell(context, x, y)"
        )

    for match in _PRIVATE_METHOD_PATTERN.finditer(code):
        method_name = match.group("name")
        parameters = match.group("parameters")
        method_end = _matching_brace_end(code, match.end() - 1)
        if method_end is None:
            errors.append(f"method {method_name} has unbalanced braces")
            continue
        method = code[match.start():method_end]
        if re.search(r"\bcontext\s*\.", method) and not re.search(
            r"\bAgentContext\s+context\b",
            parameters,
        ):
            errors.append(
                f"method {method_name} uses context but does not declare AgentContext context"
            )
        if re.search(r"\bgameTime\b", method) and not re.search(
            r"\b(?:byte|short|int|long)\s+gameTime\b",
            method,
        ):
            errors.append(
                f"method {method_name} uses gameTime without an integer parameter or local declaration"
            )
    return tuple(dict.fromkeys(errors))


def _matching_brace_end(source: str, opening_index: int) -> int | None:
    depth = 0
    for index in range(opening_index, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _fixed_source_tokens(source: str) -> tuple[str, ...]:
    _validate_marker_pair(
        source,
        STRATEGY_START_MARKER,
        STRATEGY_END_MARKER,
        "Agent strategy",
    )
    start = source.index(STRATEGY_START_MARKER) + len(STRATEGY_START_MARKER)
    end = source.index(STRATEGY_END_MARKER)
    fixed_source = source[:start] + source[end:]
    return tuple(
        token
        for token in _JAVA_TOKEN_PATTERN.findall(fixed_source)
        if not token.startswith("//") and not token.startswith("/*")
    )


def microrts_blank_strategy_prompt() -> str:
    return ""


def render_blank_strategy_agent(class_name: str = "CandidateAgent") -> str:
    if class_name != "CandidateAgent":
        raise ValueError("Repository template declares only CandidateAgent.")
    return load_java_template(JavaTemplatePaths())
