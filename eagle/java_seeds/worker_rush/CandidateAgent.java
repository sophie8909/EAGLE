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

/** Deterministic generation-zero Worker Rush seed for mixed-policy populations. */
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
            AgentContext context = new AgentContext(
                    player,
                    gs,
                    new ArrayList<>(gs.getUnits()));
            decide(context);
            return translateActions(player, gs);
        } finally {
            activePlayer = -1;
            activeGameState = null;
        }
    }

    // EAGLE_AGENT_STRATEGY_START
    // Canonical Worker Rush: continuously train Workers, retain one harvester,
    // and send every additional Worker toward the nearest enemy Base or unit.
    private void decide(AgentContext context) {
        trainWorkers(context);

        List<Unit> workers = new ArrayList<>();
        for (Unit unit : context.units) {
            if (unit.getPlayer() != context.player || !isIdleAlly(unit, context)) {
                continue;
            }
            if (unit.getType() == workerType) {
                workers.add(unit);
            } else if (unit.getType().canAttack) {
                attackNearestEnemy(unit, context);
            }
        }
        runWorkerRush(workers, context);
    }

    private void trainWorkers(AgentContext context) {
        int resources = context.gs.getPlayer(context.player).getResources();
        for (Unit unit : context.units) {
            if (unit.getPlayer() == context.player
                    && unit.getType() == baseType
                    && isIdleAlly(unit, context)
                    && resources >= workerType.cost) {
                if (commandTrain(unit, workerType)) {
                    resources -= workerType.cost;
                }
            }
        }
    }

    private void runWorkerRush(List<Unit> workers, AgentContext context) {
        if (workers.isEmpty()) {
            return;
        }

        Unit base = ownBase(context);
        if (base == null) {
            Unit builder = workers.remove(0);
            int[] buildCell = adjacentBuildCell(builder, context);
            if (buildCell != null
                    && context.gs.getPlayer(context.player).getResources() >= baseType.cost) {
                commandBuild(builder, baseType, buildCell[0], buildCell[1]);
            }
        }

        if (!workers.isEmpty()) {
            Unit harvester = workers.remove(0);
            Unit resource = nearestResource(harvester, context);
            Unit friendlyBase = nearestFriendlyBase(harvester, context);
            if (resource != null && friendlyBase != null) {
                commandHarvest(harvester, resource, friendlyBase);
            } else {
                attackNearestEnemy(harvester, context);
            }
        }

        for (Unit worker : workers) {
            attackNearestEnemy(worker, context);
        }
    }

    private void attackNearestEnemy(Unit unit, AgentContext context) {
        Unit target = nearestEnemyBase(unit, context);
        if (target == null) {
            target = nearestEnemy(unit, context);
        }
        if (target != null) {
            commandAttack(unit, target);
        } else {
            commandIdle(unit);
        }
    }

    private Unit nearestEnemyBase(Unit source, AgentContext context) {
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit unit : context.units) {
            if (unit.getPlayer() < 0
                    || unit.getPlayer() == context.player
                    || unit.getType() != baseType) {
                continue;
            }
            int distance = manhattan(source, unit);
            if (distance < bestDistance) {
                best = unit;
                bestDistance = distance;
            }
        }
        return best;
    }

    private Unit nearestFriendlyBase(Unit source, AgentContext context) {
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit unit : context.units) {
            if (unit.getPlayer() != context.player || unit.getType() != baseType) {
                continue;
            }
            int distance = manhattan(source, unit);
            if (distance < bestDistance) {
                best = unit;
                bestDistance = distance;
            }
        }
        return best;
    }

    private int[] adjacentBuildCell(Unit worker, AgentContext context) {
        int[][] directions = {{1, 0}, {0, 1}, {-1, 0}, {0, -1}};
        for (int[] direction : directions) {
            int x = worker.getX() + direction[0];
            int y = worker.getY() + direction[1];
            if (isFreeCell(context, x, y)) {
                return new int[] {x, y};
            }
        }
        return null;
    }

    private int manhattan(Unit first, Unit second) {
        return Math.abs(first.getX() - second.getX())
                + Math.abs(first.getY() - second.getY());
    }
    // EAGLE_AGENT_STRATEGY_END

    // EAGLE_ACTION_HELPERS_START
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
                || target.getPlayer() < 0 || !attacker.getType().canAttack
                || target.getPlayer() == activePlayer) {
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

    private Unit nearestEnemy(Unit source, AgentContext context) {
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit unit : context.units) {
            if (unit.getPlayer() < 0 || unit.getPlayer() == context.player) {
                continue;
            }
            int distance = manhattan(source, unit);
            if (distance < bestDistance) {
                best = unit;
                bestDistance = distance;
            }
        }
        return best;
    }

    private Unit nearestResource(Unit source, AgentContext context) {
        Unit best = null;
        int bestDistance = Integer.MAX_VALUE;
        for (Unit unit : context.units) {
            if (unit.getPlayer() != -1 || unit.getType() != resourceType) {
                continue;
            }
            int distance = manhattan(source, unit);
            if (distance < bestDistance) {
                best = unit;
                bestDistance = distance;
            }
        }
        return best;
    }

    private boolean isFreeCell(AgentContext context, int x, int y) {
        if (context == null || context.gs == null) {
            return false;
        }
        PhysicalGameState physical = context.gs.getPhysicalGameState();
        return x >= 0 && y >= 0 && x < physical.getWidth() && y < physical.getHeight()
                && context.gs.free(x, y);
    }

    private Unit ownBase(AgentContext context) {
        for (Unit unit : context.units) {
            if (unit.getPlayer() == context.player && unit.getType() == baseType) {
                return unit;
            }
        }
        return null;
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification(
                "PathFinding",
                PathFinding.class,
                new AStarPathFinding()));
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
}
