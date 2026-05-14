package ai.eagle;

import ai.abstraction.AbstractionLayerAI;
import ai.abstraction.AbstractAction;
import ai.abstraction.pathfinding.AStarPathFinding;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.AI;
import ai.core.ParameterSpecification;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonSyntaxException;
import gui.PhysicalGameStatePanel;
import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.PlayerAction;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;
import util.XMLWriter;

import java.io.BufferedReader;
import java.io.FileWriter;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.StringWriter;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * PureLLM MicroRTS agent with decision caching for larger LLM intervals.
 */
public class EAGLE extends AbstractionLayerAI {
    // Runtime prompt contract:
    // - Python/desktop GUI writes third_party/microrts/prompt.txt.
    // - MicroRTS launches with cwd=third_party/microrts, so the default "prompt.txt" is intentional.
    // - Override only when explicitly testing another prompt with -Dmicrorts.prompt or MICRORTS_PROMPT.
    private static final String PROMPT_PATH = System.getProperty(
            "microrts.prompt",
            System.getenv().getOrDefault("MICRORTS_PROMPT", "prompt.txt")
    );

    // Keep this tied to the Java runtime setting so GUI/config changes affect the real agent cadence.
    private static final int LLM_INTERVAL = readIntSetting("microrts.llm_interval", "LLM_INTERVAL", 1);
    private static final int LLM_CALL_LIMIT = readIntSetting("microrts.llm_call_limit", "LLM_CALL_LIMIT", 50);
    private static final int TICK_LIMIT = readIntSetting("microrts.tick_limit", "TICK_LIMIT", 5000);
    private static final String OLLAMA_FORMAT = "json";
    private static final String OLLAMA_HOST = System.getenv().getOrDefault("OLLAMA_HOST", "http://localhost:11434");
    private static final boolean OLLAMA_STREAM = false;
    private static final boolean DEBUG_MODE = readBooleanSetting("eagle.debug", "EAGLE_DEBUG", false);

    static String MODEL = System.getenv().getOrDefault("OLLAMA_MODEL", "llama3.1:8b");
    private static String PROMPT = null;

    protected UnitTypeTable utt;
    UnitType resourceType;
    UnitType workerType;
    UnitType lightType;
    UnitType heavyType;
    UnitType rangedType;
    UnitType baseType;
    UnitType barracksType;

    private Instant promptTime;
    private Instant responseTime;
    private long latency = 0;
    private int totalMovesGenerated = 0;
    private int totalMovesAccepted = 0;
    private int totalMovesRejected = 0;
    private int llmCallCount = 0;

    private String numShot = "One-Shot";
    private String aiName1 = "";
    private String aiName2 = "";
    private String fileName = "";
    private String valueTimestampAndScore = "";
    private boolean logsInitialized = false;
    private boolean namesInitialized = false;
    private boolean endGameLogged = false;

    private JsonArray lastValidMoves = null;
    private Map<String, UnitSnapshot> lastSnapshot = null;
    private boolean lastResponseWasValid = false;

    private String lastSkipReason = "";
    private String lastCallReason = "";

    public EAGLE(UnitTypeTable aUtt) {
        this(aUtt, new AStarPathFinding());
    }

    public EAGLE(UnitTypeTable aUtt, String aiName1, String aiName2) {
        this(aUtt, new AStarPathFinding());
        if (!namesInitialized) {
            this.aiName1 = aiName1 == null ? "" : aiName1;
            this.aiName2 = aiName2 == null ? "" : aiName2;
            namesInitialized = true;
        }
    }

    public EAGLE(UnitTypeTable aUtt, PathFinding aPf) {
        super(aPf);
        reset(aUtt);
    }

