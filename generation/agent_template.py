"""Built-in prompt and Java skeleton for MicroRTS generated agents."""

from __future__ import annotations


BLANK_STRATEGY_AGENT_TEMPLATE = """package ai.generated;

import ai.abstraction.AbstractionLayerAI;
import ai.abstraction.pathfinding.AStarPathFinding;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;

public class {class_name} extends AbstractionLayerAI {{
    protected UnitTypeTable utt;
    protected UnitType resourceType;
    protected UnitType workerType;
    protected UnitType lightType;
    protected UnitType heavyType;
    protected UnitType rangedType;
    protected UnitType baseType;
    protected UnitType barracksType;

    public {class_name}(UnitTypeTable aUtt) {{
        this(aUtt, new AStarPathFinding());
    }}

    public {class_name}(UnitTypeTable aUtt, PathFinding aPf) {{
        super(aPf);
        reset(aUtt);
    }}

    public void reset(UnitTypeTable aUtt) {{
        utt = aUtt;
        resourceType = utt.getUnitType("Resource");
        workerType = utt.getUnitType("Worker");
        lightType = utt.getUnitType("Light");
        heavyType = utt.getUnitType("Heavy");
        rangedType = utt.getUnitType("Ranged");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
    }}

    @Override
    public void reset() {{
        super.reset();
        if (utt != null) {{
            reset(utt);
        }}
    }}

    @Override
    public AI clone() {{
        return new {class_name}(utt, pf);
    }}

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {{
        if (gs.gameover()) {{
            return translateActions(player, gs);
        }}
        defineStrategy(player, gs);
        applyAutoDefense(player, gs);
        return translateActions(player, gs);
    }}

    private void defineStrategy(int player, GameState gs) {{
        // STRATEGY LOGIC GOES HERE.
        // Use the command helpers below. Leave units idle when no safe action is chosen.
    }}

    private boolean commandMove(Unit unit, int x, int y) {{
        if (unit == null || unit.getType() == baseType || unit.getType() == barracksType) {{
            return false;
        }}
        move(unit, x, y);
        return true;
    }}

    private boolean commandHarvest(Unit worker, Unit resource, Unit base) {{
        if (worker == null || resource == null || base == null) {{
            return false;
        }}
        if (worker.getType() != workerType || resource.getType() != resourceType || base.getType() != baseType) {{
            return false;
        }}
        harvest(worker, resource, base);
        return true;
    }}

    private boolean commandTrain(Unit producer, UnitType unitType) {{
        if (producer == null || unitType == null) {{
            return false;
        }}
        if (producer.getType() != baseType && producer.getType() != barracksType) {{
            return false;
        }}
        train(producer, unitType);
        return true;
    }}

    private boolean commandBuild(Unit worker, UnitType buildingType, int x, int y) {{
        if (worker == null || buildingType == null || worker.getType() != workerType) {{
            return false;
        }}
        build(worker, buildingType, x, y);
        return true;
    }}

    private boolean commandAttack(Unit attacker, Unit target) {{
        if (attacker == null || target == null || !attacker.getType().canAttack) {{
            return false;
        }}
        if (target.getPlayer() == attacker.getPlayer()) {{
            return false;
        }}
        attack(attacker, target);
        return true;
    }}

    private boolean commandIdle(Unit unit) {{
        if (unit == null) {{
            return false;
        }}
        idle(unit);
        return true;
    }}

    private boolean isIdleAlly(Unit unit, int player, GameState gs) {{
        return unit != null
                && unit.getPlayer() == player
                && gs.getUnitAction(unit) == null
                && getAbstractAction(unit) == null;
    }}

    private Unit nearestUnit(Unit source, List<Unit> units, int owner, UnitType type) {{
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit other : units) {{
            if (owner != Integer.MIN_VALUE && other.getPlayer() != owner) {{
                continue;
            }}
            if (type != null && other.getType() != type) {{
                continue;
            }}
            int distance = Math.abs(other.getX() - source.getX()) + Math.abs(other.getY() - source.getY());
            if (distance < bestDistance) {{
                best = other;
                bestDistance = distance;
            }}
        }}
        return best;
    }}

    private Unit nearestEnemy(Unit source, int player, PhysicalGameState pgs) {{
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit other : pgs.getUnits()) {{
            if (other.getPlayer() < 0 || other.getPlayer() == player) {{
                continue;
            }}
            int distance = Math.abs(other.getX() - source.getX()) + Math.abs(other.getY() - source.getY());
            if (distance < bestDistance) {{
                best = other;
                bestDistance = distance;
            }}
        }}
        return best;
    }}

    private Unit nearestResource(Unit source, PhysicalGameState pgs) {{
        return nearestUnit(source, pgs.getUnits(), -1, resourceType);
    }}

    private Unit ownBase(int player, PhysicalGameState pgs) {{
        for (Unit unit : pgs.getUnits()) {{
            if (unit.getPlayer() == player && unit.getType() == baseType) {{
                return unit;
            }}
        }}
        return null;
    }}

    private void applyAutoDefense(int player, GameState gs) {{
        PhysicalGameState pgs = gs.getPhysicalGameState();
        for (Unit ally : pgs.getUnits()) {{
            if (!isIdleAlly(ally, player, gs) || !ally.getType().canAttack) {{
                continue;
            }}
            Unit closestEnemy = nearestEnemy(ally, player, pgs);
            if (closestEnemy != null) {{
                int distance = Math.abs(closestEnemy.getX() - ally.getX()) + Math.abs(closestEnemy.getY() - ally.getY());
                if (distance <= 1) {{
                    commandAttack(ally, closestEnemy);
                }}
            }}
        }}
    }}

    @Override
    public List<ParameterSpecification> getParameters() {{
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }}
}}
"""


