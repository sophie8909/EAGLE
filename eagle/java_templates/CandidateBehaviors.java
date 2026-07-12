package ai.generated;

import java.util.ArrayList;
import java.util.List;
import rts.units.Unit;

public final class CandidateBehaviors {
    public Decision decide(AgentContext context) {
        /* EAGLE_BODY:controller */
    }
    public List<ActionProposal> economy(AgentContext context) {
        /* EAGLE_BODY:economy */
    }
    public List<ActionProposal> combat(AgentContext context) {
        /* EAGLE_BODY:combat */
    }
    public List<ActionProposal> expansion(AgentContext context) {
        /* EAGLE_BODY:expansion */
    }
    public Unit selectTarget(AgentContext context, Unit actor, List<Unit> candidates) {
        /* EAGLE_BODY:target_selection */
    }
    public PathChoice findPath(AgentContext context, Unit unit, int targetX, int targetY) {
        /* EAGLE_BODY:path_selection */
    }
}
