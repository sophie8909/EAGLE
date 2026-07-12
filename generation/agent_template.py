"""Fixed Java wrapper and generated behavior skeleton for MicroRTS agents."""

from __future__ import annotations

from eagle.candidate import DEFAULT_MODULE_BODIES, MODULE_NAMES
from eagle.module_contract import MODULE_METHOD_CONTRACTS

WRAPPER_TEMPLATE = """package ai.generated;

import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PlayerAction;
import rts.PlayerActionGenerator;
import rts.units.Unit;
import rts.units.UnitTypeTable;

public final class {class_name} extends AI {{
    private final {behavior_class_name} behaviors = new {behavior_class_name}();

    public {class_name}(UnitTypeTable utt) {{}}
    public {class_name}() {{}}
    @Override public void reset() {{}}
    @Override public AI clone() {{ return new {class_name}(); }}

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {{
        try {{
            if (!gs.canExecuteAnyAction(player)) return new PlayerAction();
            AgentContext context = new AgentContext(player, gs, new ArrayList<>(gs.getUnits()));
            return executeDecision(context, behaviors.decide(context));
        }} catch (Exception exc) {{
            PlayerAction fallback = new PlayerAction();
            fallback.fillWithNones(gs, player, 10);
            return fallback;
        }}
    }}

    private PlayerAction executeDecision(AgentContext context, Decision decision) throws Exception {{
        PlayerActionGenerator generator = new PlayerActionGenerator(context.gs, context.player);
        PlayerAction action = generator.getRandom();
        action.fillWithNones(context.gs, context.player, 10);
        return action;
    }}

    @Override public List<ParameterSpecification> getParameters() {{ return new ArrayList<>(); }}
}}

final class AgentContext {{
    final int player; final GameState gs; final List<Unit> units;
    AgentContext(int player, GameState gs, List<Unit> units) {{ this.player = player; this.gs = gs; this.units = units; }}
}}
final class Decision {{ final List<ActionProposal> proposals = new ArrayList<>(); }}
final class ActionProposal {{
    final Unit actor; final Unit target; final String intent; final int targetX; final int targetY;
    ActionProposal(Unit actor, Unit target, String intent, int targetX, int targetY) {{
        this.actor = actor; this.target = target; this.intent = intent; this.targetX = targetX; this.targetY = targetY;
    }}
}}
final class PathChoice {{
    final int x; final int y;
    PathChoice(int x, int y) {{ this.x = x; this.y = y; }}
}}
"""

BEHAVIORS_TEMPLATE = """package ai.generated;

import java.util.ArrayList;
import java.util.List;
import rts.units.Unit;

public final class {behavior_class_name} {{
{methods}
}}
"""

MICRORTS_BLANK_STRATEGY_PROMPT = """Describe one complete MicroRTS strategy implemented by six predefined behavior functions: controller, economy, combat, expansion, target selection, and path selection. The generator returns one JSON object containing all six Java method bodies. The fixed wrapper owns framework lifecycle, context collection, legality handling, and PlayerAction assembly. Generated code cannot add methods, fields, types, imports, package declarations, or markdown."""


def behavior_class_name(class_name: str) -> str:
    return f"{class_name}Behaviors"


def render_agent_wrapper(class_name: str) -> str:
    return WRAPPER_TEMPLATE.format(class_name=class_name, behavior_class_name=behavior_class_name(class_name))


def render_behavior_class(class_name: str, module_bodies: dict[str, str]) -> str:
    methods = []
    for name in MODULE_NAMES:
        contract = MODULE_METHOD_CONTRACTS[name]
        body = module_bodies.get(name, DEFAULT_MODULE_BODIES[name]).strip()
        methods.append(f"    {contract.declaration.replace('private ', '')} {{\n{indent_body(body, 8)}\n    }}")
    return BEHAVIORS_TEMPLATE.format(behavior_class_name=behavior_class_name(class_name), methods="\n\n".join(methods))


def render_blank_strategy_agent(class_name: str) -> str:
    return render_agent_wrapper(class_name)


def render_function_agent(class_name: str, module_bodies: dict[str, str]) -> str:
    return render_behavior_class(class_name, module_bodies)


def indent_body(body: str, spaces: int = 8) -> str:
    if not body.strip():
        raise ValueError("Generated function body must not be empty.")
    prefix = " " * spaces
    return "\n".join(prefix + line.rstrip() for line in body.strip().splitlines())


def microrts_blank_strategy_prompt() -> str:
    return MICRORTS_BLANK_STRATEGY_PROMPT


def get_seed_prompt_template(name: str) -> str:
    if name == "microrts_blank_strategy_agent":
        return microrts_blank_strategy_prompt()
    raise ValueError(f"Unknown seed_prompt_template: {name}")
