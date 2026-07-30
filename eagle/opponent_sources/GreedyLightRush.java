package ai.abstraction;

import ai.abstraction.pathfinding.GreedyPathFinding;
import ai.core.AI;
import rts.units.UnitTypeTable;

/** LightRush using the vendored greedy pathfinder. */
public final class GreedyLightRush extends LightRush {
    public GreedyLightRush(UnitTypeTable utt) {
        super(utt, new GreedyPathFinding());
    }

    @Override
    public AI clone() {
        return new GreedyLightRush(utt);
    }
}
