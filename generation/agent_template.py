"""Built-in prompt and Java skeleton for MicroRTS generated agents."""

from __future__ import annotations


PASSIVE_AI_STRATEGY_BODY = """PlayerAction pa = new PlayerAction();
        pa.fillWithNones(gs, player, 10);
        return pa;"""


RANDOM_AI_AGENT_TEMPLATE = """package ai.generated;

import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PlayerAction;
import rts.PlayerActionGenerator;
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
            return chooseAction(player, gs);
        }} catch (Exception exc) {{
            return new PlayerAction();
        }}
    }}

    private PlayerAction chooseAction(int player, GameState gs) throws Exception {{
        {strategy_body}
    }}

    @Override
    public List<ParameterSpecification> getParameters() {{
        return new ArrayList<>();
    }}
}}
"""


MICRORTS_BLANK_STRATEGY_PROMPT = """Generate Java statements for the body of chooseAction in this MicroRTS AI.

MicroRTS baseline:
- The initial evolved strategy starts from ai.PassiveAI from this repository's MicroRTS source.
- The scaffold owns imports, class declaration, constructors, reset, clone, getAction, and getParameters.
- getAction already checks gs.canExecuteAnyAction(player), catches exceptions, and returns a valid PlayerAction.
- The generated body should return a PlayerAction.

Allowed starting point:
- PlayerAction pa = new PlayerAction();
- pa.fillWithNones(gs, player, 10);
- return pa;

Rules for generated code:
- Output only Java statements for the body of chooseAction.
- Do not output package declarations, imports, classes, constructors, fields, or helper method definitions.
- Do not use custom imports, Optional, StrategyTable, streams, lambdas, files, network, subprocesses, or runtime LLM code.
- Do not call invented action APIs.
- Return only the chooseAction body. No markdown fences.

Current known-good scaffold:
```java
{template}
```
"""


def render_blank_strategy_agent(class_name: str) -> str:
    return render_strategy_agent(class_name, PASSIVE_AI_STRATEGY_BODY)


def render_strategy_agent(class_name: str, strategy_body: str) -> str:
    return RANDOM_AI_AGENT_TEMPLATE.format(class_name=class_name, strategy_body=strategy_body)


def microrts_blank_strategy_prompt() -> str:
    return MICRORTS_BLANK_STRATEGY_PROMPT.format(
        template=render_blank_strategy_agent("CLASS_NAME")
    )


def get_seed_prompt_template(name: str) -> str:
    if name == "microrts_blank_strategy_agent":
        return microrts_blank_strategy_prompt()
    raise ValueError(f"Unknown seed_prompt_template: {name}")
