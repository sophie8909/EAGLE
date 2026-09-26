import ai.core.AI;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitTypeTable;
import util.Pair;

/** Deterministic state-dataset generator and full-agent semantic probe. */
public final class EAGLESemanticProbe {
    private static final String STATE_PREFIX = "EAGLE_STATE\t";
    private static final String ACTION_PREFIX = "EAGLE_ACTION\t";
    private static final String[] PHASES = {"early", "mid", "late"};

    private EAGLESemanticProbe() {
    }

    private static final class Snapshot {
        final int cycle;
        final GameState state;

        Snapshot(int cycle, GameState state) {
            this.cycle = cycle;
            this.state = state;
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            throw new IllegalArgumentException("expected generate or evaluate mode");
        }
        if ("generate".equals(args[0])) {
            generate(args);
            return;
        }
        if ("evaluate".equals(args[0])) {
            evaluate(args);
            return;
        }
        throw new IllegalArgumentException("unknown mode: " + args[0]);
    }

    private static void generate(String[] args) throws Exception {
        if (args.length != 10) {
            throw new IllegalArgumentException(
                "generate requires map, output directory, player side, tick limit, three target cycles, and two reference agents"
            );
        }
        String mapPath = args[1];
        File outputDirectory = new File(args[2]);
        int playerSide = Integer.parseInt(args[3]);
        int tickLimit = Integer.parseInt(args[4]);
        int[] targets = {
            Integer.parseInt(args[5]),
            Integer.parseInt(args[6]),
            Integer.parseInt(args[7]),
        };
        if (!(targets[0] < targets[1] && targets[1] < targets[2])) {
            throw new IllegalArgumentException("phase target cycles must be strictly increasing");
        }
        if (!outputDirectory.isDirectory() && !outputDirectory.mkdirs()) {
            throw new IllegalStateException("could not create output directory: " + outputDirectory);
        }

        UnitTypeTable utt = new UnitTypeTable();
        PhysicalGameState physical = PhysicalGameState.load(mapPath, utt);
        if (physical == null || physical.getUnits().isEmpty()) {
            throw new IllegalStateException("map did not load a populated state: " + mapPath);
        }
        GameState state = new GameState(physical, utt);
        AI playerZero = instantiateAgent(args[8], utt);
        AI playerOne = instantiateAgent(args[9], utt);
        playerZero.reset();
        playerOne.reset();

        List<Snapshot> actionable = new ArrayList<>();
        boolean gameOver = false;
        while (!gameOver && state.getTime() <= tickLimit) {
            if (!state.gameover() && state.canExecuteAnyAction(playerSide)) {
                actionable.add(new Snapshot(state.getTime(), state.clone()));
            }
            if (state.getTime() >= tickLimit) {
                break;
            }
            PlayerAction actionZero = playerZero.getAction(0, state);
            PlayerAction actionOne = playerOne.getAction(1, state);
            requireActionOwner(actionZero, 0);
            requireActionOwner(actionOne, 1);
            state.issueSafe(actionZero);
            state.issueSafe(actionOne);
            gameOver = state.cycle();
        }
        if (actionable.size() < PHASES.length) {
            throw new IllegalStateException(
                "reference trajectory produced fewer than three distinct actionable states"
            );
        }

        Snapshot[] chosen = chooseDistinctSnapshots(actionable, targets);
        for (int index = 0; index < PHASES.length; index++) {
            String phase = PHASES[index];
            Snapshot snapshot = chosen[index];
            File stateFile = new File(outputDirectory, phase + ".xml");
            snapshot.state.toxml(stateFile.getAbsolutePath());
            validateReload(stateFile.toPath(), snapshot.state, playerSide);
            String encodedPath = Base64.getEncoder().encodeToString(
                stateFile.getAbsolutePath().getBytes(StandardCharsets.UTF_8)
            );
            System.out.println(
                STATE_PREFIX + phase + "\t" + targets[index] + "\t" + snapshot.cycle + "\t" + encodedPath
            );
        }
    }

    private static AI instantiateAgent(String className, UnitTypeTable utt) throws Exception {
        Class<?> agentClass = Class.forName(className);
        if (!AI.class.isAssignableFrom(agentClass)) {
            throw new IllegalArgumentException("reference class does not implement AI: " + className);
        }
        return (AI) agentClass.getConstructor(UnitTypeTable.class).newInstance(utt);
    }

    private static Snapshot[] chooseDistinctSnapshots(List<Snapshot> snapshots, int[] targets) {
        Snapshot[] chosen = new Snapshot[PHASES.length];
        int exclusiveUpperIndex = snapshots.size();
        for (int phaseIndex = PHASES.length - 1; phaseIndex >= 0; phaseIndex--) {
            int found = -1;
            for (int index = exclusiveUpperIndex - 1; index >= 0; index--) {
                if (snapshots.get(index).cycle <= targets[phaseIndex]) {
                    found = index;
                    break;
                }
            }
            if (found < 0) {
                throw new IllegalStateException(
                    "could not choose distinct actionable state for phase " + PHASES[phaseIndex]
                );
            }
            chosen[phaseIndex] = snapshots.get(found);
            exclusiveUpperIndex = found;
        }
        return chosen;
    }

