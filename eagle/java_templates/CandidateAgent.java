package ai.generated;

import ai.core.AI;
import ai.core.ParameterSpecification;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PlayerAction;
import rts.PlayerActionGenerator;
import rts.units.Unit;
import rts.units.UnitTypeTable;

public final class CandidateAgent extends AI {
    private final CandidateBehaviors behaviors = new CandidateBehaviors();
    public CandidateAgent(UnitTypeTable utt) {}
    public CandidateAgent() {}
    @Override public void reset() {}
    @Override public AI clone() { return new CandidateAgent(); }
    @Override public PlayerAction getAction(int player, GameState gs) throws Exception {
        try {
            if (!gs.canExecuteAnyAction(player)) return new PlayerAction();
            AgentContext context = new AgentContext(player, gs, new ArrayList<>(gs.getUnits()));
            Decision decision = behaviors.decide(context);
            decision.proposals.addAll(behaviors.economy(context));
            decision.proposals.addAll(behaviors.combat(context));
            decision.proposals.addAll(behaviors.expansion(context));
            if (!context.units.isEmpty()) {
                Unit actor = context.units.get(0);
                Unit target = behaviors.selectTarget(context, actor, context.units);
                behaviors.findPath(context, actor, target == null ? actor.getX() : target.getX(), target == null ? actor.getY() : target.getY());
            }
            return executeDecision(context, decision);
        } catch (Exception exc) {
            PlayerAction fallback = new PlayerAction();
            fallback.fillWithNones(gs, player, 10);
            return fallback;
        }
    }
    private PlayerAction executeDecision(AgentContext context, Decision decision) throws Exception {
        PlayerActionGenerator generator = new PlayerActionGenerator(context.gs, context.player);
        PlayerAction action = generator.getRandom();
        action.fillWithNones(context.gs, context.player, 10);
        return action;
    }
    @Override public List<ParameterSpecification> getParameters() { return new ArrayList<>(); }
}

final class AgentContext {
    final int player; final GameState gs; final List<Unit> units;
    AgentContext(int player, GameState gs, List<Unit> units) { this.player = player; this.gs = gs; this.units = units; }
}
final class Decision { final List<ActionProposal> proposals = new ArrayList<>(); }
final class ActionProposal {
    final Unit actor; final Unit target; final String intent; final int targetX; final int targetY;
    ActionProposal(Unit actor, Unit target, String intent, int targetX, int targetY) {
        this.actor = actor; this.target = target; this.intent = intent; this.targetX = targetX; this.targetY = targetY;
    }
}
final class PathChoice {
    final int x; final int y;
    PathChoice(int x, int y) { this.x = x; this.y = y; }
}
