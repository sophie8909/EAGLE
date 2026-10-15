package ai.generated;

import ai.abstraction.AbstractionLayerAI;
import ai.abstraction.AbstractAction;
import ai.abstraction.pathfinding.AStarPathFinding;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.ResourceUsage;
import rts.UnitAction;
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
    private int activePlayer = -1;
    private GameState activeGameState;

    public CandidateAgent(UnitTypeTable utt) {
        this(utt, new AStarPathFinding());
    }

    public CandidateAgent(UnitTypeTable utt, AStarPathFinding pathFinding) {
        super(pathFinding);
        reset(utt);
    }

    public void reset(UnitTypeTable utt) {
        this.utt = utt;
        activePlayer = -1;
        activeGameState = null;
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
        return new CandidateAgent(utt, new AStarPathFinding());
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        activePlayer = player;
        activeGameState = gs;
        try {
            if (gs.gameover()) {
                return translateActions(player, gs);
            }
            AgentContext context = new AgentContext(player, gs, new ArrayList<>(gs.getUnits()));
            decide(context);
            applyAutoDefense(player, gs);
            return translateActions(player, gs);
        } finally {
            activePlayer = -1;
            activeGameState = null;
        }
    }

    // EAGLE_AGENT_STRATEGY_START
private ai.abstraction.WorkerRush dslReferenceAgent;
    private GameState dslReferenceGameState;
    private int dslReferenceLastTime = -1;

    private void decide(AgentContext context) {
        actions.clear();
        if (dslReferenceAgent == null
                || dslReferenceGameState != context.gs
                || context.gs.getTime() < dslReferenceLastTime) {
            dslReferenceAgent = new ai.abstraction.WorkerRush(utt);
            dslReferenceGameState = context.gs;
        }
        dslReferenceLastTime = context.gs.getTime();
        PlayerAction referenceAction;
        try {
            referenceAction = dslReferenceAgent.getAction(context.player, context.gs);
        } catch (Exception error) {
            throw new IllegalStateException("canonical WorkerRush failed", error);
        }
        for (util.Pair<Unit, rts.UnitAction> issued : referenceAction.getActions()) {
            if (!commandPlannedAction(issued.m_a, issued.m_b, context)) {
                throw new IllegalStateException(
                        "could not replay canonical WorkerRush action for unit "
                        + issued.m_a.getID());
            }
        }
    }
    // EAGLE_AGENT_STRATEGY_END

    // EAGLE_ACTION_HELPERS_START
    // Stable Agent operation API: strategy code should issue actions through these helpers.
    private boolean commandMove(Unit unit, int x, int y) {
        if (unit == null || unit.getPlayer() != activePlayer
                || unit.getType() == baseType || unit.getType() == barracksType
                || !isInsideActiveMap(x, y)) {
            return false;
        }
        move(unit, x, y);
        return true;
    }

    private boolean commandHarvest(Unit worker, Unit resource, Unit base) {
        if (worker == null || resource == null || base == null) {
            return false;
        }
        if (worker.getPlayer() != activePlayer || base.getPlayer() != activePlayer
                || resource.getPlayer() >= 0 || worker.getType() != workerType
                || resource.getType() != resourceType || base.getType() != baseType) {
            return false;
        }
        harvest(worker, resource, base);
        return true;
    }

    private boolean commandReturn(Unit worker, Unit base, AgentContext context) {
        UnitAction planned = prepareReturn(worker, base, context);
        return planned != null && commandReturn(worker, base, context, planned);
    }

    private boolean commandReturn(Unit worker, Unit base, AgentContext context, UnitAction planned) {
        UnitAction expected = prepareReturn(worker, base, context);
        if (expected == null || !expected.equals(planned)
                || !commandPlannedAction(worker, planned, context)) {
            return false;
        }
        actions.put(worker, new ReturnAction(worker, base, planned));
        return true;
    }

    private UnitAction prepareReturn(Unit worker, Unit base, AgentContext context) {
        if (context == null || context.gs != activeGameState || context.player != activePlayer
                || !isIdleAlly(worker, context) || base == null
                || worker.getType() != workerType || base.getType() != baseType
                || base.getPlayer() != context.player || worker.getResources() <= 0
                || !context.units.contains(base)) {
            return null;
        }
        int dx = base.getX() - worker.getX();
        int dy = base.getY() - worker.getY();
        UnitAction action;
        if (Math.abs(dx) + Math.abs(dy) == 1) {
            int direction = dx == 1 ? UnitAction.DIRECTION_RIGHT
                    : dx == -1 ? UnitAction.DIRECTION_LEFT
                    : dy == 1 ? UnitAction.DIRECTION_DOWN : UnitAction.DIRECTION_UP;
            action = new UnitAction(UnitAction.TYPE_RETURN, direction);
        } else {
            action = pf.findPathToAdjacentPosition(worker,
                    base.getX() + base.getY() * context.gs.getPhysicalGameState().getWidth(),
                    context.gs, context.reservations);
        }
        return action != null && context.gs.isUnitActionAllowed(worker, action)
                && context.reservations.consistentWith(
                        action.resourceUsage(worker, context.gs.getPhysicalGameState()), context.gs)
                ? action : null;
    }

    private boolean commandPlannedAction(Unit actor, UnitAction action, AgentContext context) {
        if (context == null || context.gs != activeGameState || context.player != activePlayer
                || action == null || !isIdleAlly(actor, context) || !context.units.contains(actor)
                || !actor.canExecuteAction(action, context.gs)
                || !context.gs.isUnitActionAllowed(actor, action)) {
            return false;
        }
        ResourceUsage usage = action.resourceUsage(actor, context.gs.getPhysicalGameState());
        if (!context.reservations.consistentWith(usage, context.gs)) {
            return false;
        }
        actions.put(actor, new PlannedUnitAction(actor, action));
        context.reservations.merge(usage);
        return true;
    }

    private boolean commandTrain(Unit producer, UnitType unitType) {
        if (producer == null || producer.getPlayer() != activePlayer || unitType == null) {
            return false;
        }
        boolean validBaseProduction = producer.getType() == baseType && unitType == workerType;
        boolean validBarracksProduction = producer.getType() == barracksType
                && (unitType == lightType || unitType == heavyType || unitType == rangedType);
        if (!validBaseProduction && !validBarracksProduction) {
            return false;
        }
        train(producer, unitType);
        return true;
    }

    private boolean commandBuild(Unit worker, UnitType buildingType, int x, int y) {
        if (worker == null || worker.getPlayer() != activePlayer || buildingType == null
                || worker.getType() != workerType
                || (buildingType != baseType && buildingType != barracksType)
                || !isInsideActiveMap(x, y)) {
            return false;
        }
        build(worker, buildingType, x, y);
        return true;
    }

    private boolean commandAttack(Unit attacker, Unit target) {
        if (attacker == null || target == null || attacker.getPlayer() != activePlayer
                || target.getPlayer() < 0 || !attacker.getType().canAttack) {
            return false;
        }
        if (target.getPlayer() == activePlayer) {
            return false;
        }
        attack(attacker, target);
        return true;
    }

    private boolean commandIdle(Unit unit) {
        if (unit == null || unit.getPlayer() != activePlayer) {
            return false;
        }
        idle(unit);
        return true;
    }

    private boolean isInsideActiveMap(int x, int y) {
        if (activeGameState == null) {
            return false;
        }
        PhysicalGameState physical = activeGameState.getPhysicalGameState();
        return x >= 0 && y >= 0 && x < physical.getWidth() && y < physical.getHeight();
    }

    // EAGLE_ACTION_HELPERS_END

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

    private boolean isFreeCell(AgentContext context, int x, int y) {
        if (context == null || context.gs == null) {
            return false;
        }
        PhysicalGameState physical = context.gs.getPhysicalGameState();
        return x >= 0 && y >= 0 && x < physical.getWidth() && y < physical.getHeight()
                && context.gs.free(x, y);
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
        final ResourceUsage reservations;

        AgentContext(int player, GameState gs, List<Unit> units) {
            this.player = player;
            this.gs = gs;
            this.units = units;
            this.reservations = gs.getResourceUsage().clone();
        }
    }

    // One-cycle primitives retain the compiler's exact placement and reservations.
    private static class PlannedUnitAction extends AbstractAction {
        private final UnitAction action;
        private boolean executed;

        PlannedUnitAction(Unit actor, UnitAction action) {
            super(actor);
            this.action = action;
        }

        @Override
        public boolean completed(GameState gs) {
            return executed;
        }

        @Override
        public UnitAction execute(GameState gs, ResourceUsage usage) {
            executed = true;
            return action;
        }

        @Override
        public void toxml(util.XMLWriter writer) {
            writer.tagWithAttributes("PlannedUnitAction", "unitID=\"" + getUnit().getID() + "\"");
            writer.tag("/PlannedUnitAction");
        }
    }

    private static final class ReturnAction extends PlannedUnitAction {
        private final Unit base;

        ReturnAction(Unit worker, Unit base, UnitAction action) {
            super(worker, action);
            this.base = base;
        }

        @Override
        public void toxml(util.XMLWriter writer) {
            writer.tagWithAttributes("Return", "unitID=\"" + getUnit().getID()
                    + "\" base=\"" + base.getID() + "\"");
            writer.tag("/Return");
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
