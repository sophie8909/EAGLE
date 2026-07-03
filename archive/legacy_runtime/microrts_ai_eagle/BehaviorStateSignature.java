package ai.eagle;

import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitType;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Builds a stable behavior-only signature for EAGLE decision caching.
 */
public final class BehaviorStateSignature {
    private BehaviorStateSignature() {
    }

    public static String from(GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        List<String> players = new ArrayList<>();
        for (Player player : pgs.getPlayers()) {
            players.add("player=" + player.getID() + "|resources=" + player.getResources());
        }
        Collections.sort(players);

        List<String> units = new ArrayList<>();
        for (Unit unit : pgs.getUnits()) {
            units.add(String.join("|",
                    "owner=" + unit.getPlayer(),
                    "type=" + unitTypeName(unit.getType()),
                    "hp=" + unit.getHitPoints(),
                    "carried=" + unit.getResources(),
                    "action=" + actionSignature(unit, gs.getUnitAction(unit), pgs)
            ));
        }
        Collections.sort(units);

        return "players[" + String.join(";", players) + "]|units[" + String.join(";", units) + "]";
    }

    public static boolean isEnabled() {
        return readBooleanSetting("eagle.skip_same_behavior_state", "EAGLE_SKIP_SAME_BEHAVIOR_STATE", true);
    }

    private static boolean readBooleanSetting(String propertyName, String envName, boolean defaultValue) {
        String raw = System.getProperty(propertyName);
        if (raw == null || raw.isBlank()) {
            raw = System.getenv(envName);
        }
        if (raw == null || raw.isBlank()) {
            return defaultValue;
        }
        String normalized = raw.trim().toLowerCase();
        return normalized.equals("1")
                || normalized.equals("true")
                || normalized.equals("yes")
                || normalized.equals("on");
    }

    private static String actionSignature(Unit unit, UnitAction action, PhysicalGameState pgs) {
        if (action == null || action.getType() == UnitAction.TYPE_NONE) {
            return "none";
        }
        switch (action.getType()) {
            case UnitAction.TYPE_MOVE:
                return "move:direction=" + directionName(action.getDirection());
            case UnitAction.TYPE_HARVEST:
                return "harvest:direction=" + directionName(action.getDirection())
                        + ":target=" + adjacentTargetSignature(unit, action, pgs);
            case UnitAction.TYPE_RETURN:
                return "return:direction=" + directionName(action.getDirection())
                        + ":target=" + adjacentTargetSignature(unit, action, pgs);
            case UnitAction.TYPE_PRODUCE:
                return "produce:direction=" + directionName(action.getDirection())
                        + ":unit=" + unitTypeName(action.getUnitType());
            case UnitAction.TYPE_ATTACK_LOCATION:
                return "attack_location:target=" + locationTargetSignature(action, pgs);
            default:
                return "type_" + action.getType();
        }
    }

    private static String adjacentTargetSignature(Unit unit, UnitAction action, PhysicalGameState pgs) {
        int direction = action.getDirection();
        if (direction < 0 || direction >= UnitAction.DIRECTION_OFFSET_X.length) {
            return "none";
        }
        int targetX = unit.getX() + UnitAction.DIRECTION_OFFSET_X[direction];
        int targetY = unit.getY() + UnitAction.DIRECTION_OFFSET_Y[direction];
        return unitAtSignature(pgs, targetX, targetY);
    }

    private static String locationTargetSignature(UnitAction action, PhysicalGameState pgs) {
        return unitAtSignature(pgs, action.getLocationX(), action.getLocationY());
    }

    private static String unitAtSignature(PhysicalGameState pgs, int x, int y) {
        Unit target = pgs.getUnitAt(x, y);
        if (target == null) {
            return "empty";
        }
        return "owner=" + target.getPlayer() + ",type=" + unitTypeName(target.getType());
    }

    private static String unitTypeName(UnitType unitType) {
        return unitType == null ? "none" : unitType.name;
    }

    private static String directionName(int direction) {
        if (direction >= 0 && direction < UnitAction.DIRECTION_NAMES.length) {
            return UnitAction.DIRECTION_NAMES[direction];
        }
        return "none";
    }
}
