package ai.abstraction;

import ai.abstraction.pathfinding.BFSPathFinding;
import ai.core.AI;
import rts.units.UnitTypeTable;

/** HeavyRush using the vendored BFS pathfinder. */
public final class BFSHeavyRush extends HeavyRush {
    public BFSHeavyRush(UnitTypeTable utt) {
        super(utt, new BFSPathFinding());
    }

    @Override
    public AI clone() {
        return new BFSHeavyRush(utt);
    }
}
