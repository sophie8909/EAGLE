package ai.abstraction;

import ai.abstraction.pathfinding.AStarPathFinding;
import ai.core.AI;
import rts.units.UnitTypeTable;

/** LightRush using the vendored A* pathfinder as an explicit roster entry. */
public final class AStarLightRush extends LightRush {
    public AStarLightRush(UnitTypeTable utt) {
        super(utt, new AStarPathFinding());
    }

    @Override
    public AI clone() {
        return new AStarLightRush(utt);
    }
}
