package ai.abstraction;

import ai.abstraction.pathfinding.AStarPathFinding;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.AI;
import ai.core.ParameterSpecification;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import gui.PhysicalGameStatePanel;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.LinkedList;
import java.util.List;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.PlayerAction;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;

/**
 * Reusable fixed-template eaglePolicy agent driven by an injected policy spec.
 * The Python eaglePolicy pipeline rewrites only the injected spec/prompt blocks,
 * while the execution logic below stays stable.
 */
public class eaglePolicy extends AbstractionLayerAI {

    protected UnitTypeTable utt;
    UnitType workerType;
    UnitType lightType;
    UnitType heavyType;
    UnitType rangedType;
    UnitType baseType;
    UnitType barracksType;

    // EAGLE_POLICY_SPEC_START
    private static final boolean INJECTED_STRATEGY_ENABLED = true;
    private static final int WORKER_TARGET_BEFORE_BARRACKS = 3;
    private static final int WORKER_TARGET_AFTER_BARRACKS = 4;
    private static final int HARVESTER_TARGET = 3;
    private static final int DESIRED_BARRACKS = 1;
    private static final boolean WORKER_HARASS_ENABLED = false;
    private static final boolean ATTACK_WORKERS_FIRST = false;
    private static final boolean ATTACK_STRUCTURES_FIRST = false;
    private static final boolean PROTECT_BARRACKS = true;
    private static final int MIN_LIGHTS = 2;
    private static final int MIN_RANGED = 0;
    private static final int MIN_HEAVIES = 0;
    private static final String[] PRODUCTION_PRIORITY = {
        "Light",
        "Light",
        "Ranged"
    };
    // EAGLE_POLICY_SPEC_END

