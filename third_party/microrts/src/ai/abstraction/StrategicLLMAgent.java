package ai.abstraction;

import ai.abstraction.pathfinding.AStarPathFinding;
import ai.core.AI;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.ParameterSpecification;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import com.google.gson.*;

import rts.GameState;
import rts.PhysicalGameState;
import rts.Player;
import rts.PlayerAction;
import rts.units.*;

/**
 * StrategicLLMAgent: Enhanced hybrid AI combining LLM strategic guidance with rule-based execution.
 *
 * This agent extends HybridLLMRush with:
 * - 8 strategies (4 offensive + 4 defensive/economic)
 * - Tactical parameters (aggression, economy_priority, retreat_threshold, primary_target)
 * - Dynamic consultation intervals (more frequent during combat)
 * - Improved targeting logic based on LLM guidance
 *
 * Architecture:
 * - TIER 1: LLM Strategic Advisor (every 200-500 ticks)
 * - TIER 2: Tactical parameter application (continuous)
 * - TIER 3: Rule-based unit controllers (every tick)
 */
public class StrategicLLMAgent extends AbstractionLayerAI {

    /**
     * Extended strategy enum with offensive, defensive, and economic options.
     */
    public enum GameStrategy {
        // Offensive strategies
        WORKER_RUSH,      // Fast early aggression
        LIGHT_RUSH,       // Balanced military build
        HEAVY_RUSH,       // Tank push (counters light)
        RANGED_RUSH,      // Kiting strategy (counters melee)
        // Defensive strategies
        TURTLE,           // Heavy defense + economy
        COUNTER_ATTACK,   // Defend then push
        // Economic strategies
        BOOM,             // Max economy first
        HARASS            // Worker raids while building
    }

    /**
     * Target priority for unit attacks.
     */
    public enum TargetPriority {
        BASE,             // Focus enemy base
        WORKERS,          // Raid enemy economy
        ARMY              // Engage enemy military
    }

    // Strategy instances (composition pattern)
    private WorkerRush workerRushAI;
    private LightRush lightRushAI;
    private HeavyRush heavyRushAI;
    private RangedRush rangedRushAI;
    private TurtleDefense turtleDefenseAI;
    private BoomEconomy boomEconomyAI;

    // Unit type table reference
    protected UnitTypeTable utt;

    // Current strategic state
    private GameStrategy currentStrategy = GameStrategy.LIGHT_RUSH;
    private int lastLLMConsultation = -9999;

    // Tactical parameters (0.0 to 1.0 scale)
    private float aggression = 0.5f;           // 0=passive, 1=all-in
    private float economyPriority = 0.5f;      // 0=military focus, 1=economy focus
    private float retreatThreshold = 0.3f;     // Retreat when strength < this fraction of enemy
    private TargetPriority primaryTarget = TargetPriority.BASE;

    // Configuration (from environment variables)
    private static final String OLLAMA_HOST =
            System.getenv().getOrDefault("OLLAMA_HOST", "http://localhost:11434");
    private static final String MODEL =
            System.getenv().getOrDefault("OLLAMA_MODEL", "llama3.1:8b");
    private static final int BASE_LLM_INTERVAL =
            Integer.parseInt(System.getenv().getOrDefault("STRATEGIC_LLM_INTERVAL", "200"));
    private static final int COMBAT_LLM_INTERVAL =
            Integer.parseInt(System.getenv().getOrDefault("STRATEGIC_LLM_COMBAT_INTERVAL", "100"));

    // Statistics
    private int strategyChanges = 0;
    private int llmConsultations = 0;
    private int llmErrors = 0;
    private boolean inCombat = false;