    private static int readIntSetting(String propertyName, String envName, int defaultValue) {
        String raw = System.getProperty(propertyName);
        if (raw == null || raw.isBlank()) {
            raw = System.getenv(envName);
        }
        if (raw == null || raw.isBlank()) {
            return defaultValue;
        }
        try {
            return Math.max(1, Integer.parseInt(raw.trim()));
        } catch (NumberFormatException e) {
            System.err.println("[EAGLE] invalid interval setting: " + raw + "; using " + defaultValue);
            return defaultValue;
        }
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

    private static void debugBlock(String title, String body) {
        if (!DEBUG_MODE) {
            return;
        }
        System.out.println("[EAGLE_DEBUG_BEGIN] " + title);
        System.out.println(body == null ? "" : body);
        System.out.println("[EAGLE_DEBUG_END] " + title);
    }

    protected static String loadPromptOnce() throws IOException {
        if (PROMPT == null) {
            java.nio.file.Path path = java.nio.file.Paths.get(PROMPT_PATH);
            PROMPT = java.nio.file.Files.readString(path, StandardCharsets.UTF_8);
            System.out.println("[EAGLE] loaded prompt from: " + path.toAbsolutePath());
            debugBlock("static_prompt", PROMPT);
        }
        return PROMPT;
    }

    protected String getBasePrompt() throws IOException {
        return loadPromptOnce();
    }

    private void initLogsIfNeeded() {
        if (logsInitialized) {
            return;
        }

        String a = (aiName1 == null || aiName1.isEmpty()) ? "LLM_Ollama" : aiName1;
        String b = (aiName2 == null || aiName2.isEmpty()) ? "RandomBiasedAI" : aiName2;
        String timestamp = new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss").format(new Date());
        fileName = "Response" + timestamp + "_" + a + "_" + numShot + "_" + b + "_" + MODEL + ".csv";

        try (FileWriter writer = new FileWriter(fileName)) {
            writer.append("Thinking,Moves,Feature locations,Request Time,Response Time,Latency(milliseconds),Score_in_every_run\n");
        } catch (IOException e) {
            System.err.println("[EAGLE] failed to initialize CSV log: " + e.getMessage());
        }

        logsInitialized = true;
    }

    private void logEndGameMetrics() {
        if (endGameLogged) {
            return;
        }
        endGameLogged = true;

        JsonObject metrics = new JsonObject();
        metrics.addProperty("moves_generated", totalMovesGenerated);
        metrics.addProperty("moves_accepted", totalMovesAccepted);
        metrics.addProperty("moves_rejected", totalMovesRejected);
        metrics.addProperty("llm_calls", llmCallCount);
        metrics.addProperty("llm_call_limit", LLM_CALL_LIMIT);
        metrics.addProperty("end_time", new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS").format(new Date()));

        try (FileWriter writer = new FileWriter("game_summary.json", true)) {
            writer.write(new GsonBuilder().setPrettyPrinting().create().toJson(metrics));
            writer.write(System.lineSeparator());
        } catch (IOException e) {
            System.err.println("[EAGLE] failed to write game summary: " + e.getMessage());
        }
    }

    @Override
    public void reset() {
        super.reset();
        TIME_BUDGET = -1;
        ITERATIONS_BUDGET = -1;
        clearDecisionCache();
        llmCallCount = 0;
        endGameLogged = false;
    }

    public void reset(UnitTypeTable aUtt) {
        utt = aUtt;
        resourceType = utt.getUnitType("Resource");
        workerType = utt.getUnitType("Worker");
        lightType = utt.getUnitType("Light");
        heavyType = utt.getUnitType("Heavy");
        rangedType = utt.getUnitType("Ranged");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
        clearDecisionCache();
    }

    @Override
    public AI clone() {
        return new EAGLE(utt, pf);
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        initLogsIfNeeded();
        if (gs.gameover()) {
            logEndGameMetrics();
            return translateActions(player, gs);
        }

        // Stage 1: snapshot the real MicroRTS state before any new abstract actions are queued.
        Map<String, UnitSnapshot> currentSnapshot = buildGameSnapshot(player, gs);
        DecisionContext context = buildDecisionContext(player, gs, currentSnapshot);

        // Stage 2: reuse existing abstract actions unless the state and interval require a fresh LLM call.
        if (!shouldCallLLM(gs, context)) {
            System.out.println("[EAGLE] skip LLM: " + lastSkipReason);
            return translateActions(player, gs);
        }

        // Stage 3: render the prompt, call Ollama, and reject malformed JSON before touching game actions.
        System.out.println("[EAGLE] call LLM: " + lastCallReason);
        PromptContext promptContext = buildPromptContext(player, gs);
        logStateSnapshot(player, gs);
        logDynamicPrompt(promptContext.dynamicPrompt);
        llmCallCount++;
        System.out.println("[EAGLE] llm_call_count=" + llmCallCount + "/" + LLM_CALL_LIMIT);
        String response = prompt(promptContext.finalPrompt);
        logRawLLMResponse(response);
        JsonObject jsonResponse;

        try {
            jsonResponse = parseJsonStrictThenLenient(response);
        } catch (Exception e) {
            System.out.println("[EAGLE] invalid LLM response: JSON parse failed: " + e.getMessage());
            totalMovesRejected++;
            updateDecisionCache(null, currentSnapshot, false);
            return translateActions(player, gs);
        }

        String invalidReason = validateLLMResponse(jsonResponse);
        if (invalidReason != null) {
            System.out.println("[EAGLE] invalid LLM response: " + invalidReason);
            totalMovesRejected++;
            updateDecisionCache(jsonResponse, currentSnapshot, false);
            return translateActions(player, gs);
        }

        JsonArray moves = jsonResponse.getAsJsonArray("moves");
        // Stage 4: convert accepted JSON moves into AbstractionLayerAI actions.
        applyLLMMoves(player, gs, moves);
        // Stage 5: add a local melee fallback for idle combat units after LLM moves are applied.
        applyAutoDefense(player, gs);
        updateDecisionCache(jsonResponse, currentSnapshot, true);
        appendCsvLog(response, promptContext.featureArrayForCsv);

        if (gs.gameover()) {
            logEndGameMetrics();
        }

        return translateActions(player, gs);
    }

    private PromptContext buildPromptContext(int player, GameState gs) throws IOException {
        // The base strategy text comes from prompt.txt; the live game-state block is appended here.
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);
        ArrayList<String> features = new ArrayList<>();
        int maxActions = 0;

        for (Unit unit : pgs.getUnits()) {
            if (unit.getPlayer() == player) {
                maxActions++;
            }
            features.add(formatFeature(unit, player, p, gs));
        }

        String featuresPrompt = "Feature locations:\n" + String.join("\n", features);
        String featureArrayForCsv = Arrays.stream(featuresPrompt.split("\n"))
                .map(s -> "\"" + s.replace("\"", "\\\"") + "\"")
                .collect(Collectors.joining(", ", "[", "]"));

        String dynamicPrompt =  "Map size: " + pgs.getWidth() + "x" + pgs.getHeight() + "\n"
                                + "Turn: " + gs.getTime() + "/" + TICK_LIMIT + "\n"
                                + "Max actions: " + maxActions + "\n\n"
                                + featuresPrompt + "\n";
        String finalPrompt = getBasePrompt() + "\n\n" +
                            dynamicPrompt + 
                            "OUTPUT:\n";
                

        valueTimestampAndScore = PhysicalGameStatePanel.info1;
        debugBlock("dynamic_prompt", dynamicPrompt);
        return new PromptContext(finalPrompt, dynamicPrompt, featureArrayForCsv);
    }

    private void logStateSnapshot(int player, GameState gs) {
        Player p0 = gs.getPlayer(0);
        Player p1 = gs.getPlayer(1);
        int currentTime = gs.getTime();

        System.out.println("gs.gameover() = " + gs.gameover());
        System.out.println("Running getAction for Player: " + player);
        System.out.println(
                " current time " + currentTime
                        + " p0 player " + p0.getID() + "(" + p0.getResources() + ")"
                        + " p1 player " + p1.getID() + "(" + p1.getResources() + ")"
        );
        System.out.printf(
                "T: %d, P0: %d (%s), P1: %d (%s)%n",
                currentTime,
                p0.getID(), p0.getResources(),
                p1.getID(), p1.getResources()
        );
    }

    private void logDynamicPrompt(String dynamicPrompt) {
        System.out.println("=== Dynamic Prompt ===");
        System.out.print(dynamicPrompt == null ? "" : dynamicPrompt);
        if (dynamicPrompt == null || !dynamicPrompt.endsWith("\n")) {
            System.out.println();
        }
        System.out.println("========================");
    }

    private void logRawLLMResponse(String response) {
        System.out.println("=== Raw LLM Response ===");
        System.out.println(response == null ? "" : response);
        System.out.println("========================");
    }

    private String formatFeature(Unit unit, int player, Player p, GameState gs) {
        String unitStats;
        String unitType;
        String unitActionString = currentActionToString(unit, gs.getUnitAction(unit));

        if (unit.getType() == resourceType) {
            unitType = "Resource Node";
            unitStats = "{resources=" + unit.getResources() + "}";
        } else if (unit.getType() == baseType) {
            unitType = "Base Unit";
            unitStats = "{resources=" + p.getResources()
                    + ", current_action=\"" + unitActionString + "\", HP=" + unit.getHitPoints() + "}";
        } else if (unit.getType() == barracksType) {
            unitType = "Barracks Unit";
            unitStats = "{current_action=\"" + unitActionString + "\", HP=" + unit.getHitPoints() + "}";
        } else if (unit.getType() == workerType) {
            unitType = "Worker Unit";
            unitStats = "{current_action=\"" + unitActionString + "\", HP=" + unit.getHitPoints() + "}";
        } else if (unit.getType() == lightType) {
            unitType = "Light Unit";
            unitStats = "{current_action=\"" + unitActionString + "\", HP=" + unit.getHitPoints() + "}";
        } else if (unit.getType() == heavyType) {
            unitType = "Heavy Unit";
            unitStats = "{current_action=\"" + unitActionString + "\", HP=" + unit.getHitPoints() + "}";
        } else if (unit.getType() == rangedType) {
            unitType = "Ranged Unit";
            unitStats = "{current_action=\"" + unitActionString + "\", HP=" + unit.getHitPoints() + "}";
        } else {
            unitType = "Unknown";
            unitStats = "{}";
        }

        String team = unit.getPlayer() == player ? "Ally" : (unit.getType() == resourceType ? "Neutral" : "Enemy");
        return "(" + unit.getX() + ", " + unit.getY() + ") " + team + " " + unitType + " " + unitStats;
    }

    private Map<String, UnitSnapshot> buildGameSnapshot(int player, GameState gs) {
        // Snapshot only stable fields that should trigger a new decision when they change.
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);
        Map<String, UnitSnapshot> snapshot = new LinkedHashMap<>();

        for (Unit unit : pgs.getUnits()) {
            String key = unitKey(unit);
            String team = unit.getPlayer() == player ? "Ally" : (unit.getType() == resourceType ? "Neutral" : "Enemy");
            int storedResources = unit.getType() == baseType && unit.getPlayer() == player
                    ? p.getResources()
                    : unit.getResources();
            boolean hasAbstractAction = unit.getPlayer() == player && getAbstractAction(unit) != null;
            snapshot.put(key, new UnitSnapshot(
                    key,
                    unit.getX(),
                    unit.getY(),
                    unit.getPlayer(),
                    team,
                    unit.getType().name,
                    unit.getHitPoints(),
                    storedResources,
                    currentActionToString(unit, gs.getUnitAction(unit)),
                    hasAbstractAction
            ));
        }

        return snapshot;
    }

