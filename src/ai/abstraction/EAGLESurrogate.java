package ai.abstraction;

import ai.abstraction.pathfinding.AStarPathFinding;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.LinkedList;
import java.util.List;
import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.PlayerAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;

/**
 * Deterministic surrogate agent whose behavior is driven by a generated spec.
 * The Python surrogate pipeline rewrites only the injected spec/prompt blocks,
 * while the execution logic below stays stable.
 */
public class EAGLESurrogate extends AbstractionLayerAI {

    protected UnitTypeTable utt;
    UnitType workerType;
    UnitType lightType;
    UnitType heavyType;
    UnitType rangedType;
    UnitType baseType;
    UnitType barracksType;

    // SURROGATE_SPEC_START
    private static final boolean INJECTED_STRATEGY_ENABLED = false;
    private static final int WORKER_TARGET_BEFORE_BARRACKS = 0;
    private static final int WORKER_TARGET_AFTER_BARRACKS = 0;
    private static final int HARVESTER_TARGET = 0;
    private static final int DESIRED_BARRACKS = 0;
    private static final boolean WORKER_HARASS_ENABLED = false;
    private static final boolean ATTACK_WORKERS_FIRST = false;
    private static final boolean ATTACK_STRUCTURES_FIRST = false;
    private static final boolean PROTECT_BARRACKS = false;
    private static final int MIN_LIGHTS = 0;
    private static final int MIN_RANGED = 0;
    private static final int MIN_HEAVIES = 0;
    private static final String[] PRODUCTION_PRIORITY = {
    };
    // SURROGATE_SPEC_END

    // SURROGATE_PROMPT_START
    private static final String[] EMBEDDED_PROMPT_LINES = {
    };
    // SURROGATE_PROMPT_END