MICRORTS_BLANK_STRATEGY_PROMPT = """Generate one Java MicroRTS agent by filling only the blank strategy logic in the template below.

MicroRTS summary:
- The game is a small real-time strategy environment on a tile map.
- Players control Base, Barracks, Worker, Light, Heavy, and Ranged units.
- Neutral Resource units can be harvested by Workers and returned to a friendly Base.
- Buildings produce units. Bases train Workers. Barracks train Light, Heavy, or Ranged units.
- Combat units attack enemy units. Workers can harvest, build, move, and attack weakly.
- A generated agent must decide actions inside getAction and must not call any LLM, network, file, or external service at runtime.

Available high-level operations from AbstractionLayerAI:
- move(unit, x, y): move a non-building unit toward a map coordinate.
- harvest(worker, resource, base): make a Worker gather from a Resource and return to a Base.
- train(baseOrBarracks, unitType): train Worker from Base or combat units from Barracks.
- build(worker, buildingType, x, y): build Base or Barracks at a target coordinate.
- attack(attacker, enemy): attack an enemy unit.
- idle(unit): explicitly do nothing with a unit.

Rules for generated code:
- Use package ai.generated.
- The class name must be the exact requested class name.
- Keep the constructors and helper methods compilable.
- Fill defineStrategy with deterministic Java logic.
- Do not include HTTP, URL, Socket, Files, environment variables, subprocesses, or runtime LLM code.
- Return only Java source code.

Blank strategy template:
```java
{template}
```
"""


def render_blank_strategy_agent(class_name: str) -> str:
    return BLANK_STRATEGY_AGENT_TEMPLATE.format(class_name=class_name)


def microrts_blank_strategy_prompt() -> str:
    return MICRORTS_BLANK_STRATEGY_PROMPT.format(
        template=BLANK_STRATEGY_AGENT_TEMPLATE.format(class_name="CLASS_NAME")
    )


def get_seed_prompt_template(name: str) -> str:
    if name == "microrts_blank_strategy_agent":
        return microrts_blank_strategy_prompt()
    raise ValueError(f"Unknown seed_prompt_template: {name}")