    private String unitKey(Unit unit) {
        return unit.getID() + ":" + unit.getType().name;
    }

    private DecisionContext buildDecisionContext(int player, GameState gs, Map<String, UnitSnapshot> currentSnapshot) {
        // Compare the new snapshot against the last LLM-valid state so MicroRTS does not spam the model every frame.
        boolean hasIdleAlly = false;
        List<String> changedKeys = new ArrayList<>();
        boolean alliedChanged = false;
        boolean nonAlliedChanged = false;
        boolean alliedRemoved = false;

        for (Unit unit : gs.getPhysicalGameState().getUnits()) {
            if (unit.getPlayer() == player && isUnitFreeForNewDecision(unit, gs)) {
                hasIdleAlly = true;
            }
        }

        if (lastSnapshot == null) {
            return new DecisionContext(true, hasIdleAlly, false, false, false, changedKeys);
        }

        for (Map.Entry<String, UnitSnapshot> entry : currentSnapshot.entrySet()) {
            UnitSnapshot previous = lastSnapshot.get(entry.getKey());
            UnitSnapshot current = entry.getValue();
            if (!current.equals(previous)) {
                changedKeys.add(entry.getKey());
                if ("Ally".equals(current.team)) {
                    alliedChanged = true;
                    if (!current.hasAbstractAction && "idling".equals(current.currentAction)) {
                        hasIdleAlly = true;
                    }
                } else {
                    nonAlliedChanged = true;
                }
            }
        }

        for (Map.Entry<String, UnitSnapshot> entry : lastSnapshot.entrySet()) {
            if (!currentSnapshot.containsKey(entry.getKey())) {
                changedKeys.add(entry.getKey());
                if ("Ally".equals(entry.getValue().team)) {
                    alliedRemoved = true;
                } else {
                    nonAlliedChanged = true;
                }
            }
        }

        return new DecisionContext(false, hasIdleAlly, alliedChanged, nonAlliedChanged, alliedRemoved, changedKeys);
    }