    // EAGLE_POLICY_PROMPT_START
    private static final String[] EMBEDDED_PROMPT_LINES = {
        "You are an AI agent playing a real-time strategy game.",
        "You control ALL Ally units and must decide actions each step.",
        "Your goal is to maximize win probability by making valid and effective decisions.",
        "Always follow the rules and output the required JSON format.",
        "GAME RULES:",
        "Two players: Ally vs Enemy.",
        "Goal: destroy all enemy units and buildings.",
        "Only control Ally units.",
        "Each unit can take ONE action.",
        "Only available units can receive commands.",
        "UNIT TYPES:",
        "worker:",
        "- hp=1 cost=1 dmg=1 range=1 speed=1",
        "- can: move, harvest, build(base|barracks), attack, idle",
        "- trained_by: base",
        "light:",
        "- hp=4 cost=2 dmg=2 range=1 speed=2",
        "- can: move, attack, idle",
        "- trained_by: barracks",
        "heavy:",
        "- hp=8 cost=3 dmg=4 range=1 speed=1",
        "- can: move, attack, idle",
        "- trained_by: barracks",
        "ranged:",
        "- hp=3 cost=2 dmg=1 range=3 speed=1",
        "- can: move, attack, idle",
        "- trained_by: barracks",
        "BUILDING TYPES:",
        "base:",
        "- hp=10 cost=10",
        "- train: worker",
        "- stores: resources",
        "barracks:",
        "- hp=5 cost=5",
        "- train: light, heavy, ranged",
        "GAME STATE:",
        "Map size given.",
        "Coordinates are zero-indexed.",
        "Units/buildings include:",
        "- hp, resources, current_action, available",
        "available=true means controllable.",
        "RAW MOVE FORMAT:",
        "(x,y): unit_type action(args)",
        "unit_type: worker, light, heavy, ranged, base, barracks",
        "ACTIONS:",
        "move((x,y))",
        "train(unit_type)",
        "build((x,y),building_type)",
        "harvest((resource_x,resource_y),(base_x,base_y))",
        "attack((enemy_x,enemy_y))",
        "idle()",
        "OUTPUT JSON:",
        "{",
        "  \"thinking\": \"short reasoning\",",
        "  \"moves\": [",
        "    {",
        "      \"raw_move\": \"(x,y): unit action(args)\",",
        "      \"unit_position\": [x,y],",
        "      \"unit_type\": \"worker\",",
        "      \"action_type\": \"harvest\"",
        "    }",
        "  ]",
        "}",
        "REQUIREMENTS:",
        "- unit_position must match an Ally unit",
        "- unit_type must be valid",
        "- action_type: move, train, build, harvest, attack, idle",
        "- raw_move must match the action",
        "{\"raw_move\":\"(1,1): worker harvest((0,0),(2,1))\",\"unit_position\":[1,1],\"unit_type\":\"worker\",\"action_type\":\"harvest\"}",
        "{\"raw_move\":\"(2,1): base train(worker)\",\"unit_position\":[2,1],\"unit_type\":\"base\",\"action_type\":\"train\"}",
        "{\"raw_move\":\"(1,1): worker build((3,3),barracks)\",\"unit_position\":[1,1],\"unit_type\":\"worker\",\"action_type\":\"build\"}",
        "phase_transition_rule: Continuously adapt phase boundaries based on state-based conditions over rigid turn thresholds, integrating early/mid/late game plans according to high-octane blitzkrieg strategy_identity, while balancing economic pressure with fluid unit deployment.",
        "EARLY GAME PLAN:",
        "Prioritize swift economy disruption through surprise attacks on key infrastructure such as harvesting paths and unfinished buildings. Target exposed enemy workers to disrupt supply chains and force the opponent to react. Maintain a robust forward presence while minimizing idle resources at home to facilitate unit flow, forcing the opponent into reactive measures. Leverage early-game momentum by adapting state-based conditions over rigid turn thresholds, sustaining continuous pressure with minimal waiting.",
        "MID GAME PLAN:",
        "Sustain relentless aggression by targeting key infrastructure such as workers, unfinished buildings, and harvesting paths, leveraging early-game momentum to dictate tempo effectively through continuous pressure with minimal waiting.",
        "Continuously adapt state-based conditions over rigid turn thresholds to apply early/mid game plan adaptations in harmony with high-octane blitzkrieg strategy_identity, forcing the opponent into reactive measures that disrupt economic stabilization and outscaling.",
        "LATE GAME PLAN:",
        "In late-game situations where economies have been severely disrupted or structure counts are heavily damaged, focus on relentless economic disruption to rapidly accumulate pressure against key targets and force decisive engagement.",
        "Coordinated attacks should converge on high-priority systems and infrastructure, overwhelming defenses and accelerating the collapse of the enemy system through swift economy disruption and sustained aggression.",
        "During a base race scenario, prioritize decisive engagement over passive preservation of minimum required structures, leveraging momentum from early and mid-game efforts to dictate tempo effectively.",
        "DECISION PRIORITY:",
        "1. Prioritize swift economy disruption by targeting key infrastructure such as workers, unfinished buildings, and harvesting paths to force decisive engagement and rapid game conclusion.",
        "2. Continuously apply early/mid game plan if it still aligns with state-based conditions over rigid turn thresholds, adapting phase plans and decision priority to maintain a dynamic balance between economy disruption and unit flow.",
        "3. Maintain relentless aggression and continuous pressure on the enemy's economic resources by targeting exposed enemy units and key infrastructure, forcing them into reactive measures that disrupt their development or seize initiative.",
        "4. Focus on prioritizing high-priority targets with maximum impact, such as enemy workers and key infrastructure, to rapidly accumulate pressure against strategic targets.",
        "5. Continuously prioritize action over resource conservation, maintaining relentless aggression through swift economy disruption and continuous pressure until the opponent's economy is severely disrupted or their structure counts are heavily damaged.",
        "ANTI-STALL RULES:",
        "Do not move units back and forth without improving attack range, defense coverage, harvesting flow, or build access.",
        "If an offensive move has started and the fight is still favorable, continue pressure instead of stuttering outside contact.",
        "If a defensive hold succeeds, transition back into harvesting, production, or counterpressure instead of waiting idly."
    };
    // EAGLE_POLICY_PROMPT_END

    private static final double P_FAIL_WORKER = 0.0;
    private static final double P_FAIL_BUILD = 0.0;
    private static final double P_FAIL_TRAIN = 0.0;
    private static final double P_FAIL_COMBAT = 0.0;
    private static final int ATTACK_RADIUS_LIMIT = 5;
    private static final int TARGET_TOP_K = 3;

    private String turnLogFileName;
    private String responseCsvFileName;
    private boolean logsInitialized = false;
    private boolean endGameMetricsLogged = false;
    private final StringBuilder moveLogBuffer = new StringBuilder();

