package ai.abstraction;

import ai.RandomBiasedAI;
import ai.abstraction.pathfinding.AStarPathFinding;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;

public class {{CLASS_NAME}} extends AbstractionLayerAI {

    private final String strategyIdentity = "{{STRATEGY_IDENTITY}}";
    protected UnitTypeTable utt;
    UnitType workerType;
    UnitType baseType;
    UnitType barracksType;

    public {{CLASS_NAME}}(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());
    }

    public {{CLASS_NAME}}(UnitTypeTable a_utt, PathFinding a_pf) {
        super(a_pf);
        reset(a_utt);
    }

    public void reset() {
        super.reset();
    }

    public void reset(UnitTypeTable a_utt) {
        utt = a_utt;
        if (utt != null) {
            workerType = utt.getUnitType("Worker");
            baseType = utt.getUnitType("Base");
            barracksType = utt.getUnitType("Barracks");
        }
    }

    @Override
    public AI clone() {
        return new {{CLASS_NAME}}(utt, pf);
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }

    private AI buildFallbackAi() {
        if ("aggressive".equals(strategyIdentity)) {
            return new LightRush(utt, pf);
        }
        if ("economic".equals(strategyIdentity)) {
            return new WorkerRush(utt, pf);
        }
        if ("balanced".equals(strategyIdentity)) {
            return new RangedRush(utt, pf);
        }
        return new RandomBiasedAI(utt);
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        // Dispatch logic
        // TODO: iterate units and call handlers
        PhysicalGameState pgs = gs.getPhysicalGameState();
        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() != player || gs.getActionAssignment(u) != null) {
                continue;
            }
            if (u.getType() == workerType) {
                workerLogic(u, gs);
            } else if (u.getType() == baseType) {
                baseLogic(u, gs);
            } else if (u.getType() == barracksType) {
                barracksLogic(u, gs);
            } else if (u.getType().canAttack) {
                combatLogic(u, gs);
            } else {
                defenseLogic(u, gs);
            }
        }
        return buildFallbackAi().getAction(player, gs);
    }

    private UnitAction workerLogic(Unit u, GameState gs) {
        {{WORKER_RULE}}
    }

    private UnitAction baseLogic(Unit u, GameState gs) {
        {{BASE_RULE}}
    }

    private UnitAction barracksLogic(Unit u, GameState gs) {
        {{BARRACKS_RULE}}
    }

    private UnitAction combatLogic(Unit u, GameState gs) {
        {{COMBAT_RULE}}
    }

    private UnitAction defenseLogic(Unit u, GameState gs) {
        {{DEFENSE_RULE}}
    }

    private UnitAction fallbackWorkerAction(Unit u, GameState gs) {
        return null;
    }

    private UnitAction fallbackBaseAction(Unit u, GameState gs) {
        return null;
    }

    private UnitAction fallbackBarracksAction(Unit u, GameState gs) {
        return null;
    }

    private UnitAction fallbackCombatAction(Unit u, GameState gs) {
        return null;
    }

    private UnitAction fallbackDefenseAction(Unit u, GameState gs) {
        return null;
    }
}
