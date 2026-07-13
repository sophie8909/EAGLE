package ai.generated;

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

public final class CandidateAgent extends AbstractionLayerAI {
    private UnitTypeTable utt;
    private UnitType resourceType;
    private UnitType workerType;
    private UnitType lightType;
    private UnitType heavyType;
    private UnitType rangedType;
    private UnitType baseType;
    private UnitType barracksType;

    public CandidateAgent(UnitTypeTable utt) {
        this(utt, new AStarPathFinding());
    }

    public CandidateAgent(UnitTypeTable utt, PathFinding pathFinding) {
        super(pathFinding);
        reset(utt);
    }

    public void reset(UnitTypeTable utt) {
        this.utt = utt;
        resourceType = utt.getUnitType("Resource");
        workerType = utt.getUnitType("Worker");
        lightType = utt.getUnitType("Light");
        heavyType = utt.getUnitType("Heavy");
        rangedType = utt.getUnitType("Ranged");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
    }

    @Override
    public void reset() {
        super.reset();
        if (utt != null) {
            reset(utt);
        }
    }

    @Override
    public AI clone() {
        return new CandidateAgent(utt, pf);
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        if (gs.gameover()) {
            return translateActions(player, gs);
        }
        AgentContext context = new AgentContext(player, gs, new ArrayList<>(gs.getUnits()));
        decide(context);
        applyAutoDefense(player, gs);
        return translateActions(player, gs);
    }

    private void decide(AgentContext context) {
        /* EAGLE_BODY:controller */
    }

    private void economy(AgentContext context) {
        /* EAGLE_BODY:economy */
    }

    private void combat(AgentContext context) {
        /* EAGLE_BODY:combat */
    }

    private void expansion(AgentContext context) {
        /* EAGLE_BODY:expansion */
    }

    private Unit selectTarget(AgentContext context, Unit actor, List<Unit> candidates) {
        /* EAGLE_BODY:target_selection */
    }

    private PathChoice findPath(AgentContext context, Unit unit, int targetX, int targetY) {
        /* EAGLE_BODY:path_selection */
    }

    private boolean commandMove(Unit unit, int x, int y) {
        if (unit == null || unit.getType() == baseType || unit.getType() == barracksType) {
            return false;
        }
        move(unit, x, y);
        return true;
    }

    private boolean commandHarvest(Unit worker, Unit resource, Unit base) {
        if (worker == null || resource == null || base == null) {
            return false;
        }
        if (worker.getType() != workerType || resource.getType() != resourceType || base.getType() != baseType) {
            return false;
        }
        harvest(worker, resource, base);
        return true;
    }

    private boolean commandTrain(Unit producer, UnitType unitType) {
        if (producer == null || unitType == null) {
            return false;
        }
        if (producer.getType() != baseType && producer.getType() != barracksType) {
            return false;
        }
        train(producer, unitType);
        return true;
    }

    private boolean commandBuild(Unit worker, UnitType buildingType, int x, int y) {
        if (worker == null || buildingType == null || worker.getType() != workerType) {
            return false;
        }
        build(worker, buildingType, x, y);
        return true;
    }

    private boolean commandAttack(Unit attacker, Unit target) {
        if (attacker == null || target == null || !attacker.getType().canAttack) {
            return false;
        }
        if (target.getPlayer() == attacker.getPlayer()) {
            return false;
        }
        attack(attacker, target);
        return true;
    }

    private boolean commandIdle(Unit unit) {
        if (unit == null) {
            return false;
        }
        idle(unit);
        return true;
    }

    private boolean isIdleAlly(Unit unit, AgentContext context) {
        return unit != null
                && unit.getPlayer() == context.player
                && context.gs.getUnitAction(unit) == null
                && getAbstractAction(unit) == null;
    }

    private Unit nearestUnit(Unit source, List<Unit> units, int owner, UnitType type) {
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit other : units) {
            if (owner != Integer.MIN_VALUE && other.getPlayer() != owner) {
                continue;
            }
            if (type != null && other.getType() != type) {
                continue;
            }
            int distance = Math.abs(other.getX() - source.getX()) + Math.abs(other.getY() - source.getY());
            if (distance < bestDistance) {
                best = other;
                bestDistance = distance;
            }
        }
        return best;
    }

    private Unit nearestEnemy(Unit source, AgentContext context) {
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit other : context.units) {
            if (other.getPlayer() < 0 || other.getPlayer() == context.player) {
                continue;
            }
            int distance = Math.abs(other.getX() - source.getX()) + Math.abs(other.getY() - source.getY());
            if (distance < bestDistance) {
                best = other;
                bestDistance = distance;
            }
        }
        return best;
    }

    private Unit nearestResource(Unit source, AgentContext context) {
        return nearestUnit(source, context.units, -1, resourceType);
    }

    private Unit ownBase(AgentContext context) {
        for (Unit unit : context.units) {
            if (unit.getPlayer() == context.player && unit.getType() == baseType) {
                return unit;
            }
        }
        return null;
    }

    private void applyAutoDefense(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        AgentContext context = new AgentContext(player, gs, new ArrayList<>(pgs.getUnits()));
        for (Unit ally : context.units) {
            if (!isIdleAlly(ally, context) || !ally.getType().canAttack) {
                continue;
            }
            Unit enemy = nearestEnemy(ally, context);
            if (enemy == null) {
                continue;
            }
            int distance = Math.abs(enemy.getX() - ally.getX()) + Math.abs(enemy.getY() - ally.getY());
            if (distance <= ally.getType().attackRange) {
                commandAttack(ally, enemy);
            }
        }
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }

    private static final class AgentContext {
        final int player;
        final GameState gs;
        final List<Unit> units;

        AgentContext(int player, GameState gs, List<Unit> units) {
            this.player = player;
            this.gs = gs;
            this.units = units;
        }
    }

    private static final class PathChoice {
        final int x;
        final int y;

        PathChoice(int x, int y) {
            this.x = x;
            this.y = y;
        }
    }
}