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
    private static final boolean INJECTED_STRATEGY_ENABLED = true;
    private static final int WORKER_TARGET_BEFORE_BARRACKS = 1;
    private static final int WORKER_TARGET_AFTER_BARRACKS = 4;
    private static final int HARVESTER_TARGET = 2;
    private static final int DESIRED_BARRACKS = 1;
    private static final boolean WORKER_HARASS_ENABLED = false;
    private static final boolean ATTACK_WORKERS_FIRST = false;
    private static final boolean ATTACK_STRUCTURES_FIRST = false;
    private static final boolean PROTECT_BARRACKS = true;
    private static final int MIN_LIGHTS = 2;
    private static final int MIN_RANGED = 0;
    private static final int MIN_HEAVIES = 0;
    private static final String[] PRODUCTION_PRIORITY = {
        "Light",
        "Light",
        "Ranged"
    };
    // SURROGATE_SPEC_END

    // SURROGATE_PROMPT_START
    private static final String[] EMBEDDED_PROMPT_LINES = {
        "GAME RULES:",
        "Two players, Player 1 (Ally) and Player 2 (Enemy) are competing to eliminate all opposing enemy units in a Real Time Strategy (RTS) game.",
        "Each step, each player can assign actions to their units if they are not already doing an action. Each unit can only be assigned ONE action.",
        "Players can only assign actions to their ally units.",
        "There are 6 available actions:",
        "move((Target_x, Target_y))",
        "- Move unit to target location",
        "train(Unit_Type)",
        "- Train a unit (Base and Barracks only)",
        "build((Target_x, Target_y), Building_Type)",
        "- Worker builds building",
        "- Resources are consumed from Ally base",
        "harvest((Resource_x, Resource_y), (Ally_Base_x, Ally_Base_y))",
        "- Worker collects resources and returns to base",
        "attack((Enemy_x, Enemy_y))",
        "- Attack enemy unit",
        "idle()",
        "- Do nothing this turn",
        "WIN CONDITION:",
        "- Destroy all enemy units and buildings",
        "UNIT TYPES:",
        "worker:",
        "- HP: 1",
        "- Cost: 1",
        "- Damage: 1",
        "- Range: 1",
        "- Speed: 1",
        "- Abilities: gather resources, build base, build barracks",
        "- Trained by: base",
        "light:",
        "- HP: 4",
        "- Cost: 2",
        "- Damage: 2",
        "- Range: 1",
        "- Speed: 2",
        "- Abilities: fast attacker",
        "Trained by: barracks",
        "heavy:",
        "- HP: 8",
        "- Cost: 3",
        "- Damage: 4",
        "- Range: 1",
        "- Speed: 1",
        "- Abilities: tank unit",
        "Trained by: barracks",
        "ranged:",
        "- HP: 3",
        "- Cost: 2",
        "- Damage: 1",
        "- Range: 3",
        "- Speed: 1",
        "- Abilities: long range attacker",
        "- Trained by: barracks",
        "BUILDING TYPES:",
        "base:",
        "- HP: 10",
        "- Cost: 10",
        "- Abilities: train workers, store resources",
        "barracks:",
        "- HP: 5",
        "- Cost: 5",
        "- Abilities: train light, heavy, ranged units",
        "SUGGESTED STRATEGY:",
        "Early Game:",
        "- Harvest nonstop",
        "- Build barracks at 5 resources",
        "Mid Game:",
        "- Train army",
        "- Hunt enemy workers",
        "- Protect barracks",
        "Late Game:",
        "- Group attack",
        "- Destroy production buildings",
        "- Control resources",
        "GAME STATE FORMAT:",
        "Map size is given",
        "Feature locations list all units and buildings",
        "Coordinates are zero-indexed",
        "Units and buildings have properties:",
        "- HP",
        "- resources",
        "- current_action",
        "- available",
        "available = true means unit can receive command",
        "RAW MOVE FORMAT:",
        "(X, Y): Unit_Type Action(Action_Arguments)",
        "X: unit x position",
        "Y: unit y position",
        "Unit_Type: worker, light, heavy, ranged, base, barracks",
        "Action: move, train, build, harvest, attack, idle",
        "Action_Arguments: arguments for action",
        "There are 6 available actions:",
        "- `move` - Unit will move to target location.",
        "    - Arguments: ((Target_x, Target_y))",
        "- `train` - Unit will train the provided unit type (only bases and barracks can use this action).",
        "    - Arguments: (Unit_Type)",
        "- `build` - Unit will build the provided building type at the target location, consuming the resource cost from the ally base (only workers can use this action).",
        "    - Arguments: ((Target_x, Target_y), Building_Type)",
        "- `harvest` - Unit will navigate to the target resource, collect a resource and bring it back to the target ally base.",
        "    - Arguments: ((Resource_x, Resource_y), (Ally_Base_x, Ally_Base_y))",
        "- `attack` - Unit will navigate to, and attack the target enemy.",
        "    - Arguments: ((Enemy_x, Enemy_y))",
        "- `idle` - The target unit will do nothing for a round. This is the default for all available units that are not assigned an action.",
        "    - Arguments: ()",
        "REQUIRED JSON FORMAT:",
        "{",
        "  \"thinking\": \"Brief strategy\",",
        "  \"moves\": [",
        "    {",
        "      \"raw_move\": \"(x, y): unit_type action((args))\",",
        "      \"unit_position\": [x, y],",
        "      \"unit_type\": \"worker\",",
        "      \"action_type\": \"harvest\"",
        "    }",
        "  ]",
        "}",
        "EVERY MOVE OBJECT MUST HAVE ALL 4 FIELDS:",
        "- raw_move: string like \"(2, 0): worker harvest((0, 0), (2, 1))\"",
        "- unit_position: [x, y] array matching your Ally unit position",
        "- unit_type: \"worker\", \"base\", \"barracks\", \"light\", \"heavy\", or \"ranged\"",
        "- action_type: \"move\", \"harvest\", \"train\", \"build\", or \"attack\"",
        "VALID MOVE EXAMPLES:",
        "{\"raw_move\": \"(1, 1): worker harvest((0, 0), (2, 1))\", \"unit_position\": [1, 1], \"unit_type\": \"worker\", \"action_type\": \"harvest\"}",
        "{\"raw_move\": \"(2, 1): base train(worker)\", \"unit_position\": [2, 1], \"unit_type\": \"base\", \"action_type\": \"train\"}",
        "{\"raw_move\": \"(1, 1): worker attack((5, 6))\", \"unit_position\": [1, 1], \"unit_type\": \"worker\", \"action_type\": \"attack\"}",
        "{\"raw_move\": \"(1, 1): worker move((3, 3))\", \"unit_position\": [1, 1], \"unit_type\": \"worker\", \"action_type\": \"move\"}",
        "{\"raw_move\": \"(1, 1): worker build((3, 3), barracks)\", \"unit_position\": [1, 1], \"unit_type\": \"worker\", \"action_type\": \"build\"}",
        "STRATEGY IDENTITY: Balanced pressure.",
        "Maintain a workable balance between economy, production, defense, and map pressure at all times.",
        "Risk tolerance is moderate: respect immediate threats, but exploit exposed workers, units, or structures when trades are efficient.",
        "Pressure timing is opportunistic rather than rushed or delayed, leaning into advantages as soon as they become credible.",
        "Preferred win path is to stay structurally sound while accumulating incremental gains that snowball into a winning position.",
        "PHASE TRANSITION RULE:",
        "Early game lasts while economy is still being established: worker count is low, no barracks exists, or income is not yet stable.",
        "Shift to mid game once a barracks exists or military production is online and both sides can realistically contest space.",
        "Shift to late game when one side has enough army presence or map control that the next major fights can decide production or base survival.",
        "Use turn count only as a weak tiebreaker when state signals are unclear.",
        "EARLY GAME PLAN:",
        "Aim for minimal but stable economy first, then convert quickly into the first production structure and first combat units.",
        "Use one suitable worker as the builder and keep the rest harvesting efficiently.",
        "Avoid premature full commitment until at least a small force can pressure or defend coherently.",
        "MID GAME PLAN:",
        "Shift focus towards aggressive expansion by leveraging established economic stability and initial military presence.",
        "Sustain combat readiness through regular unit replacement and reinforce bases with strategic defensive structures.",
        "Target exposed enemy resources, disrupting their production and economy while minimizing risks in early engagements.",
        "LATE GAME PLAN:",
        "Once both sides have reduced economies or damaged structure counts, each unit matters more than long-term scaling.",
        "Collapse on the enemy system with coordinated pressure instead of splitting into low-value chases.",
        "If a base race emerges, favor actions that end the enemy faster or preserve the minimum structure needed to win.",
        "DECISION PRIORITY:",
        "1. Prevent immediate loss of base, barracks, or trapped workers when survival is at stake.",
        "2. Take immediate attack or kill opportunities that damage enemy production, base, or exposed workers.",
        "3. Maintain production uptime if resources and safe production options exist.",
        "4. Maintain enough harvesting to keep production alive.",
        "5. Reposition for the next useful fight or objective.",
        "TACTICAL HEURISTICS:",
        "If an enemy is already in range, attack immediately unless a higher-priority survival rule forbids it.",
        "Prefer finishing low-health enemies when that removes damage or clears the path to a high-value objective.",
        "Do not retreat from a favorable engagement just to reposition decoratively.",
        "ANTI-STALL RULES:",
        "Do not leave workers idle if they can harvest, build, defend, or attack productively.",
        "Do not leave bases or barracks idle when resources can be converted into useful production.",
        "Do not float resources for long when the current phase plan clearly wants workers, barracks, or units."
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