    public eaglePolicy(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());
    }

    public eaglePolicy(UnitTypeTable a_utt, PathFinding a_pf) {
        super(a_pf);
        reset(a_utt);
    }

    public void reset() {
        super.reset();
    }

    public void reset(UnitTypeTable a_utt) {
        utt = a_utt;
        workerType = utt.getUnitType("Worker");
        lightType = utt.getUnitType("Light");
        heavyType = utt.getUnitType("Heavy");
        rangedType = utt.getUnitType("Ranged");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
    }

    @Override
    public AI clone() {
        return new eaglePolicy(utt, pf);
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }

    protected StrategySpec buildStrategySpec() {
        StrategySpec spec = new StrategySpec();
        spec.enabled = INJECTED_STRATEGY_ENABLED;
        spec.workerTargetBeforeBarracks = WORKER_TARGET_BEFORE_BARRACKS;
        spec.workerTargetAfterBarracks = WORKER_TARGET_AFTER_BARRACKS;
        spec.harvesterTarget = HARVESTER_TARGET;
        spec.desiredBarracks = DESIRED_BARRACKS;
        spec.workerHarassEnabled = WORKER_HARASS_ENABLED;
        spec.attackWorkersFirst = ATTACK_WORKERS_FIRST;
        spec.attackStructuresFirst = ATTACK_STRUCTURES_FIRST;
        spec.protectBarracks = PROTECT_BARRACKS;
        spec.minLights = MIN_LIGHTS;
        spec.minRanged = MIN_RANGED;
        spec.minHeavies = MIN_HEAVIES;
        spec.productionPriority = resolveProductionPriority(PRODUCTION_PRIORITY);
        return spec;
    }

    protected boolean hasInjectedStrategy() {
        return INJECTED_STRATEGY_ENABLED;
    }

    private void initLogsIfNeeded() {
        if (!logsInitialized) {
            String ts = new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss").format(new Date());
            try {
                turnLogFileName = resolveMicrortsLogFilePath("run_" + ts + "_eaglePolicy.log").toString();
                responseCsvFileName = resolveResponseFilePath("Response" + ts + "_eaglePolicy.csv").toString();
                initializeResponseCsv(responseCsvFileName);
            } catch (IOException e) {
                throw new RuntimeException("Failed to initialize eaglePolicy log path.", e);
            }
            logsInitialized = true;
        }
    }

    private static Path resolveProjectRoot() {
        Path current = Paths.get("").toAbsolutePath().normalize();
        while (current != null) {
            if (Files.exists(current.resolve("third_party").resolve("microrts"))) {
                return current;
            }
            if ("microrts".equals(current.getFileName().toString())
                    && current.getParent() != null
                    && "third_party".equals(current.getParent().getFileName().toString())
                    && current.getParent().getParent() != null) {
                return current.getParent().getParent();
            }
            current = current.getParent();
        }
        return Paths.get("").toAbsolutePath().normalize();
    }

    private static Path resolveMicrortsLogsDirectory() throws IOException {
        Path projectRoot = resolveProjectRoot();
        Path logsDir = projectRoot.resolve("logs").resolve("microrts");
        Files.createDirectories(logsDir);
        return logsDir;
    }

    private static Path resolveMicrortsLogFilePath(String filename) throws IOException {
        return resolveMicrortsLogsDirectory().resolve(filename);
    }

    private static Path resolveResponseLogsDirectory() throws IOException {
        Path projectRoot = resolveProjectRoot();
        Path logsDir = projectRoot.resolve("logs").resolve("responses");
        Files.createDirectories(logsDir);
        return logsDir;
    }

    private static Path resolveResponseFilePath(String filename) throws IOException {
        return resolveResponseLogsDirectory().resolve(filename);
    }

    private void appendTurnLog(String text) {
        try (FileWriter fw = new FileWriter(turnLogFileName, true)) {
            fw.write(text);
            fw.write(System.lineSeparator());
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    private static void initializeResponseCsv(String filename) throws IOException {
        try (FileWriter writer = new FileWriter(filename)) {
            writer.append("Thinking,Moves,Feature locations,Request Time, Request / Prompt Tokens, response Time, Response Tokens, Latency(milliseconds),Total Tokens,Score_in_every_run\n");
        }
    }

    private static String escapeForCSV(String value) {
        if (value == null) {
            return "\"\"";
        }
        return "\"" + value.replace("\"", "\"\"") + "\"";
    }

    private static String extractFeatureArray(String dynamicPrompt) {
        String[] lines = dynamicPrompt.split("\\R");
        return Arrays.stream(lines)
            .map(line -> "\"" + line.replace("\"", "\\\"") + "\"")
            .reduce((left, right) -> left + ", " + right)
            .map(joined -> "[" + joined + "]")
            .orElse("[]");
    }

    private void appendResponseCsv(String thinking, String moves, String dynamicPrompt, String scoreSnapshot) {
        try (FileWriter writer = new FileWriter(responseCsvFileName, true)) {
            writer.append(escapeForCSV(thinking)).append(",")
                .append(escapeForCSV(moves)).append(",")
                .append(escapeForCSV(extractFeatureArray(dynamicPrompt))).append(",")
                .append(escapeForCSV("N/A")).append(",")
                .append("0,")
                .append(escapeForCSV("N/A")).append(",")
                .append("0,")
                .append("0,")
                .append("0,")
                .append(escapeForCSV(scoreSnapshot))
                .append("\n");
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    private void logEndGameMetrics(GameState gs, int player) {
        if (endGameMetricsLogged) {
            return;
        }

        JsonObject playerStats = new JsonObject();
        playerStats.addProperty("player_id", player);
        playerStats.addProperty("resources", gs.getPlayer(player).getResources());
        playerStats.addProperty("winner", gs.winner());
        playerStats.addProperty("game_over", gs.gameover());

        JsonObject gameMetrics = new JsonObject();
        gameMetrics.addProperty("turn", gs.getTime());
        gameMetrics.addProperty("score_snapshot", PhysicalGameStatePanel.info1);
        gameMetrics.addProperty("response_csv", responseCsvFileName);
        gameMetrics.addProperty("turn_log", turnLogFileName);

        JsonObject wrapper = new JsonObject();
        wrapper.addProperty("agent_type", "eaglePolicy");
        wrapper.addProperty("agent_name", getClass().getSimpleName());
        wrapper.add("player_final_stats", playerStats);
        wrapper.add("game_metrics", gameMetrics);
        wrapper.addProperty(
            "end_time",
            java.time.LocalDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS"))
        );

        try (FileWriter writer = new FileWriter(resolveResponseFilePath("game_summary_eaglePolicy.json").toString(), true)) {
            writer.write(new GsonBuilder().setPrettyPrinting().create().toJson(wrapper));
            writer.write(System.lineSeparator());
        } catch (IOException e) {
            e.printStackTrace();
        }
        endGameMetricsLogged = true;
    }

    private void logMove(String status, Unit unit, String action, String target) {
        moveLogBuffer.append("[")
            .append(status)
            .append("] ")
            .append(unit.getType().name)
            .append(" @(")
            .append(unit.getX())
            .append(",")
            .append(unit.getY())
            .append(")")
            .append(" -> ")
            .append(action);

        if (target != null && !target.isEmpty()) {
            moveLogBuffer.append(" ").append(target);
        }

        moveLogBuffer.append("\n");
    }

    private boolean shouldSkip(double probability) {
        return false;
    }

    private String formatPosition(int x, int y) {
        return "@(" + x + "," + y + ")";
    }

    private Build getCurrentBuild(Unit unit, UnitType expectedType) {
        AbstractAction action = getAbstractAction(unit);
        if (action instanceof Build && ((Build) action).type == expectedType) {
            return (Build) action;
        }
        return null;
    }

    private String unitActionToString(UnitAction action) {
        if (action == null) {
            return "idling";
        }

        String text;
        switch (action.getType()) {
            case UnitAction.TYPE_NONE:
                text = "idling";
                break;
            case UnitAction.TYPE_MOVE:
                text = String.format("moving to (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_HARVEST:
                text = String.format("harvesting from (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_RETURN:
                text = String.format("returning resources to (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_PRODUCE:
                text = String.format("producing unit at (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_ATTACK_LOCATION:
                text = String.format("attacking location (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            default:
                text = "unknown action";
                break;
        }
        return text;
    }

    private String buildDynamicPromptLikeEAGLE(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        int width = pgs.getWidth();
        int height = pgs.getHeight();
        Player currentPlayer = gs.getPlayer(player);
        List<String> features = new ArrayList<>();
        int maxActions = 0;

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player) {
                maxActions++;
            }

            UnitAction action = gs.getUnitAction(u);
            String actionText = unitActionToString(action);

            String typeLabel;
            String details;
            if (u.getType().isResource) {
                typeLabel = "Resource Node";
                details = "{resources=" + u.getResources() + "}";
            } else if (u.getType() == baseType) {
                typeLabel = "Base Unit";
                details = "{resources=" + currentPlayer.getResources()
                    + ", current_action=\"" + actionText + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == barracksType) {
                typeLabel = "Barracks Unit";
                details = "{current_action=\"" + actionText + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == workerType) {
                typeLabel = "Worker Unit";
                details = "{current_action=\"" + actionText + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == lightType) {
                typeLabel = "Light Unit";
                details = "{current_action=\"" + actionText + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == heavyType) {
                typeLabel = "Heavy Unit";
                details = "{current_action=\"" + actionText + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == rangedType) {
                typeLabel = "Ranged Unit";
                details = "{current_action=\"" + actionText + "\", HP=" + u.getHitPoints() + "}";
            } else {
                typeLabel = "Unknown";
                details = "{}";
            }

            String owner = u.getPlayer() == player ? "Ally" : (u.getType().isResource ? "Neutral" : "Enemy");
            String pos = "(" + u.getX() + ", " + u.getY() + ")";
            features.add(pos + " " + owner + " " + typeLabel + " " + details);
        }

        String mapSize = "Map size: " + width + "x" + height;
        String turn = "Turn: " + gs.getTime() + "/5000";
        String maxActionsText = "Max actions: " + maxActions;
        String featureBlock = "Feature locations:\n" + String.join("\n", features);

        return mapSize + "\n" + turn + "\n" + maxActionsText + "\n\n" + featureBlock + "\n";
    }

    private void appendStrategySection(StringBuilder rawLog, StrategySpec spec) {
        rawLog.append("=== eaglePolicy Strategy ===\n");
        rawLog.append("enabled=").append(spec.enabled).append("\n");
        rawLog.append("workerTargetBeforeBarracks=").append(spec.workerTargetBeforeBarracks).append("\n");
        rawLog.append("workerTargetAfterBarracks=").append(spec.workerTargetAfterBarracks).append("\n");
        rawLog.append("harvesterTarget=").append(spec.harvesterTarget).append("\n");
        rawLog.append("desiredBarracks=").append(spec.desiredBarracks).append("\n");
        rawLog.append("workerHarassEnabled=").append(spec.workerHarassEnabled).append("\n");
        rawLog.append("attackWorkersFirst=").append(spec.attackWorkersFirst).append("\n");
        rawLog.append("attackStructuresFirst=").append(spec.attackStructuresFirst).append("\n");
        rawLog.append("protectBarracks=").append(spec.protectBarracks).append("\n");
        rawLog.append("minLights=").append(spec.minLights).append("\n");
        rawLog.append("minRanged=").append(spec.minRanged).append("\n");
        rawLog.append("minHeavies=").append(spec.minHeavies).append("\n");
        rawLog.append("productionPriority=");
        if (spec.productionPriority == null) {
            rawLog.append("null\n");
        } else {
            rawLog.append("[");
            for (int i = 0; i < spec.productionPriority.length; i++) {
                if (i > 0) {
                    rawLog.append(", ");
                }
                UnitType t = spec.productionPriority[i];
                rawLog.append(t == null ? "null" : t.name);
            }
            rawLog.append("]\n");
        }
        rawLog.append("P_FAIL_WORKER=").append(P_FAIL_WORKER).append("\n");
        rawLog.append("P_FAIL_BUILD=").append(P_FAIL_BUILD).append("\n");
        rawLog.append("P_FAIL_TRAIN=").append(P_FAIL_TRAIN).append("\n");
        rawLog.append("P_FAIL_COMBAT=").append(P_FAIL_COMBAT).append("\n");
        rawLog.append("ATTACK_RADIUS_LIMIT=").append(ATTACK_RADIUS_LIMIT).append("\n");
        rawLog.append("TARGET_TOP_K=").append(TARGET_TOP_K).append("\n");
        rawLog.append("========================\n");
    }

    protected void logStateSnapshot(int player, GameState gs) {
        Player p0 = gs.getPlayer(0);
        Player p1 = gs.getPlayer(1);
        int currentTime = gs.getTime();

        System.out.println("gs.gameover() = " + gs.gameover());
        System.out.println("Running getAction for Player: " + player);
        System.out.println(" current time " + currentTime + " p0 " + p0 + " p1 " + p1);
        System.out.printf(
            "T: %d, P0: %d (%s), P1: %d (%s)%n",
            currentTime,
            p0.getID(), p0.getResources(),
            p1.getID(), p1.getResources()
        );
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        initLogsIfNeeded();
        moveLogBuffer.setLength(0);

        StringBuilder rawLog = new StringBuilder();
        rawLog.append("=== Turn ").append(gs.getTime()).append(" ===\n");
        String dynamicPrompt = buildDynamicPromptLikeEAGLE(player, gs);
        rawLog.append("=== Dynamic Prompt ===\n");
        rawLog.append(dynamicPrompt);
        rawLog.append("========================\n");

        if (!hasInjectedStrategy()) {
            logStateSnapshot(player, gs);
            PlayerAction pa = translateActions(player, gs);

            rawLog.append("=== eaglePolicy Strategy ===\n");
            rawLog.append("Injected strategy disabled\n");
            rawLog.append("========================\n");
            rawLog.append("=== Applied Moves ===\n");
            rawLog.append("(none)\n");
            rawLog.append("========================\n");
            rawLog.append("=== Final PlayerAction ===\n");
            rawLog.append(String.valueOf(pa)).append("\n");
            rawLog.append("========================\n");

            appendTurnLog(rawLog.toString());
            appendResponseCsv(
                "Injected strategy disabled",
                "(none)",
                dynamicPrompt,
                PhysicalGameStatePanel.info1
            );
            if (gs.gameover()) {
                logEndGameMetrics(gs, player);
            }
            return pa;
        }

        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);
        StrategySpec spec = buildStrategySpec();
        appendStrategySection(rawLog, spec);

        for (Unit u : pgs.getUnits()) {
            if (u.getType() == baseType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                baseBehavior(u, p, pgs, spec);
            }
        }

        for (Unit u : pgs.getUnits()) {
            if (u.getType() == barracksType && u.getPlayer() == player && gs.getActionAssignment(u) == null) {
                barracksBehavior(u, p, pgs, spec);
            }
        }

        List<Unit> workers = new LinkedList<>();
        for (Unit u : pgs.getUnits()) {
            if (u.getType() == workerType && u.getPlayer() == player) {
                workers.add(u);
            }
        }
        workersBehavior(workers, p, gs, spec);

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player && u.getType().canAttack && !u.getType().canHarvest && gs.getActionAssignment(u) == null) {
                combatBehavior(u, p, gs, spec);
            }
        }

        logStateSnapshot(player, gs);
        PlayerAction pa = translateActions(player, gs);

        rawLog.append("=== Applied Moves ===\n");
        if (moveLogBuffer.length() == 0) {
            rawLog.append("(none)\n");
        } else {
            rawLog.append(moveLogBuffer);
        }
        rawLog.append("========================\n");
        rawLog.append("=== Final PlayerAction ===\n");
        rawLog.append(String.valueOf(pa)).append("\n");
        rawLog.append("========================\n");

        appendTurnLog(rawLog.toString());
        String movesSummary = moveLogBuffer.length() == 0 ? "(none)" : moveLogBuffer.toString();
        appendResponseCsv(
            "eaglePolicy strategy applied",
            movesSummary,
            dynamicPrompt,
            PhysicalGameStatePanel.info1
        );
        if (gs.gameover()) {
            logEndGameMetrics(gs, player);
        }
        return pa;
    }

    protected void baseBehavior(Unit base, Player player, PhysicalGameState pgs, StrategySpec spec) {
        int workerCount = countUnits(pgs, player.getID(), workerType);
        int barracksCount = countUnits(pgs, player.getID(), barracksType);
        int targetWorkers = barracksCount > 0 ? spec.workerTargetAfterBarracks : spec.workerTargetBeforeBarracks;

        if (workerCount < targetWorkers && player.getResources() >= workerType.cost) {
            if (shouldSkip(P_FAIL_TRAIN)) {
                logMove("SKIPPED", base, "train", workerType.name + " [dropout]");
                return;
            }
            train(base, workerType);
            logMove("APPLIED", base, "train", workerType.name);
        }
    }

    protected void barracksBehavior(Unit barracks, Player player, PhysicalGameState pgs, StrategySpec spec) {
        UnitType nextType = chooseProductionType(player, pgs, spec);
        if (nextType != null && player.getResources() >= nextType.cost) {
            if (shouldSkip(P_FAIL_TRAIN)) {
                logMove("SKIPPED", barracks, "train", nextType.name + " [dropout]");
                return;
            }
            train(barracks, nextType);
            logMove("APPLIED", barracks, "train", nextType.name);
        }
    }

    protected void workersBehavior(List<Unit> workers, Player player, GameState gs, StrategySpec spec) {
        if (workers.isEmpty()) {
            return;
        }

        PhysicalGameState pgs = gs.getPhysicalGameState();
        int baseCount = countUnits(pgs, player.getID(), baseType);
        int barracksCount = countUnits(pgs, player.getID(), barracksType);
        int resourcesUsed = 0;
        List<Unit> freeWorkers = new LinkedList<>(workers);
        List<Integer> reservedPositions = new LinkedList<>();

        if (baseCount == 0 && !freeWorkers.isEmpty() && player.getResources() >= baseType.cost) {
            Unit builder = freeWorkers.remove(0);
            if (shouldSkip(P_FAIL_BUILD)) {
                logMove("SKIPPED", builder, "build", baseType.name + " [dropout]");
            } else {
                Build pendingBuild = getCurrentBuild(builder, baseType);
                if (pendingBuild != null) {
                    logMove("PENDING", builder, "build", baseType.name + " " + formatPosition(pendingBuild.x, pendingBuild.y));
                    return;
                }
                int buildPos = findBuildingPosition(reservedPositions, builder.getX(), builder.getY(), player, pgs);
                if (buildPos >= 0
                        && buildIfNotAlreadyBuilding(
                            builder,
                            baseType,
                            builder.getX(),
                            builder.getY(),
                            reservedPositions,
                            player,
                            pgs)) {
                    int buildX = buildPos % pgs.getWidth();
                    int buildY = buildPos / pgs.getWidth();
                    logMove("APPLIED", builder, "build", baseType.name + " " + formatPosition(buildX, buildY));
                    resourcesUsed += baseType.cost;
                } else {
                    logMove("SKIPPED", builder, "build", baseType.name + " [no_valid_position]");
                }
            }
        }

        while (barracksCount < spec.desiredBarracks
                && !freeWorkers.isEmpty()
                && player.getResources() >= barracksType.cost + resourcesUsed) {
            Unit builder = freeWorkers.remove(0);
            if (shouldSkip(P_FAIL_BUILD)) {
                logMove("SKIPPED", builder, "build", barracksType.name + " [dropout]");
            } else {
                Build pendingBuild = getCurrentBuild(builder, barracksType);
                if (pendingBuild != null) {
                    logMove(
                        "PENDING",
                        builder,
                        "build",
                        barracksType.name + " " + formatPosition(pendingBuild.x, pendingBuild.y));
                    barracksCount++;
                    continue;
                }
                int buildPos = findBuildingPosition(reservedPositions, builder.getX(), builder.getY(), player, pgs);
                if (buildPos >= 0
                        && buildIfNotAlreadyBuilding(
                            builder,
                            barracksType,
                            builder.getX(),
                            builder.getY(),
                            reservedPositions,
                            player,
                            pgs)) {
                    int buildX = buildPos % pgs.getWidth();
                    int buildY = buildPos / pgs.getWidth();
                    logMove("APPLIED", builder, "build", barracksType.name + " " + formatPosition(buildX, buildY));
                    resourcesUsed += barracksType.cost;
                    barracksCount++;
                } else {
                    logMove("SKIPPED", builder, "build", barracksType.name + " [no_valid_position]");
                }
            }
        }

        int desiredHarvesters = Math.min(freeWorkers.size(), Math.max(1, spec.harvesterTarget));
        List<Unit> militaryWorkers = new LinkedList<>();
        for (Unit worker : freeWorkers) {
            if (desiredHarvesters > 0 && tryHarvest(worker, player, pgs)) {
                desiredHarvesters--;
            } else {
                militaryWorkers.add(worker);
            }
        }

        for (Unit worker : militaryWorkers) {
            if (spec.workerHarassEnabled) {
                combatBehavior(worker, player, gs, spec);
            }
        }
    }

    protected boolean tryHarvest(Unit worker, Player player, PhysicalGameState pgs) {
        Unit closestBase = nearestUnit(worker, pgs, player.getID(), baseType, true);
        Unit closestResource = nearestResource(worker, pgs);
        if (closestBase == null || closestResource == null) {
            return false;
        }

        if (shouldSkip(P_FAIL_WORKER)) {
            logMove("SKIPPED", worker, "harvest", "[dropout]");
            return true;
        }

        if (worker.getResources() > 0) {
            AbstractAction aa = getAbstractAction(worker);
            if (!(aa instanceof Harvest) || ((Harvest) aa).base != closestBase) {
                harvest(worker, null, closestBase);
                logMove("APPLIED", worker, "harvest",
                    "return_to_base (" + closestBase.getX() + "," + closestBase.getY() + ")");
            }
            return true;
        }

        AbstractAction aa = getAbstractAction(worker);
        if (!(aa instanceof Harvest)
                || ((Harvest) aa).target != closestResource
                || ((Harvest) aa).base != closestBase) {
            harvest(worker, closestResource, closestBase);
            logMove("APPLIED", worker, "harvest",
                "resource (" + closestResource.getX() + "," + closestResource.getY()
                    + ") -> base (" + closestBase.getX() + "," + closestBase.getY() + ")");
        }
        return true;
    }

    protected void combatBehavior(Unit attacker, Player player, GameState gs, StrategySpec spec) {
        if (shouldSkip(P_FAIL_COMBAT)) {
            logMove("SKIPPED", attacker, "attack", "[dropout]");
            return;
        }

        Unit target = selectAttackTarget(attacker, player, gs.getPhysicalGameState(), spec);
        if (target != null) {
            attack(attacker, target);
            logMove("APPLIED", attacker, "attack", "(" + target.getX() + "," + target.getY() + ")");
        }
    }

    protected Unit selectAttackTarget(Unit attacker, Player player, PhysicalGameState pgs, StrategySpec spec) {
        List<Unit> topCandidates = new ArrayList<>();
        List<Integer> topScores = new ArrayList<>();

        for (Unit candidate : pgs.getUnits()) {
            if (candidate.getPlayer() < 0 || candidate.getPlayer() == player.getID()) {
                continue;
            }

            int distance = Math.abs(candidate.getX() - attacker.getX()) + Math.abs(candidate.getY() - attacker.getY());
            if (distance > ATTACK_RADIUS_LIMIT) {
                continue;
            }

            int score = -distance;

            if (spec.attackWorkersFirst && candidate.getType() == workerType) {
                score += 30;
            }
            if (spec.attackStructuresFirst && (candidate.getType() == baseType || candidate.getType() == barracksType)) {
                score += 25;
            }
            if (spec.protectBarracks && candidate.getType().canAttack && !candidate.getType().canHarvest) {
                score += 8;
            }
            if (candidate.getType() == baseType) {
                score += 5;
            }
            if (candidate.getType() == barracksType) {
                score += 7;
            }

            int insertPos = topCandidates.size();
            for (int i = 0; i < topScores.size(); i++) {
                if (score > topScores.get(i)) {
                    insertPos = i;
                    break;
                }
            }

            if (insertPos < TARGET_TOP_K) {
                topCandidates.add(insertPos, candidate);
                topScores.add(insertPos, score);

                if (topCandidates.size() > TARGET_TOP_K) {
                    topCandidates.remove(TARGET_TOP_K);
                    topScores.remove(TARGET_TOP_K);
                }
            }
        }

        if (!topCandidates.isEmpty()) {
            return topCandidates.get(0);
        }

        Unit bestFallback = null;
        int bestFallbackScore = Integer.MIN_VALUE;
        for (Unit candidate : pgs.getUnits()) {
            if (candidate.getPlayer() < 0 || candidate.getPlayer() == player.getID()) {
                continue;
            }

            int distance = Math.abs(candidate.getX() - attacker.getX()) + Math.abs(candidate.getY() - attacker.getY());
            int score = -distance;

            if (spec.attackWorkersFirst && candidate.getType() == workerType) {
                score += 30;
            }
            if (spec.attackStructuresFirst && (candidate.getType() == baseType || candidate.getType() == barracksType)) {
                score += 25;
            }
            if (spec.protectBarracks && candidate.getType().canAttack && !candidate.getType().canHarvest) {
                score += 8;
            }
            if (candidate.getType() == baseType) {
                score += 5;
            }
            if (candidate.getType() == barracksType) {
                score += 7;
            }

            if (bestFallback == null || score > bestFallbackScore) {
                bestFallback = candidate;
                bestFallbackScore = score;
            }
        }

        return bestFallback;
    }

    protected UnitType chooseProductionType(Player player, PhysicalGameState pgs, StrategySpec spec) {
        for (UnitType candidate : spec.productionPriority) {
            if (candidate == null) {
                continue;
            }
            int existing = countUnits(pgs, player.getID(), candidate);
            int minimum = spec.minimumUnitCount(candidate);
            if (existing < minimum && player.getResources() >= candidate.cost) {
                return candidate;
            }
        }

        for (UnitType candidate : spec.productionPriority) {
            if (candidate != null && player.getResources() >= candidate.cost) {
                return candidate;
            }
        }
        return null;
    }

    protected UnitType[] resolveProductionPriority(String[] names) {
        List<UnitType> resolved = new ArrayList<>();
        if (names != null) {
            for (String name : names) {
                UnitType unitType = resolveUnitTypeName(name);
                if (unitType != null && !resolved.contains(unitType)) {
                    resolved.add(unitType);
                }
            }
        }
        if (resolved.isEmpty()) {
            if (lightType != null) resolved.add(lightType);
            if (rangedType != null) resolved.add(rangedType);
            if (heavyType != null) resolved.add(heavyType);
        }
        return resolved.toArray(new UnitType[0]);
    }

    protected UnitType resolveUnitTypeName(String name) {
        if (name == null) {
            return null;
        }
        String normalized = name.trim().toLowerCase();
        if (normalized.equals("light")) {
            return lightType;
        }
        if (normalized.equals("ranged")) {
            return rangedType;
        }
        if (normalized.equals("heavy")) {
            return heavyType;
        }
        return null;
    }

    protected int countUnits(PhysicalGameState pgs, int playerId, UnitType type) {
        int count = 0;
        for (Unit unit : pgs.getUnits()) {
            if (unit.getPlayer() == playerId && unit.getType() == type) {
                count++;
            }
        }
        return count;
    }

    protected Unit nearestUnit(Unit origin, PhysicalGameState pgs, int playerId, UnitType type, boolean samePlayerOnly) {
        Unit closest = null;
        int closestDistance = Integer.MAX_VALUE;
        for (Unit unit : pgs.getUnits()) {
            if (unit.getType() != type) {
                continue;
            }
            if (samePlayerOnly && unit.getPlayer() != playerId) {
                continue;
            }
            int distance = Math.abs(unit.getX() - origin.getX()) + Math.abs(unit.getY() - origin.getY());
            if (closest == null || distance < closestDistance) {
                closest = unit;
                closestDistance = distance;
            }
        }
        return closest;
    }

    protected Unit nearestResource(Unit origin, PhysicalGameState pgs) {
        Unit closest = null;
        int closestDistance = Integer.MAX_VALUE;
        for (Unit unit : pgs.getUnits()) {
            if (!unit.getType().isResource) {
                continue;
            }
            int distance = Math.abs(unit.getX() - origin.getX()) + Math.abs(unit.getY() - origin.getY());
            if (closest == null || distance < closestDistance) {
                closest = unit;
                closestDistance = distance;
            }
        }
        return closest;
    }

    protected class StrategySpec {
        boolean enabled = false;
        int workerTargetBeforeBarracks = 0;
        int workerTargetAfterBarracks = 0;
        int harvesterTarget = 0;
        int desiredBarracks = 0;
        boolean workerHarassEnabled = false;
        boolean attackWorkersFirst = false;
        boolean attackStructuresFirst = false;
        boolean protectBarracks = false;
        UnitType[] productionPriority = new UnitType[0];
        int minLights = 0;
        int minRanged = 0;
        int minHeavies = 0;

        int minimumUnitCount(UnitType type) {
            if (type == lightType) {
                return minLights;
            }
            if (type == rangedType) {
                return minRanged;
            }
            if (type == heavyType) {
                return minHeavies;
            }
            return 0;
        }
    }
}