    /**
     * Constructor with UnitTypeTable
     */
    public StrategicLLMAgent(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());
    }

    /**
     * Constructor with UnitTypeTable and PathFinding
     */
    public StrategicLLMAgent(UnitTypeTable a_utt, PathFinding a_pf) {
        super(a_pf);
        reset(a_utt);
    }

    @Override
    public void reset() {
        super.reset();
        if (workerRushAI != null) workerRushAI.reset();
        if (lightRushAI != null) lightRushAI.reset();
        if (heavyRushAI != null) heavyRushAI.reset();
        if (rangedRushAI != null) rangedRushAI.reset();
        if (turtleDefenseAI != null) turtleDefenseAI.reset();
        if (boomEconomyAI != null) boomEconomyAI.reset();
    }

    public void reset(UnitTypeTable a_utt) {
        utt = a_utt;
        // Initialize all strategy instances
        workerRushAI = new WorkerRush(a_utt, pf);
        lightRushAI = new LightRush(a_utt, pf);
        heavyRushAI = new HeavyRush(a_utt, pf);
        rangedRushAI = new RangedRush(a_utt, pf);
        turtleDefenseAI = new TurtleDefense(a_utt, pf);
        boomEconomyAI = new BoomEconomy(a_utt, pf);

        System.out.println("[StrategicLLMAgent] Initialized with model=" + MODEL +
                           ", base_interval=" + BASE_LLM_INTERVAL +
                           ", combat_interval=" + COMBAT_LLM_INTERVAL +
                           ", initial_strategy=" + currentStrategy);
    }

    @Override
    public AI clone() {
        StrategicLLMAgent clone = new StrategicLLMAgent(utt, pf);
        clone.currentStrategy = this.currentStrategy;
        clone.aggression = this.aggression;
        clone.economyPriority = this.economyPriority;
        clone.retreatThreshold = this.retreatThreshold;
        clone.primaryTarget = this.primaryTarget;
        return clone;
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        int currentTime = gs.getTime();

        // Detect combat state (affects consultation frequency)
        inCombat = detectCombat(player, gs);
        int llmInterval = inCombat ? COMBAT_LLM_INTERVAL : BASE_LLM_INTERVAL;

        // Check if it's time to consult the LLM
        if (currentTime - lastLLMConsultation >= llmInterval) {
            consultLLMForStrategy(player, gs);
            lastLLMConsultation = currentTime;
        }

        // Apply retreat logic if needed
        if (shouldRetreat(player, gs)) {
            return handleRetreat(player, gs);
        }

        // Delegate to the current strategy with tactical modifications
        PlayerAction baseAction = getCurrentStrategyAI().getAction(player, gs);

        // Apply target priority modifications
        return applyTargetPriority(player, gs, baseAction);
    }

    /**
     * Detect if we're in active combat (units engaged)
     */
    private boolean detectCombat(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        int enemyPlayer = 1 - player;

        for (Unit myUnit : pgs.getUnits()) {
            if (myUnit.getPlayer() == player && myUnit.getType().canAttack) {
                for (Unit enemyUnit : pgs.getUnits()) {
                    if (enemyUnit.getPlayer() == enemyPlayer) {
                        int distance = Math.abs(myUnit.getX() - enemyUnit.getX()) +
                                       Math.abs(myUnit.getY() - enemyUnit.getY());
                        if (distance <= 5) {
                            return true;
                        }
                    }
                }
            }
        }
        return false;
    }

    /**
     * Check if we should retreat based on strength comparison
     */
    private boolean shouldRetreat(int player, GameState gs) {
        if (retreatThreshold <= 0) return false;

        int[] strength = calculateStrength(player, gs);
        int myStrength = strength[0];
        int enemyStrength = strength[1];

        if (enemyStrength == 0) return false;

        float ratio = (float) myStrength / enemyStrength;
        return ratio < retreatThreshold && inCombat;
    }

    /**
     * Calculate military strength for both players
     */
    private int[] calculateStrength(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        int enemyPlayer = 1 - player;

        UnitType workerType = utt.getUnitType("Worker");
        UnitType lightType = utt.getUnitType("Light");
        UnitType heavyType = utt.getUnitType("Heavy");
        UnitType rangedType = utt.getUnitType("Ranged");

        int myStrength = 0, enemyStrength = 0;

        for (Unit u : pgs.getUnits()) {
            int value = 0;
            if (u.getType() == workerType) value = 1;
            else if (u.getType() == lightType) value = 2;
            else if (u.getType() == heavyType) value = 4;
            else if (u.getType() == rangedType) value = 2;

            if (u.getPlayer() == player) myStrength += value;
            else if (u.getPlayer() == enemyPlayer) enemyStrength += value;
        }

        return new int[]{myStrength, enemyStrength};
    }

    /**
     * Handle retreat behavior - move military units back toward base
     */
    private PlayerAction handleRetreat(int player, GameState gs) throws Exception {
        // Switch to defensive strategy during retreat
        if (currentStrategy != GameStrategy.TURTLE && currentStrategy != GameStrategy.COUNTER_ATTACK) {
            System.out.println("[StrategicLLMAgent] T=" + gs.getTime() + ": Retreating! Switching to COUNTER_ATTACK");
            switchStrategy(GameStrategy.COUNTER_ATTACK, gs.getTime());
        }
        return getCurrentStrategyAI().getAction(player, gs);
    }

    /**
     * Apply target priority modifications to unit actions
     */
    private PlayerAction applyTargetPriority(int player, GameState gs, PlayerAction baseAction) {
        // For now, delegate to base strategy
        // TODO: Can override attack targets based on primaryTarget setting
        return baseAction;
    }

    /**
     * Get the AI instance for the current strategy
     */
    private AbstractionLayerAI getCurrentStrategyAI() {
        switch (currentStrategy) {
            case WORKER_RUSH:
                return workerRushAI;
            case LIGHT_RUSH:
                return lightRushAI;
            case HEAVY_RUSH:
                return heavyRushAI;
            case RANGED_RUSH:
                return rangedRushAI;
            case TURTLE:
                return turtleDefenseAI;
            case BOOM:
                return boomEconomyAI;
            case COUNTER_ATTACK:
                // Counter attack uses heavy rush but with defensive mindset
                return heavyRushAI;
            case HARASS:
                // Harass uses worker rush for early pressure
                return workerRushAI;
            default:
                return lightRushAI;
        }
    }

    /**
     * Switch to a new strategy
     */
    private void switchStrategy(GameStrategy newStrategy, int currentTime) {
        System.out.println("[StrategicLLMAgent] T=" + currentTime + ": Strategy switch " +
                           currentStrategy + " -> " + newStrategy);
        currentStrategy = newStrategy;
        strategyChanges++;

        // Reset the new strategy's action queue to avoid conflicts
        getCurrentStrategyAI().reset();
    }

    /**
     * Consult the LLM to decide strategy and tactical parameters
     */
    private void consultLLMForStrategy(int player, GameState gs) {
        llmConsultations++;

        try {
            String prompt = buildStrategicPrompt(player, gs);
            String response = callOllamaAPI(prompt);
            parseStrategicResponse(response, gs.getTime());
        } catch (Exception e) {
            llmErrors++;
            System.err.println("[StrategicLLMAgent] LLM consultation failed: " + e.getMessage());
            // Keep current strategy on error
        }
    }

    /**
     * Build a comprehensive strategic prompt for the LLM
     */
    private String buildStrategicPrompt(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);
        int enemyPlayer = 1 - player;

        // Count units for both players
        int myWorkers = 0, myLight = 0, myHeavy = 0, myRanged = 0;
        int myBases = 0, myBarracks = 0;
        int enemyWorkers = 0, enemyLight = 0, enemyHeavy = 0, enemyRanged = 0;
        int enemyBases = 0, enemyBarracks = 0;

        UnitType workerType = utt.getUnitType("Worker");
        UnitType lightType = utt.getUnitType("Light");
        UnitType heavyType = utt.getUnitType("Heavy");
        UnitType rangedType = utt.getUnitType("Ranged");
        UnitType baseType = utt.getUnitType("Base");
        UnitType barracksType = utt.getUnitType("Barracks");

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player) {
                if (u.getType() == workerType) myWorkers++;
                else if (u.getType() == lightType) myLight++;
                else if (u.getType() == heavyType) myHeavy++;
                else if (u.getType() == rangedType) myRanged++;
                else if (u.getType() == baseType) myBases++;
                else if (u.getType() == barracksType) myBarracks++;
            } else if (u.getPlayer() == enemyPlayer) {
                if (u.getType() == workerType) enemyWorkers++;
                else if (u.getType() == lightType) enemyLight++;
                else if (u.getType() == heavyType) enemyHeavy++;
                else if (u.getType() == rangedType) enemyRanged++;
                else if (u.getType() == baseType) enemyBases++;
                else if (u.getType() == barracksType) enemyBarracks++;
            }
        }

        // Calculate military strength
        int myStrength = myWorkers + myLight * 2 + myHeavy * 4 + myRanged * 2;
        int enemyStrength = enemyWorkers + enemyLight * 2 + enemyHeavy * 4 + enemyRanged * 2;

        // Determine game phase
        int maxCycles = 3000;
        String gamePhase;
        if (gs.getTime() < maxCycles / 4) {
            gamePhase = "EARLY";
        } else if (gs.getTime() < maxCycles * 3 / 4) {
            gamePhase = "MID";
        } else {
            gamePhase = "LATE";
        }

        StringBuilder sb = new StringBuilder();
        sb.append("You are a strategic advisor for a real-time strategy game.\n\n");

        sb.append("STRATEGIES (pick one):\n");
        sb.append("- WORKER_RUSH: Fast early attack with workers (no barracks needed)\n");
        sb.append("- LIGHT_RUSH: Build barracks, train light units (fast, balanced)\n");
        sb.append("- HEAVY_RUSH: Train heavy units (high HP, counters light infantry)\n");
        sb.append("- RANGED_RUSH: Train ranged units (attack from distance, counters melee)\n");
        sb.append("- TURTLE: Defensive build with heavy units, attack when strong\n");
        sb.append("- BOOM: Economy first, maximize workers before military\n");
        sb.append("- COUNTER_ATTACK: Defend then push (good when behind)\n");
        sb.append("- HARASS: Worker raids while building up\n\n");

        sb.append("TACTICAL PARAMETERS (0.0 to 1.0):\n");
        sb.append("- aggression: Attack intensity (0=passive, 1=all-in)\n");
        sb.append("- economy_priority: Focus on economy vs military (0=military, 1=economy)\n");
        sb.append("- retreat_threshold: When to retreat (e.g., 0.3 = if strength < 30% of enemy)\n\n");

        sb.append("TARGET PRIORITY (pick one): BASE, WORKERS, ARMY\n\n");

        sb.append("GAME STATE:\n");
        sb.append("- Phase: ").append(gamePhase).append(" (").append(gs.getTime()).append("/").append(maxCycles).append(")\n");
        sb.append("- Your resources: ").append(p.getResources()).append("\n");
        sb.append("- Your forces: ").append(myWorkers).append(" workers, ");
        sb.append(myLight).append(" light, ").append(myHeavy).append(" heavy, ");
        sb.append(myRanged).append(" ranged\n");
        sb.append("- Your buildings: ").append(myBases).append(" base, ");
        sb.append(myBarracks).append(" barracks\n");
        sb.append("- Enemy forces: ").append(enemyWorkers).append(" workers, ");
        sb.append(enemyLight).append(" light, ").append(enemyHeavy).append(" heavy, ");
        sb.append(enemyRanged).append(" ranged\n");
        sb.append("- Strength comparison: You=").append(myStrength);
        sb.append(", Enemy=").append(enemyStrength).append("\n");
        sb.append("- In combat: ").append(inCombat ? "YES" : "NO").append("\n\n");

        sb.append("Current strategy: ").append(currentStrategy).append("\n");
        sb.append("Current params: aggression=").append(String.format("%.1f", aggression));
        sb.append(", economy=").append(String.format("%.1f", economyPriority));
        sb.append(", retreat=").append(String.format("%.1f", retreatThreshold));
        sb.append(", target=").append(primaryTarget).append("\n\n");

        sb.append("Reply with JSON:\n");
        sb.append("{\n");
        sb.append("  \"strategy\": \"LIGHT_RUSH\",\n");
        sb.append("  \"aggression\": 0.7,\n");
        sb.append("  \"economy_priority\": 0.3,\n");
        sb.append("  \"retreat_threshold\": 0.3,\n");
        sb.append("  \"primary_target\": \"BASE\"\n");
        sb.append("}\n");

        return sb.toString();
    }

    /**
     * Call the Ollama API
     */
    private String callOllamaAPI(String prompt) throws Exception {
        JsonObject body = new JsonObject();
        body.addProperty("model", MODEL);
        body.addProperty("prompt", "/no_think " + prompt);
        body.addProperty("stream", false);
        body.addProperty("format", "json");

        URL url = new URL(OLLAMA_HOST + "/api/generate");
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setConnectTimeout(5000);
        conn.setReadTimeout(15000);
        conn.setDoOutput(true);

        try (OutputStream os = conn.getOutputStream()) {
            byte[] input = body.toString().getBytes(StandardCharsets.UTF_8);
            os.write(input);
        }

        int code = conn.getResponseCode();
        InputStream is = (code == HttpURLConnection.HTTP_OK)
                ? conn.getInputStream()
                : conn.getErrorStream();

        StringBuilder sb = new StringBuilder();
        try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
            for (String line; (line = br.readLine()) != null; ) {
                sb.append(line);
            }
        }

        if (code != HttpURLConnection.HTTP_OK) {
            throw new IOException("Ollama API error (" + code + "): " + sb.toString());
        }

        // Parse Ollama response to get the model's text output
        JsonObject top = JsonParser.parseString(sb.toString()).getAsJsonObject();
        if (top.has("response") && !top.get("response").getAsString().isEmpty()) {
            return top.get("response").getAsString();
        }
        throw new IOException("No response field in Ollama output");
    }

    /**
     * Parse the LLM response to extract strategy and tactical parameters
     */
    private void parseStrategicResponse(String response, int currentTime) {
        if (response == null || response.isEmpty()) return;

        try {
            String cleaned = response.trim();
            if (cleaned.startsWith("{")) {
                JsonObject json = JsonParser.parseString(cleaned).getAsJsonObject();

                // Parse strategy
                if (json.has("strategy")) {
                    String strategyStr = json.get("strategy").getAsString().toUpperCase();
                    GameStrategy newStrategy = parseStrategyString(strategyStr);
                    if (newStrategy != null && newStrategy != currentStrategy) {
                        switchStrategy(newStrategy, currentTime);
                    }
                }

                // Parse tactical parameters
                if (json.has("aggression")) {
                    aggression = clamp(json.get("aggression").getAsFloat(), 0f, 1f);
                }
                if (json.has("economy_priority")) {
                    economyPriority = clamp(json.get("economy_priority").getAsFloat(), 0f, 1f);
                }
                if (json.has("retreat_threshold")) {
                    retreatThreshold = clamp(json.get("retreat_threshold").getAsFloat(), 0f, 1f);
                }
                if (json.has("primary_target")) {
                    String targetStr = json.get("primary_target").getAsString().toUpperCase();
                    primaryTarget = parseTargetPriority(targetStr);
                }

                System.out.println("[StrategicLLMAgent] T=" + currentTime +
                                   ": Updated params - strategy=" + currentStrategy +
                                   ", aggression=" + String.format("%.2f", aggression) +
                                   ", economy=" + String.format("%.2f", economyPriority) +
                                   ", retreat=" + String.format("%.2f", retreatThreshold) +
                                   ", target=" + primaryTarget);
            }
        } catch (Exception e) {
            // Try to parse strategy from plain text
            String upper = response.toUpperCase();
            for (GameStrategy gs : GameStrategy.values()) {
                if (upper.contains(gs.name())) {
                    if (gs != currentStrategy) {
                        switchStrategy(gs, currentTime);
                    }
                    break;
                }
            }
        }
    }

    /**
     * Parse strategy string to enum
     */
    private GameStrategy parseStrategyString(String s) {
        try {
            return GameStrategy.valueOf(s);
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    /**
     * Parse target priority string to enum
     */
    private TargetPriority parseTargetPriority(String s) {
        try {
            return TargetPriority.valueOf(s);
        } catch (IllegalArgumentException e) {
            return TargetPriority.BASE;
        }
    }

    /**
     * Clamp float value to range
     */
    private float clamp(float value, float min, float max) {
        return Math.max(min, Math.min(max, value));
    }

    // Getters for testing/debugging
    public GameStrategy getCurrentStrategy() { return currentStrategy; }
    public float getAggression() { return aggression; }
    public float getEconomyPriority() { return economyPriority; }
    public float getRetreatThreshold() { return retreatThreshold; }
    public TargetPriority getPrimaryTarget() { return primaryTarget; }
    public int getStrategyChanges() { return strategyChanges; }
    public int getLLMConsultations() { return llmConsultations; }
    public int getLLMErrors() { return llmErrors; }

    // Setters for testing/debugging
    public void setStrategy(GameStrategy strategy) { this.currentStrategy = strategy; }
    public void setAggression(float value) { this.aggression = clamp(value, 0f, 1f); }
    public void setEconomyPriority(float value) { this.economyPriority = clamp(value, 0f, 1f); }
    public void setRetreatThreshold(float value) { this.retreatThreshold = clamp(value, 0f, 1f); }
    public void setPrimaryTarget(TargetPriority target) { this.primaryTarget = target; }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }

    @Override
    public String toString() {
        return "StrategicLLMAgent(model=" + MODEL +
               ", strategy=" + currentStrategy +
               ", aggression=" + String.format("%.2f", aggression) +
               ", economy=" + String.format("%.2f", economyPriority) +
               ", retreat=" + String.format("%.2f", retreatThreshold) +
               ", target=" + primaryTarget +
               ", changes=" + strategyChanges +
               ", consultations=" + llmConsultations +
               ", errors=" + llmErrors + ")";
    }
}