    public EAGLESurrogate(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());
    }

    public EAGLESurrogate(UnitTypeTable a_utt, PathFinding a_pf) {
        super(a_pf);
        reset(a_utt);
    }

    public void reset() {
        super.reset();
    }

    public void reset(UnitTypeTable a_utt) {
        utt = a_utt;
        workerType = utt.getUnitType("Worker");
        lightType = utt.getUnitType("Light");
        heavyType = utt.getUnitType("Heavy");
        rangedType = utt.getUnitType("Ranged");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
    }

    @Override
    public AI clone() {
        return new EAGLESurrogate(utt, pf);
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }

    protected StrategySpec buildStrategySpec() {
        StrategySpec spec = new StrategySpec();
        spec.enabled = INJECTED_STRATEGY_ENABLED;
        spec.workerTargetBeforeBarracks = WORKER_TARGET_BEFORE_BARRACKS;
        spec.workerTargetAfterBarracks = WORKER_TARGET_AFTER_BARRACKS;
        spec.harvesterTarget = HARVESTER_TARGET;
        spec.desiredBarracks = DESIRED_BARRACKS;
        spec.workerHarassEnabled = WORKER_HARASS_ENABLED;
        spec.attackWorkersFirst = ATTACK_WORKERS_FIRST;
        spec.attackStructuresFirst = ATTACK_STRUCTURES_FIRST;
        spec.protectBarracks = PROTECT_BARRACKS;
        spec.minLights = MIN_LIGHTS;
        spec.minRanged = MIN_RANGED;
        spec.minHeavies = MIN_HEAVIES;
        spec.productionPriority = resolveProductionPriority(PRODUCTION_PRIORITY);
        return spec;
    }

    protected boolean hasInjectedStrategy() {
        return INJECTED_STRATEGY_ENABLED;
    }

    protected void logStateSnapshot(int player, GameState gs) {
        Player p0 = gs.getPlayer(0);
        Player p1 = gs.getPlayer(1);
        int currentTime = gs.getTime();

        System.out.println("gs.gameover() = " + gs.gameover());
        System.out.println("Running getAction for Player: " + player);
        System.out.println(" current time " + currentTime + " p0 " + p0 + " p1 " + p1);
        System.out.printf(
                "T: %d, P0: %d (%s), P1: %d (%s)%n",
                currentTime,
                p0.getID(), p0.getResources(),
                p1.getID(), p1.getResources()
        );
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        if (!hasInjectedStrategy()) {
            logStateSnapshot(player, gs);
            return translateActions(player, gs);
        }

        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);
        StrategySpec spec = buildStrategySpec();

        for (Unit u : pgs.getUnits()) {
            if (u.getType() == baseType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                baseBehavior(u, p, pgs, spec);
            }
        }

        for (Unit u : pgs.getUnits()) {
            if (u.getType() == barracksType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                barracksBehavior(u, p, pgs, spec);
            }
        }

        List<Unit> workers = new LinkedList<>();
        for (Unit u : pgs.getUnits()) {
            if (u.getType() == workerType && u.getPlayer() == player) {
                workers.add(u);
            }
        }
        workersBehavior(workers, p, gs, spec);

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player && u.getType().canAttack && !u.getType().canHarvest && gs.getActionAssignment(u) == null) {
                combatBehavior(u, p, gs, spec);
            }
        }

        logStateSnapshot(player, gs);
        return translateActions(player, gs);
    }

    protected void baseBehavior(Unit base, Player player, PhysicalGameState pgs, StrategySpec spec) {
        int workerCount = countUnits(pgs, player.getID(), workerType);
        int barracksCount = countUnits(pgs, player.getID(), barracksType);
        int targetWorkers = barracksCount > 0 ? spec.workerTargetAfterBarracks : spec.workerTargetBeforeBarracks;
        if (workerCount < targetWorkers && player.getResources() >= workerType.cost) {
            train(base, workerType);
        }
    }

    protected void barracksBehavior(Unit barracks, Player player, PhysicalGameState pgs, StrategySpec spec) {
        UnitType nextType = chooseProductionType(player, pgs, spec);
        if (nextType != null && player.getResources() >= nextType.cost) {
            train(barracks, nextType);
        }
    }

    protected void workersBehavior(List<Unit> workers, Player player, GameState gs, StrategySpec spec) {
        if (workers.isEmpty()) {
            return;
        }

        PhysicalGameState pgs = gs.getPhysicalGameState();
        int baseCount = countUnits(pgs, player.getID(), baseType);
        int barracksCount = countUnits(pgs, player.getID(), barracksType);
        int resourcesUsed = 0;
        List<Unit> freeWorkers = new LinkedList<>(workers);
        List<Integer> reservedPositions = new LinkedList<>();

        if (baseCount == 0 && !freeWorkers.isEmpty() && player.getResources() >= baseType.cost) {
            Unit builder = freeWorkers.remove(0);
            buildIfNotAlreadyBuilding(builder, baseType, builder.getX(), builder.getY(), reservedPositions, player, pgs);
            resourcesUsed += baseType.cost;
        }

        while (barracksCount < spec.desiredBarracks
                && !freeWorkers.isEmpty()
                && player.getResources() >= barracksType.cost + resourcesUsed) {
            Unit builder = freeWorkers.remove(0);
            buildIfNotAlreadyBuilding(builder, barracksType, builder.getX(), builder.getY(), reservedPositions, player, pgs);
            resourcesUsed += barracksType.cost;
            barracksCount++;
        }

        int desiredHarvesters = Math.min(freeWorkers.size(), Math.max(1, spec.harvesterTarget));
        List<Unit> militaryWorkers = new LinkedList<>();
        for (Unit worker : freeWorkers) {
            if (desiredHarvesters > 0 && tryHarvest(worker, player, pgs)) {
                desiredHarvesters--;
            } else {
                militaryWorkers.add(worker);
            }
        }

        for (Unit worker : militaryWorkers) {
            if (spec.workerHarassEnabled) {
                combatBehavior(worker, player, gs, spec);
            }
        }
    }

    protected boolean tryHarvest(Unit worker, Player player, PhysicalGameState pgs) {
        Unit closestBase = nearestUnit(worker, pgs, player.getID(), baseType, true);
        Unit closestResource = nearestResource(worker, pgs);
        if (closestBase == null || closestResource == null) {
            return false;
        }

        if (worker.getResources() > 0) {
            AbstractAction aa = getAbstractAction(worker);
            if (!(aa instanceof Harvest) || ((Harvest) aa).base != closestBase) {
                harvest(worker, null, closestBase);
            }
            return true;
        }

        AbstractAction aa = getAbstractAction(worker);
        if (!(aa instanceof Harvest)
                || ((Harvest) aa).target != closestResource
                || ((Harvest) aa).base != closestBase) {
            harvest(worker, closestResource, closestBase);
        }
        return true;
    }

    protected void combatBehavior(Unit attacker, Player player, GameState gs, StrategySpec spec) {
        Unit target = selectAttackTarget(attacker, player, gs.getPhysicalGameState(), spec);
        if (target != null) {
            attack(attacker, target);
        }
    }

    protected Unit selectAttackTarget(Unit attacker, Player player, PhysicalGameState pgs, StrategySpec spec) {
        Unit best = null;
        int bestScore = Integer.MIN_VALUE;

        for (Unit candidate : pgs.getUnits()) {
            if (candidate.getPlayer() < 0 || candidate.getPlayer() == player.getID()) {
                continue;
            }

            int distance = Math.abs(candidate.getX() - attacker.getX()) + Math.abs(candidate.getY() - attacker.getY());
            int score = -distance;

            if (spec.attackWorkersFirst && candidate.getType() == workerType) {
                score += 30;
            }
            if (spec.attackStructuresFirst && (candidate.getType() == baseType || candidate.getType() == barracksType)) {
                score += 25;
            }
            if (spec.protectBarracks && candidate.getType().canAttack && !candidate.getType().canHarvest) {
                score += 8;
            }
            if (candidate.getType() == baseType) {
                score += 5;
            }
            if (candidate.getType() == barracksType) {
                score += 7;
            }

            if (best == null || score > bestScore) {
                best = candidate;
                bestScore = score;
            }
        }

        return best;
    }

    protected UnitType chooseProductionType(Player player, PhysicalGameState pgs, StrategySpec spec) {
        for (UnitType candidate : spec.productionPriority) {
            if (candidate == null) {
                continue;
            }
            int existing = countUnits(pgs, player.getID(), candidate);
            int minimum = spec.minimumUnitCount(candidate);
            if (existing < minimum && player.getResources() >= candidate.cost) {
                return candidate;
            }
        }

        for (UnitType candidate : spec.productionPriority) {
            if (candidate != null && player.getResources() >= candidate.cost) {
                return candidate;
            }
        }
        return null;
    }

    protected UnitType[] resolveProductionPriority(String[] names) {
        List<UnitType> resolved = new ArrayList<>();
        if (names != null) {
            for (String name : names) {
                UnitType unitType = resolveUnitTypeName(name);
                if (unitType != null && !resolved.contains(unitType)) {
                    resolved.add(unitType);
                }
            }
        }
        if (resolved.isEmpty()) {
            if (lightType != null) resolved.add(lightType);
            if (rangedType != null) resolved.add(rangedType);
            if (heavyType != null) resolved.add(heavyType);
        }
        return resolved.toArray(new UnitType[0]);
    }

    protected UnitType resolveUnitTypeName(String name) {
        if (name == null) {
            return null;
        }
        String normalized = name.trim().toLowerCase();
        if (normalized.equals("light")) {
            return lightType;
        }
        if (normalized.equals("ranged")) {
            return rangedType;
        }
        if (normalized.equals("heavy")) {
            return heavyType;
        }
        return null;
    }

    protected int countUnits(PhysicalGameState pgs, int playerId, UnitType type) {
        int count = 0;
        for (Unit unit : pgs.getUnits()) {
            if (unit.getPlayer() == playerId && unit.getType() == type) {
                count++;
            }
        }
        return count;
    }

    protected Unit nearestUnit(Unit origin, PhysicalGameState pgs, int playerId, UnitType type, boolean samePlayerOnly) {
        Unit closest = null;
        int closestDistance = Integer.MAX_VALUE;
        for (Unit unit : pgs.getUnits()) {
            if (unit.getType() != type) {
                continue;
            }
            if (samePlayerOnly && unit.getPlayer() != playerId) {
                continue;
            }
            int distance = Math.abs(unit.getX() - origin.getX()) + Math.abs(unit.getY() - origin.getY());
            if (closest == null || distance < closestDistance) {
                closest = unit;
                closestDistance = distance;
            }
        }
        return closest;
    }

    protected Unit nearestResource(Unit origin, PhysicalGameState pgs) {
        Unit closest = null;
        int closestDistance = Integer.MAX_VALUE;
        for (Unit unit : pgs.getUnits()) {
            if (!unit.getType().isResource) {
                continue;
            }
            int distance = Math.abs(unit.getX() - origin.getX()) + Math.abs(unit.getY() - origin.getY());
            if (closest == null || distance < closestDistance) {
                closest = unit;
                closestDistance = distance;
            }
        }
        return closest;
    }

    protected class StrategySpec {
        boolean enabled = false;
        int workerTargetBeforeBarracks = 0;
        int workerTargetAfterBarracks = 0;
        int harvesterTarget = 0;
        int desiredBarracks = 0;
        boolean workerHarassEnabled = false;
        boolean attackWorkersFirst = false;
        boolean attackStructuresFirst = false;
        boolean protectBarracks = false;
        UnitType[] productionPriority = new UnitType[0];
        int minLights = 0;
        int minRanged = 0;
        int minHeavies = 0;

        int minimumUnitCount(UnitType type) {
            if (type == lightType) {
                return minLights;
            }
            if (type == rangedType) {
                return minRanged;
            }
            if (type == heavyType) {
                return minHeavies;
            }
            return 0;
        }
    }
}
