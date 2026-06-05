package tests.eagle;

import ai.eagle.BehaviorStateSignature;
import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.PlayerAction;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;

public final class BehaviorStateSignatureTest {
    private static final UnitTypeTable UTT = new UnitTypeTable();
    private static final UnitType WORKER = UTT.getUnitType("Worker");
    private static final UnitType BASE = UTT.getUnitType("Base");
    private static final UnitType RESOURCE = UTT.getUnitType("Resource");

    private BehaviorStateSignatureTest() {
    }

    public static void main(String[] args) {
        assertEquals(signature(baseState(1, 1, 5, 5)), signature(baseState(2, 2, 6, 6)),
                "coordinates should not affect behavior signature");
        assertNotEquals(signature(baseState(1, 1, 5, 5)), signature(withWorkerHp(3)),
                "HP should affect behavior signature");
        assertNotEquals(signature(baseState(1, 1, 5, 5)), signature(withCarriedResources(1)),
                "carried resources should affect behavior signature");
        assertNotEquals(signature(baseState(1, 1, 5, 5)), signature(withPlayerResources(3, 2)),
                "player resources should affect behavior signature");
        assertNotEquals(signature(withMoveAction()), signature(withAttackLocationTargetingWorker()),
                "current action type should affect behavior signature");
        assertNotEquals(signature(withAttackLocationTargetingWorker()), signature(withAttackLocationTargetingBase()),
                "action target type should affect behavior signature");
        System.out.println("BehaviorStateSignatureTest passed");
    }

    private static String signature(GameState gs) {
        return BehaviorStateSignature.from(gs);
    }

    private static GameState baseState(int allyX, int allyY, int enemyX, int enemyY) {
        PhysicalGameState pgs = new PhysicalGameState(8, 8);
        pgs.addPlayer(new Player(0, 2));
        pgs.addPlayer(new Player(1, 1));
        pgs.addUnit(new Unit(100, 0, WORKER, allyX, allyY, 0));
        pgs.addUnit(new Unit(101, 1, WORKER, enemyX, enemyY, 0));
        pgs.addUnit(new Unit(102, -1, RESOURCE, 3, 3, 4));
        return new GameState(pgs, UTT);
    }

    private static GameState withWorkerHp(int hp) {
        GameState gs = baseState(1, 1, 5, 5);
        gs.getPhysicalGameState().getUnit(100).setHitPoints(hp);
        return gs;
    }

    private static GameState withCarriedResources(int resources) {
        GameState gs = baseState(1, 1, 5, 5);
        gs.getPhysicalGameState().getUnit(100).setResources(resources);
        return gs;
    }

    private static GameState withPlayerResources(int p0Resources, int p1Resources) {
        GameState gs = baseState(1, 1, 5, 5);
        gs.getPhysicalGameState().getPlayer(0).setResources(p0Resources);
        gs.getPhysicalGameState().getPlayer(1).setResources(p1Resources);
        return gs;
    }

    private static GameState withMoveAction() {
        GameState gs = baseState(1, 1, 5, 5);
        Unit ally = gs.getPhysicalGameState().getUnit(100);
        PlayerAction pa = new PlayerAction();
        pa.addUnitAction(ally, new UnitAction(UnitAction.TYPE_MOVE, UnitAction.DIRECTION_RIGHT));
        gs.issue(pa);
        return gs;
    }

    private static GameState withAttackLocationTargetingWorker() {
        GameState gs = actionTargetState(false);
        Unit ally = gs.getPhysicalGameState().getUnit(100);
        PlayerAction pa = new PlayerAction();
        pa.addUnitAction(ally, new UnitAction(UnitAction.TYPE_ATTACK_LOCATION, 2, 1));
        gs.issue(pa);
        return gs;
    }

    private static GameState withAttackLocationTargetingBase() {
        GameState gs = actionTargetState(true);
        Unit ally = gs.getPhysicalGameState().getUnit(100);
        PlayerAction pa = new PlayerAction();
        pa.addUnitAction(ally, new UnitAction(UnitAction.TYPE_ATTACK_LOCATION, 2, 1));
        gs.issue(pa);
        return gs;
    }

    private static GameState actionTargetState(boolean baseAtTarget) {
        PhysicalGameState pgs = new PhysicalGameState(8, 8);
        pgs.addPlayer(new Player(0, 2));
        pgs.addPlayer(new Player(1, 1));
        pgs.addUnit(new Unit(100, 0, WORKER, 1, 1, 0));
        if (baseAtTarget) {
            pgs.addUnit(new Unit(101, 1, BASE, 2, 1, 0));
            pgs.addUnit(new Unit(102, 1, WORKER, 5, 5, 0));
        } else {
            pgs.addUnit(new Unit(101, 1, WORKER, 2, 1, 0));
            pgs.addUnit(new Unit(102, 1, BASE, 5, 5, 0));
        }
        pgs.addUnit(new Unit(103, -1, RESOURCE, 3, 3, 4));
        return new GameState(pgs, UTT);
    }

    private static void assertEquals(String expected, String actual, String message) {
        if (!expected.equals(actual)) {
            throw new AssertionError(message + "\nexpected=" + expected + "\nactual=" + actual);
        }
    }

    private static void assertNotEquals(String first, String second, String message) {
        if (first.equals(second)) {
            throw new AssertionError(message + "\nsignature=" + first);
        }
    }
}
