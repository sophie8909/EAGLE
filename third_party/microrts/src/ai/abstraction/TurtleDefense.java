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
 * TurtleDefense: Defensive strategy that prioritizes economy and defense.
 *
 * Strategy:
 * - Train multiple workers (3-4) for strong economy
 * - Build barracks and train heavy units for defense
 * - Military units defend near base until sufficient force (5+ units)
 * - Only attack when army is large enough
 *
 * Counter: Good against early rushes, weak to harassment and late-game ranged
 */
public class TurtleDefense extends AbstractionLayerAI {

    protected UnitTypeTable utt;
    UnitType workerType;
    UnitType baseType;
    UnitType barracksType;
    UnitType heavyType;

    // Configuration
    private static final int TARGET_WORKERS = 3;
    private static final int ATTACK_THRESHOLD = 5;  // Attack when we have 5+ military

    public TurtleDefense(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());
    }

    public TurtleDefense(UnitTypeTable a_utt, PathFinding a_pf) {
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
        heavyType = utt.getUnitType("Heavy");
    }

    public AI clone() {
        return new TurtleDefense(utt, pf);
    }

    public PlayerAction getAction(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);

        // Count our units
        int nworkers = 0;
        int nmilitary = 0;
        Unit ourBase = null;

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player) {
                if (u.getType() == workerType) nworkers++;
                else if (u.getType().canAttack && !u.getType().canHarvest) nmilitary++;
                if (u.getType() == baseType) ourBase = u;
            }
        }

        // Base behavior: train workers until target, then save resources
        for (Unit u : pgs.getUnits()) {
            if (u.getType() == baseType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                baseBehavior(u, p, pgs, nworkers);
            }
        }

        // Barracks behavior: train heavy units
        for (Unit u : pgs.getUnits()) {
            if (u.getType() == barracksType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                barracksBehavior(u, p, pgs);
            }
        }

        // Military unit behavior: defend or attack
        for (Unit u : pgs.getUnits()) {
            if (u.getType().canAttack && !u.getType().canHarvest && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                militaryBehavior(u, p, gs, ourBase, nmilitary);
            }
        }

        // Worker behavior
        List<Unit> workers = new LinkedList<>();
        for (Unit u : pgs.getUnits()) {
            if (u.getType().canHarvest && u.getPlayer() == player) {
                workers.add(u);
            }
        }
        workersBehavior(workers, p, gs);

        return translateActions(player, gs);
    }

    public void baseBehavior(Unit u, Player p, PhysicalGameState pgs, int nworkers) {
        if (nworkers < TARGET_WORKERS && p.getResources() >= workerType.cost) {
            train(u, workerType);
        }
    }

    public void barracksBehavior(Unit u, Player p, PhysicalGameState pgs) {
        if (p.getResources() >= heavyType.cost) {
            train(u, heavyType);
        }
    }

    public void militaryBehavior(Unit u, Player p, GameState gs, Unit ourBase, int nmilitary) {
        PhysicalGameState pgs = gs.getPhysicalGameState();

        // Find closest enemy
        Unit closestEnemy = null;
        int closestDistance = Integer.MAX_VALUE;
        for (Unit u2 : pgs.getUnits()) {
            if (u2.getPlayer() >= 0 && u2.getPlayer() != p.getID()) {
                int d = Math.abs(u2.getX() - u.getX()) + Math.abs(u2.getY() - u.getY());
                if (d < closestDistance) {
                    closestEnemy = u2;
                    closestDistance = d;
                }
            }
        }

        if (closestEnemy == null) return;

        // If enemy is close (attacking us) or we have enough force, attack
        boolean enemyClose = closestDistance < 6;
        boolean readyToAttack = nmilitary >= ATTACK_THRESHOLD;

        if (enemyClose || readyToAttack) {
            attack(u, closestEnemy);
        } else if (ourBase != null) {
            // Stay near base - move towards base if too far
            int distFromBase = Math.abs(u.getX() - ourBase.getX()) + Math.abs(u.getY() - ourBase.getY());
            if (distFromBase > 4) {
                move(u, ourBase.getX(), ourBase.getY());
            } else {
                // Idle near base
                idle(u);
            }
        } else {
            attack(u, closestEnemy);
        }
    }

    public void workersBehavior(List<Unit> workers, Player p, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        int nbases = 0;
        int nbarracks = 0;
        int resourcesUsed = 0;
        List<Unit> freeWorkers = new LinkedList<>(workers);

        if (workers.isEmpty()) return;

        for (Unit u2 : pgs.getUnits()) {
            if (u2.getType() == baseType && u2.getPlayer() == p.getID()) nbases++;
            if (u2.getType() == barracksType && u2.getPlayer() == p.getID()) nbarracks++;
        }

        List<Integer> reservedPositions = new LinkedList<>();

        // Build base if none
        if (nbases == 0 && !freeWorkers.isEmpty()) {
            if (p.getResources() >= baseType.cost + resourcesUsed) {
                Unit u = freeWorkers.remove(0);
                buildIfNotAlreadyBuilding(u, baseType, u.getX(), u.getY(), reservedPositions, p, pgs);
                resourcesUsed += baseType.cost;
            }
        }

        // Build barracks if none (prioritize this for defense)
        if (nbarracks == 0 && !freeWorkers.isEmpty()) {
            if (p.getResources() >= barracksType.cost + resourcesUsed) {
                Unit u = freeWorkers.remove(0);
                buildIfNotAlreadyBuilding(u, barracksType, u.getX(), u.getY(), reservedPositions, p, pgs);
                resourcesUsed += barracksType.cost;
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
