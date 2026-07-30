package ai.abstraction;

import ai.abstraction.pathfinding.FloodFillPathFinding;
import ai.core.AI;
import rts.units.UnitTypeTable;

/** LightRush using the vendored flood-fill pathfinder. */
public final class FloodFillLightRush extends LightRush {
    public FloodFillLightRush(UnitTypeTable utt) {
        super(utt, new FloodFillPathFinding());
    }

    @Override
    public AI clone() {
        return new FloodFillLightRush(utt);
    }
}
