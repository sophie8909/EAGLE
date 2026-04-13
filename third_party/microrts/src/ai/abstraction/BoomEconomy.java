package ai.abstraction;

import ai.abstraction.pathfinding.AStarPathFinding;
import ai.core.AI;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.LinkedList;
import java.util.List;
import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.PlayerAction;
import rts.units.*;

/**
 * BoomEconomy: Economy-first strategy that maximizes workers before military.
 *
 * Strategy:
 * - Train many workers (4-5) for maximum resource income
 * - Build second base if resources allow
 * - Delay military production until economy is strong
 * - Transition to light/ranged units for efficient scaling
 *
 * Counter: Strong late-game economy, weak to early rushes
 */
public class BoomEconomy extends AbstractionLayerAI {

    protected UnitTypeTable utt;
    UnitType workerType;
    UnitType baseType;
    UnitType barracksType;
    UnitType lightType;

    // Configuration
    private static final int TARGET_WORKERS = 5;
    private static final int ECON_RESOURCE_THRESHOLD = 8;  // Start military when we have 8+ resources
    private static final int MAX_BASES = 2;

    public BoomEconomy(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());
    }

    public BoomEconomy(UnitTypeTable a_utt, PathFinding a_pf) {
        super(a_pf);
        reset(a_utt);
    }

    public void reset() {
        super.reset();
    }

    public void reset(UnitTypeTable a_utt) {
        utt = a_utt;
        workerType = utt.getUnitType("Worker");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
        lightType = utt.getUnitType("Light");
    }

    public AI clone() {
        return new BoomEconomy(utt, pf);
    }

    public PlayerAction getAction(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);

        // Count our units
        int nworkers = 0;
        int nmilitary = 0;
        int nbases = 0;
        int nbarracks = 0;

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player) {
                if (u.getType() == workerType) nworkers++;
                else if (u.getType().canAttack && !u.getType().canHarvest) nmilitary++;
                if (u.getType() == baseType) nbases++;
                if (u.getType() == barracksType) nbarracks++;
            }
        }

        // Decide if we should be in economy mode or military mode
        boolean economyMode = (nworkers < TARGET_WORKERS) || (p.getResources() < ECON_RESOURCE_THRESHOLD && nmilitary == 0);

        // Base behavior
        for (Unit u : pgs.getUnits()) {
            if (u.getType() == baseType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                baseBehavior(u, p, pgs, nworkers, economyMode);
            }
        }

        // Barracks behavior: only produce when not in economy mode
        for (Unit u : pgs.getUnits()) {
            if (u.getType() == barracksType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                if (!economyMode) {
                    barracksBehavior(u, p, pgs);
                }
            }
        }

        // Military unit behavior: attack nearest enemy
        for (Unit u : pgs.getUnits()) {
            if (u.getType().canAttack && !u.getType().canHarvest && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                meleeUnitBehavior(u, p, gs);
            }
        }

        // Worker behavior
        List<Unit> workers = new LinkedList<>();
        for (Unit u : pgs.getUnits()) {
            if (u.getType().canHarvest && u.getPlayer() == player) {
                workers.add(u);
            }
        }
        workersBehavior(workers, p, gs, nbases, nbarracks, economyMode);

        return translateActions(player, gs);
    }

    public void baseBehavior(Unit u, Player p, PhysicalGameState pgs, int nworkers, boolean economyMode) {
        // In economy mode, always train workers up to target
        if (economyMode && nworkers < TARGET_WORKERS && p.getResources() >= workerType.cost) {
            train(u, workerType);
        } else if (!economyMode && nworkers < 2 && p.getResources() >= workerType.cost) {
            // Maintain at least 2 workers even in military mode
            train(u, workerType);
        }
    }

    public void barracksBehavior(Unit u, Player p, PhysicalGameState pgs) {
        if (p.getResources() >= lightType.cost) {
            train(u, lightType);
        }
    }

    public void meleeUnitBehavior(Unit u, Player p, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Unit closestEnemy = null;
        int closestDistance = 0;
        for (Unit u2 : pgs.getUnits()) {
            if (u2.getPlayer() >= 0 && u2.getPlayer() != p.getID()) {
                int d = Math.abs(u2.getX() - u.getX()) + Math.abs(u2.getY() - u.getY());
                if (closestEnemy == null || d < closestDistance) {
                    closestEnemy = u2;
                    closestDistance = d;
                }
            }
        }
        if (closestEnemy != null) {
            attack(u, closestEnemy);
        }
    }

    public void workersBehavior(List<Unit> workers, Player p, GameState gs, int nbases, int nbarracks, boolean economyMode) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        int resourcesUsed = 0;
        List<Unit> freeWorkers = new LinkedList<>(workers);

        if (workers.isEmpty()) return;

        List<Integer> reservedPositions = new LinkedList<>();

        // Build base if none
        if (nbases == 0 && !freeWorkers.isEmpty()) {
            if (p.getResources() >= baseType.cost + resourcesUsed) {
                Unit u = freeWorkers.remove(0);
                buildIfNotAlreadyBuilding(u, baseType, u.getX(), u.getY(), reservedPositions, p, pgs);
                resourcesUsed += baseType.cost;
            }
        }

        // In boom mode, consider building second base before barracks
        if (economyMode && nbases < MAX_BASES && nbases > 0 && !freeWorkers.isEmpty()) {
            if (p.getResources() >= baseType.cost + resourcesUsed + 4) {  // Extra buffer for second base
                Unit u = freeWorkers.remove(0);
                // Find position away from first base
                Unit firstBase = null;
                for (Unit u2 : pgs.getUnits()) {
                    if (u2.getType() == baseType && u2.getPlayer() == p.getID()) {
                        firstBase = u2;
                        break;
                    }
                }
                // Build near resources but away from first base
                int buildX = u.getX();
                int buildY = u.getY();
                if (firstBase != null) {
                    // Move towards center of map, away from first base
                    int centerX = pgs.getWidth() / 2;
                    int centerY = pgs.getHeight() / 2;
                    if (Math.abs(u.getX() - centerX) < Math.abs(firstBase.getX() - centerX)) {
                        buildX = u.getX();
                        buildY = u.getY();
                    }
                }
                buildIfNotAlreadyBuilding(u, baseType, buildX, buildY, reservedPositions, p, pgs);
                resourcesUsed += baseType.cost;
            }
        }

        // Build barracks (only when not in pure economy mode or have good resources)
        if (nbarracks == 0 && !freeWorkers.isEmpty()) {
            if (!economyMode || p.getResources() >= barracksType.cost + resourcesUsed + 4) {
                if (p.getResources() >= barracksType.cost + resourcesUsed) {
                    Unit u = freeWorkers.remove(0);
                    buildIfNotAlreadyBuilding(u, barracksType, u.getX(), u.getY(), reservedPositions, p, pgs);
                    resourcesUsed += barracksType.cost;
                }
            }
        }

        // All free workers harvest
        for (Unit u : freeWorkers) {
            Unit closestBase = null;
            Unit closestResource = null;
            int closestDistance = 0;

            for (Unit u2 : pgs.getUnits()) {
                if (u2.getType().isResource) {
                    int d = Math.abs(u2.getX() - u.getX()) + Math.abs(u2.getY() - u.getY());
                    if (closestResource == null || d < closestDistance) {
                        closestResource = u2;
                        closestDistance = d;
                    }
                }
            }
            closestDistance = 0;
            for (Unit u2 : pgs.getUnits()) {
                if (u2.getType().isStockpile && u2.getPlayer() == p.getID()) {
                    int d = Math.abs(u2.getX() - u.getX()) + Math.abs(u2.getY() - u.getY());
                    if (closestBase == null || d < closestDistance) {
                        closestBase = u2;
                        closestDistance = d;
                    }
                }
            }

            if (u.getResources() > 0) {
                if (closestBase != null) {
                    AbstractAction aa = getAbstractAction(u);
                    if (!(aa instanceof Harvest) || ((Harvest) aa).base != closestBase) {
                        harvest(u, null, closestBase);
                    }
                }
            } else {
                if (closestResource != null && closestBase != null) {
                    AbstractAction aa = getAbstractAction(u);
                    if (!(aa instanceof Harvest) || ((Harvest) aa).target != closestResource || ((Harvest) aa).base != closestBase) {
                        harvest(u, closestResource, closestBase);
                    }
                }
            }
        }
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }
}