    private boolean shouldCallLLM(GameState gs, DecisionContext context) {
        if (llmCallCount >= LLM_CALL_LIMIT) {
            lastSkipReason = "llm_call_limit reached (" + llmCallCount + "/" + LLM_CALL_LIMIT + ")";
            return false;
        }
        // Invalid or missing previous output forces a retry; valid cached actions can keep running.
        if (!lastResponseWasValid) {
            lastCallReason = "previous response was invalid or missing";
            return true;
        }
        if (lastSnapshot == null) {
            lastCallReason = "no previous snapshot";
            return true;
        }
        if (lastValidMoves == null) {
            lastCallReason = "no previous valid moves";
            return true;
        }
        if (!context.changedKeys.isEmpty() && context.hasIdleAlly) {
            lastCallReason = "state changed and at least one allied unit needs a new decision";
            return true;
        }
        if (context.alliedRemoved && context.hasIdleAlly) {
            lastCallReason = "allied unit disappeared and remaining allied unit needs a new decision";
            return true;
        }
        if (gs.getTime() % LLM_INTERVAL == 0 && context.hasIdleAlly) {
            lastCallReason = "interval reached and allied unit needs a new decision";
            return true;
        }

        if (context.changedKeys.isEmpty()) {
            lastSkipReason = "state unchanged";
        } else if (!context.hasIdleAlly) {
            lastSkipReason = "state changed, but allied units are already executing actions";
        } else {
            lastSkipReason = "no new decision required";
        }
        return false;
    }

    private boolean isUnitFreeForNewDecision(Unit unit, GameState gs) {
        return unit.getPlayer() >= 0
                && unit.getPlayer() != -1
                && gs.getUnitAction(unit) == null
                && getAbstractAction(unit) == null;
    }

