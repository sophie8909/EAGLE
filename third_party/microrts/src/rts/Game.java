package rts;

import ai.core.AI;
import gui.PhysicalGameStatePanel;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.lang.reflect.Constructor;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.swing.JFrame;

import ai.eagle.EAGLE;
import rts.units.Unit;
import rts.units.UnitTypeTable;

/**
 * Class responsible for creating all objects necessary for a single game and
 * run the main loop of the game until completion.
 * @author douglasrizzo
 */
public class Game {

    private UnitTypeTable utt;
    protected rts.GameState gs;
    protected AI ai1, ai2;

    private boolean partiallyObservable, headless;
    private int maxCycles, updateInterval;
    private String resultJsonPath = "";
    private boolean verboseLog = false;

    /**
     * Create a game from a GameSettings object.
     *
     * @param gameSettings a GameSettings object, created either by reading a config file or
     *                     through command-ine arguments
     * @throws Exception when reading the XML file for the map or instantiating AIs from class names
     */
    public Game(GameSettings gameSettings) throws Exception {
        this(new UnitTypeTable(gameSettings.getUTTVersion(),
                        gameSettings.getConflictPolicy()), gameSettings.getMapLocation(),
                gameSettings.isHeadless(),
                gameSettings.isPartiallyObservable(), gameSettings.getMaxCycles(), gameSettings.getUpdateInterval(),
                gameSettings.getAI1(), gameSettings.getAI2(), gameSettings.getResultJsonPath(), gameSettings.isVerboseLog());
    }


    public Game(UnitTypeTable utt, String mapLocation, boolean headless, boolean partiallyObservable, int maxCycles,
                int updateInterval, String ai1, String ai2) throws Exception {
        this(utt, mapLocation, headless, partiallyObservable, maxCycles, updateInterval, ai1, ai2, "", false);
    }

    public Game(UnitTypeTable utt, String mapLocation, boolean headless, boolean partiallyObservable, int maxCycles,
                int updateInterval, String ai1, String ai2, String resultJsonPath, boolean verboseLog) throws Exception {
        this(utt, mapLocation, headless, partiallyObservable, maxCycles, updateInterval);
        this.resultJsonPath = resultJsonPath == null ? "" : resultJsonPath;
        this.verboseLog = verboseLog;

        Constructor cons1 = Class.forName(ai1)
                .getConstructor(UnitTypeTable.class);
        Constructor cons2 = Class.forName(ai2)
                .getConstructor(UnitTypeTable.class);



        this.ai1 = (AI) cons1.newInstance(utt);
        this.ai2 = (AI) cons2.newInstance(utt);
        System.out.println(" -->in Game rts gmu3r2g 43    "+(AI) cons1.newInstance(utt));
        System.out.println(" -->in Game rts gmu3r2g 54    "+(AI) cons2.newInstance(utt));
        System.out.println(" ai1 --> "+this.ai1);
        System.out.println(" ai1 --> "+this.ai2);
    }

    public Game(UnitTypeTable utt, String mapLocation, boolean headless, boolean partiallyObservable, int maxCycles,
                int updateInterval, AI ai1, AI ai2) throws Exception {
        this(utt, mapLocation, headless, partiallyObservable, maxCycles, updateInterval);

        this.ai1 = ai1;
        this.ai2 = ai2;
        System.out.println(" ai1 --> "+this.ai1);
        System.out.println(" ai1 --> "+this.ai2);
    }

    private Game(UnitTypeTable utt, String mapLocation, boolean headless, boolean partiallyObservable, int maxCycles,
                 int updateInterval) throws Exception {

        this.utt = utt;
        PhysicalGameState pgs = PhysicalGameState.load(mapLocation, utt);

        gs = new GameState(pgs, utt);
        this.partiallyObservable = partiallyObservable;
        this.headless = headless;
        this.maxCycles = maxCycles;
        this.updateInterval = updateInterval;

        System.out.println(" maxCycles --> "+maxCycles);
        System.out.println(" headless --> "+headless);
        System.out.println(" updateInterval --> "+updateInterval);
        System.out.println(" partiallyObservable --> "+partiallyObservable);



    }

