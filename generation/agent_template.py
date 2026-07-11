"""Fixed Java skeleton for function-based MicroRTS generated agents."""

from __future__ import annotations

from eagle.candidate import DEFAULT_MODULE_BODIES, MODULE_NAMES


FUNCTION_AGENT_TEMPLATE = """package ai.generated;

import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PlayerAction;
import rts.PlayerActionGenerator;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitTypeTable;

public class {class_name} extends AI {{
    public {class_name}(UnitTypeTable utt) {{
    }}

    public {class_name}() {{
    }}

    @Override
    public void reset() {{
    }}

    @Override
    public AI clone() {{
        return new {class_name}();
    }}

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {{
        try {{
            if (!gs.canExecuteAnyAction(player)) {{
                return new PlayerAction();
            }}
            AgentContext context = new AgentContext(player, gs, units(gs));
            return executeDecision(context, decide(context));
        }} catch (Exception exc) {{
            PlayerAction fallback = new PlayerAction();
            fallback.fillWithNones(gs, player, 10);
            return fallback;
        }}
    }}

    private Decision decide(AgentContext context) throws Exception {{
        {controller_body}
    }}

    private List<ActionProposal> economy(AgentContext context) throws Exception {{
        {economy_body}
    }}

    private List<ActionProposal> combat(AgentContext context) throws Exception {{
        {combat_body}
    }}

    private List<ActionProposal> expansion(AgentContext context) throws Exception {{
        {expansion_body}
    }}

    private Unit selectTarget(AgentContext context, Unit actor, List<Unit> candidates) throws Exception {{
        {target_selection_body}
    }}

    private PathChoice findPath(AgentContext context, Unit unit, int targetX, int targetY) throws Exception {{
        {path_selection_body}
    }}

    private PlayerAction executeDecision(AgentContext context, Decision decision) throws Exception {{
        PlayerActionGenerator generator = new PlayerActionGenerator(context.gs, context.player);
        PlayerAction action = generator.getRandom();
        action.fillWithNones(context.gs, context.player, 10);
        return action;
    }}

    private List<Unit> units(GameState gs) {{
        return new ArrayList<>(gs.getUnits());
    }}

    @Override
    public List<ParameterSpecification> getParameters() {{
        return new ArrayList<>();
    }}

    private static class AgentContext {{
        final int player;
        final GameState gs;
        final List<Unit> units;

        AgentContext(int player, GameState gs, List<Unit> units) {{
            this.player = player;
            this.gs = gs;
            this.units = units;
        }}
    }}

    private static class Decision {{
        final List<ActionProposal> proposals = new ArrayList<>();
    }}

    private static class ActionProposal {{
        final Unit actor;
        final Unit target;
        final String intent;
        final int targetX;
        final int targetY;

        ActionProposal(Unit actor, Unit target, String intent, int targetX, int targetY) {{
            this.actor = actor;
            this.target = target;
            this.intent = intent;
            this.targetX = targetX;
            this.targetY = targetY;
        }}
    }}

    private static class PathChoice {{
        final int x;
        final int y;

        PathChoice(int x, int y) {{
            this.x = x;
            this.y = y;
        }}
    }}
}}
"""


MICRORTS_BLANK_STRATEGY_PROMPT = """Generate Java statements for one function body in this MicroRTS AI.

The agent has six evolvable functions:
- controller / decision
- economy
- combat
- expansion
- target selection
- path selection

The scaffold owns MicroRTS API interaction, AgentContext construction, action legality checks,
conflict handling, and PlayerAction assembly. Generated functions return structured intermediate
values such as Decision, ActionProposal, Unit, or PathChoice.

Rules:
- Output only Java statements for the requested function body.
- Do not output package declarations, imports, classes, constructors, fields, or helper methods.
- Do not mutate global state.
- Do not use custom imports, Optional, StrategyTable, streams, lambdas, files, network, subprocesses, or runtime LLM code.
- No markdown fences.

Current known-good scaffold:
```java
{template}
```
"""


def render_blank_strategy_agent(class_name: str) -> str:
    return render_function_agent(class_name, DEFAULT_MODULE_BODIES)


def render_function_agent(class_name: str, module_bodies: dict[str, str]) -> str:
    bodies = {name: indent_body(module_bodies.get(name, DEFAULT_MODULE_BODIES[name])) for name in MODULE_NAMES}
    return FUNCTION_AGENT_TEMPLATE.format(
        class_name=class_name,
        controller_body=bodies["controller"],
        economy_body=bodies["economy"],
        combat_body=bodies["combat"],
        expansion_body=bodies["expansion"],
        target_selection_body=bodies["target_selection"],
        path_selection_body=bodies["path_selection"],
    )


def indent_body(body: str) -> str:
    if not body.strip():
        return "return new ArrayList<>();"
    return "\n        ".join(line.rstrip() for line in body.strip().splitlines())


def microrts_blank_strategy_prompt() -> str:
    return MICRORTS_BLANK_STRATEGY_PROMPT.format(template=render_blank_strategy_agent("CLASS_NAME"))


def get_seed_prompt_template(name: str) -> str:
    if name == "microrts_blank_strategy_agent":
        return microrts_blank_strategy_prompt()
    raise ValueError(f"Unknown seed_prompt_template: {name}")
