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
    private void decide(AgentContext context) {
        actions.clear();
        java.util.List<Unit> actors = new java.util.ArrayList<>(context.units);
        actors.sort((a, b) -> Long.compare(a.getID(), b.getID()));
        for (Unit actor : actors) {
            if (!isIdleAlly(actor, context)) continue;
            if (dslDecideActor(context, actor)) continue;
            commandPlannedAction(actor, new rts.UnitAction(rts.UnitAction.TYPE_NONE, 10), context);
        }
    }

    private boolean dslDecideActor(AgentContext context, Unit actor) {
        if (actor.getType() == baseType && true) {
            DslPlan plan = dslRule0(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == workerType && ((dslActorRank(context, actor) < 2) && (actor.getResources() > 0))) {
            DslPlan plan = dslRule1(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == workerType && (dslActorRank(context, actor) < 2)) {
            DslPlan plan = dslRule2(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == workerType && (context.gs.getTime() >= 5)) {
            DslPlan plan = dslRule3(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == barracksType && (context.gs.getPlayer(context.player).getResources() >= 2)) {
            DslPlan plan = dslRule4(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == lightType && (dslCount(context, actor, 1, new UnitType[]{workerType}, 5) > 0)) {
            DslPlan plan = dslRule5(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == heavyType && (dslDistance(context, actor, 1, new UnitType[]{baseType}) < 6)) {
            DslPlan plan = dslRule6(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == rangedType && (false || !((actor.getHitPoints() == 0)))) {
            DslPlan plan = dslRule7(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == workerType && true) {
            DslPlan plan = dslRule8(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        if (actor.getType() == workerType && true) {
            DslPlan plan = dslRule9(context, actor);
            if (plan != null && dslIssue(context, actor, plan)) return true;
        }
        return false;
    }

    private DslPlan dslRule0(AgentContext context, Unit actor) {
        return dslSelectCell(context, actor, 7, workerType, 0);
    }

    private DslPlan dslRule1(AgentContext context, Unit actor) {
        return dslSelectEntity(context, actor, 2, 0, new UnitType[]{baseType}, 0);
    }

    private DslPlan dslRule2(AgentContext context, Unit actor) {
        return dslSelectEntity(context, actor, 1, 2, new UnitType[]{resourceType}, 0);
    }

    private DslPlan dslRule3(AgentContext context, Unit actor) {
        return dslSelectEntity(context, actor, 4, 1, new UnitType[]{baseType, barracksType, workerType, lightType, heavyType, rangedType}, 2);
    }

    private DslPlan dslRule4(AgentContext context, Unit actor) {
        return dslChoose(context, actor, new DslPlan[]{dslSelectCell(context, actor, 7, lightType, 1), dslSelectCell(context, actor, 7, rangedType, 0)});
    }

    private DslPlan dslRule5(AgentContext context, Unit actor) {
        return dslSelectEntity(context, actor, 3, 1, new UnitType[]{workerType}, 3);
    }

    private DslPlan dslRule6(AgentContext context, Unit actor) {
        return dslSelectEntity(context, actor, 5, 1, new UnitType[]{baseType}, 1);
    }

    private DslPlan dslRule7(AgentContext context, Unit actor) {
        return dslChoose(context, actor, new DslPlan[]{dslSelectEntity(context, actor, 3, 1, new UnitType[]{workerType}, 5), dslSelectEntity(context, actor, 4, 1, new UnitType[]{baseType}, 4), dslSelectCell(context, actor, 5, null, 1), dslIdlePlan()});
    }

    private DslPlan dslRule8(AgentContext context, Unit actor) {
        return dslSelectCell(context, actor, 6, barracksType, 0);
    }

    private DslPlan dslRule9(AgentContext context, Unit actor) {
        return dslIdlePlan();
    }

    private static final class DslPlan {
        final int kind;
        final rts.UnitAction action;
        final Unit target;
        DslPlan(int kind, rts.UnitAction action, Unit target) {
            this.kind = kind;
            this.action = action;
            this.target = target;
        }
    }

    private DslPlan dslIdlePlan() {
        return new DslPlan(0, null, null);
    }

    private long dslHash(AgentContext context, Unit actor) {
        return ((long) context.gs.getTime()) * 31L
                + ((long) context.player) * 17L + actor.getID() * 13L;
    }

    private int dslActorRank(AgentContext context, Unit actor) {
        int rank = 0;
        for (Unit other : context.units) {
            if (other.getPlayer() == context.player && other.getType() == actor.getType()
                    && other.getID() < actor.getID()) rank++;
        }
        return rank;
    }

    private boolean dslMatches(Unit unit, int owner, UnitType[] types, int player) {
        boolean ownership = owner == 0 ? unit.getPlayer() == player
                : owner == 1 ? unit.getPlayer() >= 0 && unit.getPlayer() != player
                : unit.getPlayer() < 0;
        if (!ownership) return false;
        for (UnitType type : types) if (unit.getType() == type) return true;
        return false;
    }

    private int dslManhattan(Unit a, Unit b) {
        return Math.abs(a.getX() - b.getX()) + Math.abs(a.getY() - b.getY());
    }

    private int dslCount(AgentContext context, Unit actor, int owner, UnitType[] types, double radius) {
        int count = 0;
        for (Unit other : context.units) {
            if (dslMatches(other, owner, types, context.player)
                    && (radius < 0 || dslManhattan(actor, other) <= radius)) count++;
        }
        return count;
    }

    private double dslDistance(AgentContext context, Unit actor, int owner, UnitType[] types) {
        double best = Double.POSITIVE_INFINITY;
        for (Unit other : context.units) {
            if (dslMatches(other, owner, types, context.player))
                best = Math.min(best, dslManhattan(actor, other));
        }
        return best;
    }

    private int dslPosition(AgentContext context, int x, int y) {
        return x + y * context.gs.getPhysicalGameState().getWidth();
    }

    private boolean dslLegal(AgentContext context, Unit actor, DslPlan plan) {
        if (plan == null) return false;
        if (plan.kind == 0) return true;
        if (!actor.canExecuteAction(plan.action, context.gs)
                || !context.gs.isUnitActionAllowed(actor, plan.action)) return false;
        return context.reservations.consistentWith(
                plan.action.resourceUsage(actor, context.gs.getPhysicalGameState()), context.gs);
    }

    private DslPlan dslPrimitive(AgentContext context, Unit actor, int kind,
            rts.UnitAction action, Unit target) {
        if (action == null) return null;
        DslPlan plan = new DslPlan(kind, action, target);
        return dslLegal(context, actor, plan) ? plan : null;
    }

    private rts.UnitAction dslPath(AgentContext context, Unit actor, Unit target, int range) {
        int position = dslPosition(context, target.getX(), target.getY());
        return pf.findPathToPositionInRange(actor, position, range,
                context.gs, context.reservations);
    }

    private int dslDirection(Unit actor, Unit target) {
        int dx = target.getX() - actor.getX();
        int dy = target.getY() - actor.getY();
        if (dx == 0 && dy == -1) return rts.UnitAction.DIRECTION_UP;
        if (dx == 1 && dy == 0) return rts.UnitAction.DIRECTION_RIGHT;
        if (dx == 0 && dy == 1) return rts.UnitAction.DIRECTION_DOWN;
        if (dx == -1 && dy == 0) return rts.UnitAction.DIRECTION_LEFT;
        return -1;
    }

    private DslPlan dslPlanEntity(AgentContext context, Unit actor, int kind, Unit target) {
        rts.UnitAction action;
        if (kind == 1 || kind == 2) {
            if (actor.getType() != workerType || (kind == 1 ? actor.getResources() != 0
                    : actor.getResources() <= 0)) return null;
            int direction = dslDirection(actor, target);
            if (direction >= 0) action = new rts.UnitAction(
                    kind == 1 ? rts.UnitAction.TYPE_HARVEST : rts.UnitAction.TYPE_RETURN, direction);
            else action = dslPath(context, actor, target, 1);
        } else if (kind == 3 || kind == 4) {
            if (!actor.getType().canAttack) return null;
            int dx = target.getX() - actor.getX();
            int dy = target.getY() - actor.getY();
            boolean inRange = ((long) dx * dx + (long) dy * dy)
                    <= ((long) actor.getType().attackRange * actor.getType().attackRange);
            if (inRange) action = new rts.UnitAction(rts.UnitAction.TYPE_ATTACK_LOCATION,
                    target.getX(), target.getY());
            else if (kind == 4) action = dslPath(context, actor, target, actor.getType().attackRange);
            else return null;
        } else if (kind == 5) {
            if (!actor.getType().canMove || target == actor || dslManhattan(actor, target) <= 1)
                return null;
            action = dslPath(context, actor, target, 1);
        } else return null;
        return dslPrimitive(context, actor, kind, action, target);
    }

    private DslPlan dslSelectEntity(AgentContext context, Unit actor,
            int kind, int owner, UnitType[] types, int selector) {
        java.util.List<DslPlan> legal = new java.util.ArrayList<>();
        for (Unit target : context.units) {
            if (!dslMatches(target, owner, types, context.player)) continue;
            DslPlan plan = dslPlanEntity(context, actor, kind, target);
            if (plan != null) legal.add(plan);
        }
        if (legal.isEmpty()) return null;
        legal.sort((a, b) -> {
            int value = 0;
            if (selector == 0 || selector == 1) {
                value = Integer.compare(dslManhattan(actor, a.target), dslManhattan(actor, b.target));
                if (selector == 1) value = -value;
            } else if (selector == 2 || selector == 3) {
                value = Integer.compare(a.target.getHitPoints(), b.target.getHitPoints());
                if (selector == 3) value = -value;
            }
            return value != 0 ? value : Long.compare(a.target.getID(), b.target.getID());
        });
        int index = selector == 5
                ? (int) Math.floorMod(dslHash(context, actor), (long) legal.size()) : 0;
        return legal.get(index);
    }

    private DslPlan dslSelectCell(AgentContext context, Unit actor,
            int kind, UnitType unitType, int selector) {
        java.util.List<DslPlan> legal = new java.util.ArrayList<>();
        for (int y = actor.getY() - 1; y <= actor.getY() + 1; y++) {
            for (int x = actor.getX() - 1; x <= actor.getX() + 1; x++) {
                if (Math.abs(x - actor.getX()) + Math.abs(y - actor.getY()) != 1
                        || !isFreeCell(context, x, y)) continue;
                int direction = x < actor.getX() ? rts.UnitAction.DIRECTION_LEFT
                        : x > actor.getX() ? rts.UnitAction.DIRECTION_RIGHT
                        : y < actor.getY() ? rts.UnitAction.DIRECTION_UP
                        : rts.UnitAction.DIRECTION_DOWN;
                rts.UnitAction action = kind == 5
                        ? new rts.UnitAction(rts.UnitAction.TYPE_MOVE, direction)
                        : new rts.UnitAction(rts.UnitAction.TYPE_PRODUCE, direction, unitType);
                DslPlan plan = dslPrimitive(context, actor, kind, action, null);
                if (plan != null) legal.add(plan);
            }
        }
        if (legal.isEmpty()) return null;
        int index = selector == 0 ? 0
                : (int) Math.floorMod(dslHash(context, actor), (long) legal.size());
        return legal.get(index);
    }

    private DslPlan dslChoose(AgentContext context, Unit actor, DslPlan[] options) {
        java.util.List<DslPlan> legal = new java.util.ArrayList<>();
        for (DslPlan option : options) if (dslLegal(context, actor, option)) legal.add(option);
        return legal.isEmpty() ? null
                : legal.get((int) Math.floorMod(dslHash(context, actor), (long) legal.size()));
    }

    private boolean dslIssue(AgentContext context, Unit actor, DslPlan plan) {
        if (!dslLegal(context, actor, plan)) return false;
        if (plan.kind == 0) return commandPlannedAction(actor, new rts.UnitAction(rts.UnitAction.TYPE_NONE, 10), context);
        if (plan.kind == 2) return commandReturn(actor, plan.target, context, plan.action);
        return commandPlannedAction(actor, plan.action, context);
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