    /**
     * Create a game from a GameSettings object, but also receiving AI players as parameters
     * @param gameSettings a GameSettings object, created either by reading a config file or
     *                     through command-ine arguments
     * @param player_one AI for player one
     * @param player_two AI for player two
     * @throws Exception when reading the XML file for the map
     */
    public Game(GameSettings gameSettings, AI player_one, AI player_two)
        throws Exception {
        UnitTypeTable utt = new UnitTypeTable(gameSettings.getUTTVersion(),
            gameSettings.getConflictPolicy());
        PhysicalGameState pgs = PhysicalGameState.load(gameSettings.getMapLocation(), utt);

        gs = new GameState(pgs, utt);

        partiallyObservable = gameSettings.isPartiallyObservable();
        headless = gameSettings.isHeadless();
        maxCycles = gameSettings.getMaxCycles();
        updateInterval = gameSettings.getUpdateInterval();

        ai1 = player_one;
        ai2 = player_two;

        System.out.println(" ai1 --> "+ai1);
        System.out.println(" ai2 --> "+ai2);
        System.out.println(" player_one --> "+player_one);
        System.out.println(" player_two --> "+player_two);
        System.out.println("  partiallyObservable --> "+partiallyObservable);
        System.out.println(" headless --> "+headless);
        System.out.println(" maxCycles --> "+maxCycles);

    }

    /**
     * run the main loop of the game
     * @throws Exception
     */
    public void start() throws Exception {
        // Setup UI
        JFrame w = headless ? null : PhysicalGameStatePanel
            .newVisualizer(gs, 640, 640, false, PhysicalGameStatePanel.COLORSCHEME_BLACK);

        start(w);
    }

    /**
     * run the main loop of the game
     * @param w a window where the game will be displayed
     * @throws Exception
     */
    public void start(JFrame w) throws Exception {
        // Reset all players
        ai1.reset();
        ai2.reset();

        // pre-game analysis
        ai1.preGameAnalysis(gs, 0);
        ai2.preGameAnalysis(gs, 0);

        boolean gameover = false;
        String tracePath = System.getProperty("microrts.trace.path", "").trim();
        String roundStateDirPath = System.getProperty("microrts.round_state_dir", "").trim();
        Trace trace = tracePath.isEmpty() ? null : new Trace(utt);

        while (!gameover && gs.getTime() < maxCycles) {
            long timeToNextUpdate = System.currentTimeMillis() + updateInterval;

            rts.GameState playerOneGameState =
                    partiallyObservable ? new PartiallyObservableGameState(gs, 0) : gs;
            rts.GameState playerTwoGameState =
                    partiallyObservable ? new PartiallyObservableGameState(gs, 1) : gs;

            // Game waits for both AIs to respond - this is naturally fair
            // If an AI takes 5 seconds, the game just runs slower, not unfairly
            rts.PlayerAction pa1 = ai1.getAction(0, playerOneGameState);
            rts.PlayerAction pa2 = ai2.getAction(1, playerTwoGameState);
            if (trace != null) {
                TraceEntry entry = new TraceEntry(gs.getPhysicalGameState().cloneIncludingTerrain(), gs.getTime());
                entry.addPlayerAction(pa1);
                entry.addPlayerAction(pa2);
                trace.addEntry(entry);
            }
            gs.issueSafe(pa1);
            gs.issueSafe(pa2);

            // simulate
            gameover = gs.cycle();
            writeRoundStateSnapshot(roundStateDirPath, gs.getTime(), gameover);

            // if not headless mode, wait and repaint the window
            if (w != null) {
                if (!w.isVisible())
                    break;

                // only wait if the AIs have not already consumed more time than the predetermined interval
                long waitTime = timeToNextUpdate - System.currentTimeMillis();
                if (waitTime >=0) {
                    try {
                        Thread.sleep(waitTime);
                    } catch (Exception e) {
                        e.printStackTrace();
                    }
                }

                // repaint the window after (or regardless of) wait time
                w.repaint();
            }
        }
        ai1.gameOver(gs.winner());
        ai2.gameOver(gs.winner());

        // Print clear game result for benchmark parsing
        int winner = gs.winner();
        int finalTick = gs.getTime();
        boolean tickTimeout = !gameover && finalTick >= maxCycles;
        writeResultJson(resultJsonPath, gameover, winner, finalTick, tickTimeout);
        if (verboseLog) {
            printFinalStateSnapshot(finalTick);
            System.out.println();
            System.out.println("=== GAME RESULT ===");
            System.out.println("FINAL_TICK: " + finalTick);
            System.out.println("WINNER: " + winner);
            if (winner == 0) {
                System.out.println("Player 0 wins!");
            } else if (winner == 1) {
                System.out.println("Player 1 wins!");
            } else {
                System.out.println("Draw (no winner)");
            }
            System.out.println("===================");
        }
        if (trace != null) {
            trace.toxml(tracePath);
            System.out.println("[MicroRTS] saved trace: " + tracePath);
        }

        System.out.flush();
        System.err.flush();

        if (w != null) {
            w.setVisible(false);
            w.dispose();
        }

        String forceExit = System.getenv("EAGLE_FORCE_EXIT_ON_GAME_OVER");
        if ("1".equals(forceExit)) {
            System.exit(0);
        }
    }

