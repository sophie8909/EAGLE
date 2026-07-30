package ai.abstraction;

import ai.abstraction.pathfinding.BFSPathFinding;
import ai.core.AI;
import rts.units.UnitTypeTable;

/** LightRush using the vendored BFS pathfinder. */
public final class BFSLightRush extends LightRush {
    public BFSLightRush(UnitTypeTable utt) {
        super(utt, new BFSPathFinding());
    }

    @Override
    public AI clone() {
        return new BFSLightRush(utt);
    }
}