    private String validateLLMResponse(JsonObject response) {
        if (response == null) {
            return "response is null";
        }
        if (!response.has("thinking") || response.get("thinking").isJsonNull()) {
            return "missing thinking";
        }
        if (!response.has("moves") || !response.get("moves").isJsonArray()) {
            return "missing moves array";
        }

        JsonArray moves = response.getAsJsonArray("moves");
        for (int i = 0; i < moves.size(); i++) {
            JsonElement element = moves.get(i);
            if (!element.isJsonObject()) {
                return "move[" + i + "] is not an object";
            }
            JsonObject move = element.getAsJsonObject();
            for (String field : List.of("raw_move", "unit_position", "unit_type", "action_type")) {
                if (!move.has(field) || move.get(field).isJsonNull()) {
                    return "move[" + i + "] missing " + field;
                }
            }
            if (!move.get("unit_position").isJsonArray()) {
                return "move[" + i + "] unit_position is not an array";
            }
            JsonArray pos = move.getAsJsonArray("unit_position");
            if (pos.size() != 2 || !pos.get(0).isJsonPrimitive() || !pos.get(1).isJsonPrimitive()) {
                return "move[" + i + "] unit_position must contain exactly 2 integers";
            }
            try {
                pos.get(0).getAsInt();
                pos.get(1).getAsInt();
            } catch (Exception e) {
                return "move[" + i + "] unit_position contains non-integer values";
            }
        }
        return null;
    }

    private void applyLLMMoves(int player, GameState gs, JsonArray moves) {
        // Each move is validated against the current board before being queued as an abstract action.
        PhysicalGameState pgs = gs.getPhysicalGameState();
        int accepted = 0;
        int rejected = 0;

        for (JsonElement moveElement : moves) {
            try {
                JsonObject move = moveElement.getAsJsonObject();
                JsonArray unitPosition = move.getAsJsonArray("unit_position");
                int unitX = unitPosition.get(0).getAsInt();
                int unitY = unitPosition.get(1).getAsInt();
                Unit unit = pgs.getUnitAt(unitX, unitY);

                if (unit == null || unit.getPlayer() != player) {
                    rejected++;
                    continue;
                }

                String actionType = move.get("action_type").getAsString().toLowerCase();
                String rawMove = move.get("raw_move").getAsString();
                boolean applied = applySingleMove(actionType, rawMove, unit, pgs);
                if (applied) {
                    accepted++;
                } else {
                    rejected++;
                }
            } catch (Exception e) {
                rejected++;
                System.out.println("[EAGLE] move rejected: " + e.getMessage());
            }
        }

        totalMovesGenerated += moves.size();
        totalMovesAccepted += accepted;
        totalMovesRejected += rejected;
    }

    private boolean applySingleMove(String actionType, String rawMove, Unit unit, PhysicalGameState pgs) {
        switch (actionType) {
            case "move":
                return applyMove(rawMove, unit);
            case "harvest":
                return applyHarvest(rawMove, unit, pgs);
            case "train":
                return applyTrain(rawMove, unit);
            case "build":
                return applyBuild(rawMove, unit);
            case "attack":
                return applyAttack(rawMove, unit, pgs);
            case "idle":
                idle(unit);
                return true;
            default:
                return false;
        }
    }