    private static void validateReload(Path statePath, GameState expected, int playerSide) {
        UnitTypeTable reloadTable = new UnitTypeTable();
        GameState reloaded = GameState.fromXML(statePath.toString(), reloadTable);
        if (reloaded == null) {
            throw new IllegalStateException("GameState.fromXML returned null: " + statePath);
        }
        if (!reloaded.integrityCheck()
                || reloaded.getTime() != expected.getTime()
                || reloaded.getPhysicalGameState().getWidth() != expected.getPhysicalGameState().getWidth()
                || reloaded.getPhysicalGameState().getHeight() != expected.getPhysicalGameState().getHeight()
                || reloaded.getPhysicalGameState().getUnits().size()
                    != expected.getPhysicalGameState().getUnits().size()) {
            throw new IllegalStateException("GameState XML round trip changed core state: " + statePath);
        }
        if (reloaded.gameover() || !reloaded.canExecuteAnyAction(playerSide)) {
            throw new IllegalStateException("probe state is terminal or not actionable: " + statePath);
        }
    }

    private static void evaluate(String[] args) throws Exception {
        if (args.length < 5 || (args.length - 2) % 3 != 0) {
            throw new IllegalArgumentException(
                "evaluate requires candidate class followed by probe-id/state-path/player-side triples"
            );
        }
        Class<?> candidateClass = Class.forName(args[1]);
        if (!AI.class.isAssignableFrom(candidateClass)) {
            throw new IllegalArgumentException("candidate class does not implement AI: " + args[1]);
        }
        for (int offset = 2; offset < args.length; offset += 3) {
            String probeId = args[offset];
            String statePath = args[offset + 1];
            int playerSide = Integer.parseInt(args[offset + 2]);
            UnitTypeTable utt = new UnitTypeTable();
            GameState state = GameState.fromXML(statePath, utt);
            if (state == null || !state.integrityCheck()) {
                throw new IllegalStateException("invalid probe state: " + statePath);
            }
            if (state.gameover() || !state.canExecuteAnyAction(playerSide)) {
                throw new IllegalStateException("probe state is terminal or not actionable: " + statePath);
            }
            AI candidate = (AI) candidateClass.getConstructor(UnitTypeTable.class).newInstance(utt);
            candidate.reset();
            PlayerAction action = candidate.getAction(playerSide, state);
            requireActionOwner(action, playerSide);
            String normalized = normalizeAction(action);
            state.issueSafe(action);
            String encoded = Base64.getEncoder().encodeToString(
                normalized.getBytes(StandardCharsets.UTF_8)
            );
            System.out.println(ACTION_PREFIX + probeId + "\t" + encoded);
        }
    }

    private static void requireActionOwner(PlayerAction action, int playerSide) {
        if (action == null || action.getResourceUsage() == null || !action.integrityCheck()) {
            throw new IllegalStateException("agent returned null or invalid PlayerAction");
        }
        Set<Long> unitIds = new HashSet<>();
        for (Pair<Unit, UnitAction> pair : action.getActions()) {
            if (pair.m_a == null || pair.m_b == null) {
                throw new IllegalStateException("PlayerAction contains a null unit or action");
            }
            if (pair.m_a.getPlayer() != playerSide) {
                throw new IllegalStateException("PlayerAction controls a unit owned by another player");
            }
            if (!unitIds.add(pair.m_a.getID())) {
                throw new IllegalStateException("PlayerAction contains duplicate unit assignments");
            }
        }
    }

    private static String normalizeAction(PlayerAction action) {
        List<Pair<Unit, UnitAction>> pairs = new ArrayList<>(action.getActions());
        pairs.sort(Comparator.comparingLong(pair -> pair.m_a.getID()));
        StringBuilder json = new StringBuilder("[");
        boolean first = true;
        for (Pair<Unit, UnitAction> pair : pairs) {
            if (!first) {
                json.append(',');
            }
            first = false;
            Unit unit = pair.m_a;
            UnitAction unitAction = pair.m_b;
            json.append("{\"unit_id\":").append(unit.getID());
            json.append(",\"unit_x\":").append(unit.getX());
            json.append(",\"unit_y\":").append(unit.getY());
            json.append(",\"type\":").append(unitAction.getType());
            switch (unitAction.getType()) {
                case UnitAction.TYPE_ATTACK_LOCATION:
                    json.append(",\"x\":").append(unitAction.getLocationX());
                    json.append(",\"y\":").append(unitAction.getLocationY());
                    break;
                case UnitAction.TYPE_PRODUCE:
                    json.append(",\"parameter\":").append(unitAction.getDirection());
                    json.append(",\"unit_type\":\"")
                        .append(escapeJson(unitAction.getUnitType().name)).append("\"");
                    break;
                default:
                    json.append(",\"parameter\":").append(unitAction.getDirection());
                    break;
            }
            json.append('}');
        }
        return json.append(']').toString();
    }

    private static String escapeJson(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