    private void writeResultJson(String path, boolean gameover, int winner, int finalTick, boolean tickTimeout) {
        if (path == null || path.isEmpty()) {
            return;
        }
        Path resultPath = Paths.get(path);
        Path tmpPath = Paths.get(path + ".tmp");
        try {
            Path parent = resultPath.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            String content = buildResultJson(gameover, winner, finalTick, tickTimeout);
            Files.write(tmpPath, content.getBytes(StandardCharsets.UTF_8));
            try {
                Files.move(tmpPath, resultPath, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            } catch (java.nio.file.AtomicMoveNotSupportedException e) {
                Files.move(tmpPath, resultPath, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException e) {
            System.err.println("[MicroRTS] failed to write result JSON: " + e.getMessage());
        }
    }

    private String buildResultJson(boolean gameover, int winner, int finalTick, boolean tickTimeout) {
        ResourceSnapshot p0 = buildPlayerSnapshot(0);
        ResourceSnapshot p1 = buildPlayerSnapshot(1);
        StringBuilder json = new StringBuilder();
        json.append("{\n");
        appendJsonField(json, "gameover", String.valueOf(gameover), true);
        appendJsonField(json, "winner", String.valueOf(winner), true);
        appendJsonField(json, "result", quote(resultLabel(winner, tickTimeout)), true);
        appendJsonField(json, "target_side", "0", true);
        appendJsonField(json, "final_tick", String.valueOf(finalTick), true);
        appendJsonField(json, "max_cycles", String.valueOf(maxCycles), true);
        appendJsonField(json, "tick_timeout", String.valueOf(tickTimeout), true);
        appendJsonField(json, "termination_reason", quote(tickTimeout ? "tick_timeout" : gameover ? "gameover" : "stopped"), true);
        appendJsonField(json, "ai1", quote(ai1.getClass().getName()), true);
        appendJsonField(json, "ai2", quote(ai2.getClass().getName()), true);
        appendJsonField(json, "llm_calls", String.valueOf(llmCallCount(ai1)), true);
        appendJsonField(json, "llm_call_limit", String.valueOf(llmCallLimit(ai1)), true);
        appendJsonField(json, "llm_call_limit_reached", String.valueOf(llmCallLimitReached(ai1)), true);
        json.append("  \"players\": {\n");
        json.append("    \"p0\": ").append(snapshotJson(p0)).append(",\n");
        json.append("    \"p1\": ").append(snapshotJson(p1)).append("\n");
        json.append("  },\n");
        json.append("  \"ally\": ").append(snapshotJson(p0)).append(",\n");
        json.append("  \"enemy\": ").append(snapshotJson(p1)).append(",\n");
        json.append("  \"final_scoreboard\": {")
                .append("\"time\":").append(finalTick).append(",")
                .append("\"p0_units\":").append(p0.unitCount).append(",")
                .append("\"p1_units\":").append(p1.unitCount).append(",")
                .append("\"p0_eval\":").append(p0.materialTotal).append(",")
                .append("\"p1_eval\":").append(p1.materialTotal)
                .append("}\n");
        json.append("}\n");
        return json.toString();
    }

    private ResourceSnapshot buildPlayerSnapshot(int player) {
        ResourceSnapshot snapshot = new ResourceSnapshot(gs.getPlayer(player).getResources());
        for (Unit unit : gs.getPhysicalGameState().getUnits()) {
            if (unit.getPlayer() != player) {
                continue;
            }
            snapshot.unitCount++;
            snapshot.carriedResources += unit.getResources();
            String typeName = unit.getType().name;
            snapshot.unitTypes.put(typeName, snapshot.unitTypes.getOrDefault(typeName, 0) + 1);
            snapshot.materialTotal += unit.getType().cost;
        }
        snapshot.resourceTotal = snapshot.playerResources + snapshot.carriedResources;
        return snapshot;
    }

    private String resultLabel(int winner, boolean tickTimeout) {
        if (winner == 0) {
            return "p0_win";
        }
        if (winner == 1) {
            return "p1_win";
        }
        return tickTimeout ? "timeout_draw" : "draw";
    }

    private int llmCallCount(AI ai) {
        return ai instanceof EAGLE ? ((EAGLE) ai).getLlmCallCount() : 0;
    }

    private int llmCallLimit(AI ai) {
        return ai instanceof EAGLE ? ((EAGLE) ai).getLlmCallLimit() : 0;
    }

    private boolean llmCallLimitReached(AI ai) {
        return ai instanceof EAGLE && ((EAGLE) ai).hasLlmCallLimitReached();
    }

    private String snapshotJson(ResourceSnapshot snapshot) {
        StringBuilder json = new StringBuilder();
        json.append("{");
        json.append("\"unit_count\":").append(snapshot.unitCount).append(",");
        json.append("\"player_resources\":").append(snapshot.playerResources).append(",");
        json.append("\"carried_resources\":").append(snapshot.carriedResources).append(",");
        json.append("\"resource_total\":").append(snapshot.resourceTotal).append(",");
        json.append("\"material_total\":").append(snapshot.materialTotal).append(",");
        json.append("\"unit_types\":{");
        boolean first = true;
        for (Map.Entry<String, Integer> entry : snapshot.unitTypes.entrySet()) {
            if (!first) {
                json.append(",");
            }
            json.append(quote(entry.getKey())).append(":").append(entry.getValue());
            first = false;
        }
        json.append("}}");
        return json.toString();
    }

    private void appendJsonField(StringBuilder json, String name, String value, boolean comma) {
        json.append("  ").append(quote(name)).append(": ").append(value);
        if (comma) {
            json.append(",");
        }
        json.append("\n");
    }

    private String quote(String value) {
        String escaped = value == null ? "" : value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r");
        return "\"" + escaped + "\"";
    }

    private static class ResourceSnapshot {
        final int playerResources;
        int unitCount = 0;
        int carriedResources = 0;
        int resourceTotal = 0;
        int materialTotal = 0;
        final Map<String, Integer> unitTypes = new LinkedHashMap<>();

        ResourceSnapshot(int playerResources) {
            this.playerResources = playerResources;
        }
    }

    private void printFinalStateSnapshot(int finalTick) {
        System.out.print(renderStateSnapshot(finalTick));
    }

    private void writeRoundStateSnapshot(String roundStateDirPath, int tick, boolean gameover) {
        if (roundStateDirPath == null || roundStateDirPath.isEmpty()) {
            return;
        }
        try {
            Path roundStateDir = Paths.get(roundStateDirPath);
            Files.createDirectories(roundStateDir);
            String fileName = String.format("round_%06d.log", tick);
            StringBuilder content = new StringBuilder();
            content.append("ROUND_TICK: ").append(tick).append('\n');
            content.append("GAMEOVER: ").append(gameover).append('\n');
            content.append(renderStateSnapshot(tick));
            Files.write(roundStateDir.resolve(fileName), content.toString().getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            System.err.println("[MicroRTS] failed to write round state snapshot: " + e.getMessage());
        }
    }

    private String renderStateSnapshot(int tick) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        StringBuilder content = new StringBuilder();
        content.append(
            "current time " + tick
            + " p0 player 0(" + gs.getPlayer(0).getResources() + ")"
            + " p1 player 1(" + gs.getPlayer(1).getResources() + ")"
        ).append('\n');
        content.append("=== Dynamic Prompt ===\n");
        content.append("Map size: ").append(pgs.getWidth()).append('x').append(pgs.getHeight()).append('\n');
        content.append("Turn: ").append(tick).append('/').append(maxCycles).append('\n');
        content.append("Feature locations:\n");
        for (Unit unit : pgs.getUnits()) {
            content.append(renderFeatureLine(unit)).append('\n');
        }
        content.append("======================\n");
        return content.toString();
    }

    private String renderFeatureLine(Unit unit) {
        String team = unit.getPlayer() == 0 ? "Ally" : unit.getPlayer() == 1 ? "Enemy" : "Neutral";
        String unitLabel = featureUnitLabel(unit);
        String details = "{HP=" + unit.getHitPoints() + ", resources=" + unit.getResources() + "}";
        return "(" + unit.getX() + "," + unit.getY() + ") " + team + " " + unitLabel + " " + details;
    }

    private String featureUnitLabel(Unit unit) {
        String name = unit.getType().name;
        if ("Resource".equalsIgnoreCase(name)) return "Resource Node";
        if ("Base".equalsIgnoreCase(name)) return "Base Unit";
        if ("Barracks".equalsIgnoreCase(name)) return "Barracks Unit";
        if ("Worker".equalsIgnoreCase(name)) return "Worker Unit";
        if ("Light".equalsIgnoreCase(name)) return "Light Unit";
        if ("Heavy".equalsIgnoreCase(name)) return "Heavy Unit";
        if ("Ranged".equalsIgnoreCase(name)) return "Ranged Unit";
        return name + " Unit";
    }
}