    private boolean applyMove(String rawMove, Unit unit) {
        if (unit.getType() == baseType || unit.getType() == barracksType) {
            return false;
        }
        Matcher matcher = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?move\\(\\(\\s*(\\d+),\\s*(\\d+)\\s*\\)\\)").matcher(rawMove);
        if (!matcher.find()) {
            return false;
        }
        move(unit, Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
        return true;
    }

    private boolean applyHarvest(String rawMove, Unit unit, PhysicalGameState pgs) {
        if (unit.getType() != workerType) {
            return false;
        }
        Matcher matcher = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?harvest\\(\\((\\d+),\\s*(\\d+)\\),\\s*\\((\\d+),\\s*(\\d+)\\)\\)").matcher(rawMove);
        if (!matcher.find()) {
            return false;
        }
        Unit resourceUnit = pgs.getUnitAt(Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
        Unit baseUnit = pgs.getUnitAt(Integer.parseInt(matcher.group(3)), Integer.parseInt(matcher.group(4)));
        if (resourceUnit == null || baseUnit == null || resourceUnit.getType() != resourceType || baseUnit.getType() != baseType) {
            return false;
        }
        harvest(unit, resourceUnit, baseUnit);
        return true;
    }

    private boolean applyTrain(String rawMove, Unit unit) {
        if (unit.getType() != baseType && unit.getType() != barracksType) {
            return false;
        }
        Matcher matcher = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?train\\(\\s*['\\\"]?(\\w+)['\\\"]?\\s*\\)").matcher(rawMove);
        if (!matcher.find()) {
            return false;
        }
        train(unit, stringToUnitType(matcher.group(1)));
        return true;
    }

    private boolean applyBuild(String rawMove, Unit unit) {
        if (unit.getType() != workerType) {
            return false;
        }
        Matcher matcher = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?build\\(\\s*\\(\\s*(\\d+),\\s*(\\d+)\\s*\\),\\s*['\\\"]?(\\w+)['\\\"]?\\s*\\)").matcher(rawMove);
        if (!matcher.find()) {
            return false;
        }
        build(unit, stringToUnitType(matcher.group(3)), Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
        return true;
    }

    private boolean applyAttack(String rawMove, Unit unit, PhysicalGameState pgs) {
        if (!unit.getType().canAttack) {
            return false;
        }
        Matcher matcher = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?attack\\(\\s*\\(\\s*(\\d+),\\s*(\\d+)\\s*\\)\\s*\\)").matcher(rawMove);
        if (!matcher.find()) {
            return false;
        }
        Unit enemyUnit = pgs.getUnitAt(Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
        if (enemyUnit == null || enemyUnit.getPlayer() == unit.getPlayer()) {
            return false;
        }
        attack(unit, enemyUnit);
        return true;
    }

    private void applyAutoDefense(int player, GameState gs) {
        // Local fallback only handles adjacent enemies for idle attackers; it does not replace strategic LLM moves.
        PhysicalGameState pgs = gs.getPhysicalGameState();
        for (Unit ally : pgs.getUnits()) {
            if (ally.getPlayer() != player || !ally.getType().canAttack || getAbstractAction(ally) != null) {
                continue;
            }

            Unit closestEnemy = null;
            int closestDistance = Integer.MAX_VALUE;
            for (Unit other : pgs.getUnits()) {
                if (other.getPlayer() == player || other.getPlayer() < 0) {
                    continue;
                }
                int distance = Math.abs(other.getX() - ally.getX()) + Math.abs(other.getY() - ally.getY());
                if (distance < closestDistance) {
                    closestEnemy = other;
                    closestDistance = distance;
                }
            }

            if (closestEnemy != null && closestDistance == 1) {
                attack(ally, closestEnemy);
            }
        }
    }

    private void updateDecisionCache(JsonObject response, Map<String, UnitSnapshot> snapshot, boolean valid) {
        // Cache the state that produced this response, not the post-action translated PlayerAction.
        lastResponseWasValid = valid;
        lastSnapshot = new LinkedHashMap<>(snapshot);
        lastValidMoves = valid && response != null && response.has("moves")
                ? response.getAsJsonArray("moves").deepCopy()
                : null;
    }

    private void clearDecisionCache() {
        lastValidMoves = null;
        lastSnapshot = null;
        lastResponseWasValid = false;
        lastSkipReason = "";
        lastCallReason = "";
    }

    private void appendCsvLog(String response, String featureArrayForCsv) {
        if (fileName == null || fileName.isEmpty()) {
            return;
        }
        try (FileWriter writer = new FileWriter(fileName, true)) {
            String thinking = "";
            String moves = response;
            int thinkingIndex = response.indexOf("\"thinking\"");
            int movesIndex = response.indexOf("\"moves\"");
            if (thinkingIndex >= 0 && movesIndex > thinkingIndex) {
                thinking = response.substring(thinkingIndex + 11, movesIndex);
                moves = response.substring(movesIndex);
            }

            writer.append(escapeForCSV(thinking)).append(",")
                    .append(escapeForCSV(moves)).append(",")
                    .append(escapeForCSV(featureArrayForCsv)).append(",")
                    .append(promptTime != null ? promptTime.toString() : "").append(",")
                    .append(responseTime != null ? responseTime.toString() : "").append(",")
                    .append(String.valueOf(latency)).append(",")
                    .append(escapeForCSV(valueTimestampAndScore))
                    .append("\n");
        } catch (IOException e) {
            System.err.println("[EAGLE] failed to write CSV row: " + e.getMessage());
        }
    }

    public static String escapeForCSV(String value) {
        if (value == null) {
            return "\"\"";
        }
        String escaped = value.replace("\"", "\"\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r");
        return "\"" + escaped + "\"";
    }

    static String sanitizeModelJson(String s) {
        if (s == null) {
            return "";
        }
        s = s.trim();
        if (s.startsWith("```")) {
            int first = s.indexOf('\n');
            if (first >= 0) {
                s = s.substring(first + 1);
            }
            int close = s.lastIndexOf("```");
            if (close > 0) {
                s = s.substring(0, close);
            }
            s = s.trim();
        }

        int obj = s.indexOf('{');
        int arr = s.indexOf('[');
        int start = obj == -1 ? arr : (arr == -1 ? obj : Math.min(obj, arr));
        if (start > 0) {
            s = s.substring(start).trim();
        }
        return s;
    }

    static JsonObject parseJsonStrictThenLenient(String raw) {
        String cleaned = sanitizeModelJson(raw);
        try {
            return JsonParser.parseString(cleaned).getAsJsonObject();
        } catch (JsonSyntaxException e) {
            try {
                com.google.gson.stream.JsonReader reader = new com.google.gson.stream.JsonReader(new java.io.StringReader(cleaned));
                reader.setLenient(true);
                return JsonParser.parseReader(reader).getAsJsonObject();
            } catch (Exception ignored) {
                throw e;
            }
        }
    }

    public String prompt(String finalPrompt) {
        try {
            JsonObject body = new JsonObject();
            body.addProperty("model", MODEL);
            body.addProperty("prompt", "/no_think " + finalPrompt);
            body.addProperty("stream", OLLAMA_STREAM);
            body.addProperty("format", OLLAMA_FORMAT);

            URL url = new URL(OLLAMA_HOST + "/api/generate");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);

            promptTime = Instant.now();
            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            InputStream stream = code == HttpURLConnection.HTTP_OK ? conn.getInputStream() : conn.getErrorStream();
            StringBuilder sb = new StringBuilder();
            try (BufferedReader br = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                for (String line; (line = br.readLine()) != null; ) {
                    sb.append(line);
                }
            }

            responseTime = Instant.now();
            latency = responseTime.toEpochMilli() - promptTime.toEpochMilli();

            if (code != HttpURLConnection.HTTP_OK) {
                System.err.println("[EAGLE] Ollama error (" + code + "): " + sb);
                return "{\"thinking\":\"ollama_error\",\"moves\":[]}";
            }

            JsonObject top = JsonParser.parseString(sb.toString()).getAsJsonObject();
            if (top.has("response") && !top.get("response").getAsString().isEmpty()) {
                String modelText = top.get("response").getAsString();
                debugBlock("response", modelText);
                return modelText;
            }
            if (top.has("thinking") && !top.get("thinking").isJsonNull()) {
                String modelText = top.get("thinking").getAsString();
                debugBlock("response", modelText);
                return modelText;
            }

            System.err.println("[EAGLE] unexpected Ollama payload: " + sb);
            return "{\"thinking\":\"invalid_ollama_payload\",\"moves\":[]}";
        } catch (Exception e) {
            System.err.println("[EAGLE] Ollama exception: " + e.getMessage());
            return "{\"thinking\":\"exception\",\"moves\":[]}";
        }
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }

    private UnitType stringToUnitType(String value) {
        switch (value.toLowerCase()) {
            case "worker":
                return workerType;
            case "light":
                return lightType;
            case "heavy":
                return heavyType;
            case "ranged":
                return rangedType;
            case "base":
                return baseType;
            case "barracks":
                return barracksType;
            default:
                System.out.println("[EAGLE] unknown unit type: " + value + "; using worker");
                return workerType;
        }
    }

    private String currentActionToString(Unit unit, UnitAction action) {
        AbstractAction queuedAction = getAbstractAction(unit);
        if (queuedAction != null) {
            return abstractActionToString(queuedAction);
        }
        return unitActionToString(unit, action);
    }

    private String unitActionToString(Unit unit, UnitAction action) {
        if (action == null) {
            return "idling";
        }
        switch (action.getType()) {
            case UnitAction.TYPE_MOVE:
                return String.format("moving %s toward next_cell=(%d,%d)",
                        directionName(action.getDirection()),
                        actionTargetX(unit, action),
                        actionTargetY(unit, action));
            case UnitAction.TYPE_HARVEST:
                return String.format("harvesting %s from adjacent_cell=(%d,%d)",
                        directionName(action.getDirection()),
                        actionTargetX(unit, action),
                        actionTargetY(unit, action));
            case UnitAction.TYPE_RETURN:
                return String.format("returning resources %s to adjacent_cell=(%d,%d)",
                        directionName(action.getDirection()),
                        actionTargetX(unit, action),
                        actionTargetY(unit, action));
            case UnitAction.TYPE_PRODUCE:
                return String.format("producing %s %s at adjacent_cell=(%d,%d)",
                        action.getUnitType() == null ? "unit" : action.getUnitType().name,
                        directionName(action.getDirection()),
                        actionTargetX(unit, action),
                        actionTargetY(unit, action));
            case UnitAction.TYPE_ATTACK_LOCATION:
                return String.format("attacking location (%d,%d)", action.getLocationX(), action.getLocationY());
            case UnitAction.TYPE_NONE:
                return "idling";
            default:
                return "unknown action";
        }
    }

    private String abstractActionToString(AbstractAction action) {
        try {
            StringWriter buffer = new StringWriter();
            XMLWriter writer = new XMLWriter(buffer, "");
            action.toxml(writer);
            String xml = buffer.toString();
            if (xml.startsWith("<Build")) {
                return String.format("building %s at (%s,%s)",
                        xmlAttribute(xml, "type"),
                        xmlAttribute(xml, "x"),
                        xmlAttribute(xml, "y"));
            }
            if (xml.startsWith("<Move")) {
                return String.format("moving to (%s,%s)",
                        xmlAttribute(xml, "x"),
                        xmlAttribute(xml, "y"));
            }
            if (xml.startsWith("<Train")) {
                return "training " + xmlAttribute(xml, "type");
            }
            if (xml.startsWith("<Attack")) {
                return "attacking unit " + xmlAttribute(xml, "target");
            }
            if (xml.startsWith("<Harvest")) {
                return "harvesting target " + xmlAttribute(xml, "target")
                        + " then returning to base " + xmlAttribute(xml, "base");
            }
            if (xml.startsWith("<Idle")) {
                return "idling";
            }
            return action.getClass().getSimpleName();
        } catch (RuntimeException e) {
            return action.getClass().getSimpleName();
        }
    }

    private String xmlAttribute(String xml, String attribute) {
        Matcher matcher = Pattern.compile(attribute + "=\"([^\"]*)\"").matcher(xml);
        if (matcher.find()) {
            return matcher.group(1);
        }
        return "?";
    }

    private String directionName(int direction) {
        if (direction >= 0 && direction < UnitAction.DIRECTION_NAMES.length) {
            return UnitAction.DIRECTION_NAMES[direction];
        }
        return "none";
    }

    private int actionTargetX(Unit unit, UnitAction action) {
        int direction = action.getDirection();
        if (direction >= 0 && direction < UnitAction.DIRECTION_OFFSET_X.length) {
            return unit.getX() + UnitAction.DIRECTION_OFFSET_X[direction];
        }
        return action.getLocationX();
    }

    private int actionTargetY(Unit unit, UnitAction action) {
        int direction = action.getDirection();
        if (direction >= 0 && direction < UnitAction.DIRECTION_OFFSET_Y.length) {
            return unit.getY() + UnitAction.DIRECTION_OFFSET_Y[direction];
        }
        return action.getLocationY();
    }

    private static class PromptContext {
        final String finalPrompt;
        final String dynamicPrompt;
        final String featureArrayForCsv;

        PromptContext(String finalPrompt, String dynamicPrompt, String featureArrayForCsv) {
            this.finalPrompt = finalPrompt;
            this.dynamicPrompt = dynamicPrompt;
            this.featureArrayForCsv = featureArrayForCsv;
        }
    }

    private static class DecisionContext {
        final boolean noPreviousSnapshot;
        final boolean hasIdleAlly;
        final boolean alliedChanged;
        final boolean nonAlliedChanged;
        final boolean alliedRemoved;
        final List<String> changedKeys;

        DecisionContext(
                boolean noPreviousSnapshot,
                boolean hasIdleAlly,
                boolean alliedChanged,
                boolean nonAlliedChanged,
                boolean alliedRemoved,
                List<String> changedKeys
        ) {
            this.noPreviousSnapshot = noPreviousSnapshot;
            this.hasIdleAlly = hasIdleAlly;
            this.alliedChanged = alliedChanged;
            this.nonAlliedChanged = nonAlliedChanged;
            this.alliedRemoved = alliedRemoved;
            this.changedKeys = changedKeys;
        }
    }

    private static class UnitSnapshot {
        final String key;
        final int x;
        final int y;
        final int player;
        final String team;
        final String type;
        final int hp;
        final int resources;
        final String currentAction;
        final boolean hasAbstractAction;

        UnitSnapshot(
                String key,
                int x,
                int y,
                int player,
                String team,
                String type,
                int hp,
                int resources,
                String currentAction,
                boolean hasAbstractAction
        ) {
            this.key = key;
            this.x = x;
            this.y = y;
            this.player = player;
            this.team = team;
            this.type = type;
            this.hp = hp;
            this.resources = resources;
            this.currentAction = currentAction;
            this.hasAbstractAction = hasAbstractAction;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) {
                return true;
            }
            if (!(o instanceof UnitSnapshot)) {
                return false;
            }
            UnitSnapshot that = (UnitSnapshot) o;
            return x == that.x
                    && y == that.y
                    && player == that.player
                    && hp == that.hp
                    && resources == that.resources
                    && hasAbstractAction == that.hasAbstractAction
                    && Objects.equals(key, that.key)
                    && Objects.equals(team, that.team)
                    && Objects.equals(type, that.type)
                    && Objects.equals(currentAction, that.currentAction);
        }

        @Override
        public int hashCode() {
            return Objects.hash(key, x, y, player, team, type, hp, resources, currentAction, hasAbstractAction);
        }
    }
}
