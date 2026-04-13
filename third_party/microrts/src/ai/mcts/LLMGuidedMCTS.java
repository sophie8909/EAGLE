package ai.mcts;

import ai.RandomBiasedAI;
import ai.core.AI;
import ai.core.ParameterSpecification;
import ai.evaluation.EvaluationFunction;
import ai.evaluation.LLMStrategicEvaluation;
import ai.evaluation.LLMStrategicEvaluation.StrategicGoal;
import ai.mcts.naivemcts.NaiveMCTS;

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
 * LLMGuidedMCTS: Monte Carlo Tree Search guided by LLM strategic advice.
 *
 * This agent combines the tactical precision of MCTS with LLM strategic reasoning:
 * - LLM is consulted once per search (not per iteration) to provide strategic guidance
 * - Strategic guidance biases tree search toward strategically sound actions
 * - MCTS handles tactical execution and lookahead
 *
 * Architecture:
 * - LLM provides: strategy, aggression, economy_priority, target_priority
 * - These parameters adjust the evaluation function weights
 * - MCTS uses the adjusted evaluation for tree search
 *
 * Benefits over pure LLM:
 * - Much fewer LLM calls (1 per getAction vs N per tick)
 * - MCTS provides tactical lookahead the LLM cannot
 * - Combines LLM knowledge with computational search
 *
 * Benefits over pure MCTS:
 * - LLM provides high-level strategic context
 * - Biases search toward strategically sound regions
 * - Adapts strategy based on game state analysis
 */
public class LLMGuidedMCTS extends NaiveMCTS {

    // LLM Configuration
    private static final String OLLAMA_HOST =
            System.getenv().getOrDefault("OLLAMA_HOST", "http://localhost:11434");
    private static final String MODEL =
            System.getenv().getOrDefault("OLLAMA_MODEL", "llama3.1:8b");
    private static final int LLM_INTERVAL =
            Integer.parseInt(System.getenv().getOrDefault("MCTS_LLM_INTERVAL", "500"));

    // Strategic state from LLM
    private String currentStrategy = "BALANCED";
    private float aggression = 0.5f;
    private float economyPriority = 0.5f;
    private String targetPriority = "BASE";

    // Goal-based strategic state (new)
    private StrategicGoal primaryGoal = StrategicGoal.BUILD_ARMY;
    private StrategicGoal secondaryGoal = StrategicGoal.EXPAND_ECONOMY;
    private boolean useGoalBasedGuidance = true; // Toggle between parameter-based and goal-based

    // LLM consultation tracking
    private int lastLLMConsultation = -9999;
    private int llmConsultations = 0;
    private int llmErrors = 0;

    // Reference types
    protected UnitTypeTable utt;

    // Custom evaluation function that uses LLM weights
    private LLMStrategicEvaluation strategicEval;

    /**
     * Constructor with UnitTypeTable
     */
    public LLMGuidedMCTS(UnitTypeTable a_utt) {
        // Use longer time budget for LLM-guided search (200ms vs 100ms default)
        // More iterations with strategic guidance = better results
        super(200, -1, 100, 10,
              0.3f, 0.0f, 0.4f,
              new RandomBiasedAI(),
              new LLMStrategicEvaluation(a_utt), true);

        this.utt = a_utt;
        this.strategicEval = (LLMStrategicEvaluation) this.ef;

        System.out.println("[LLMGuidedMCTS] Initialized with model=" + MODEL +
                           ", time_budget=" + TIME_BUDGET +
                           ", llm_interval=" + LLM_INTERVAL);
    }

    /**
     * Full constructor with all parameters
     */
    public LLMGuidedMCTS(UnitTypeTable a_utt, int available_time, int max_playouts,
                         int lookahead, int max_depth,
                         float e_l, float e_g, float e_0,
                         AI policy, boolean fensa) {
        super(available_time, max_playouts, lookahead, max_depth,
              e_l, e_g, e_0,
              policy,
              new LLMStrategicEvaluation(a_utt), fensa);

        this.utt = a_utt;
        this.strategicEval = (LLMStrategicEvaluation) this.ef;
    }

    @Override
    public void reset() {
        super.reset();
        lastLLMConsultation = -9999;
    }

    @Override
    public AI clone() {
        LLMGuidedMCTS clone = new LLMGuidedMCTS(utt, TIME_BUDGET, ITERATIONS_BUDGET,
                                                 MAXSIMULATIONTIME, MAX_TREE_DEPTH,
                                                 epsilon_l, epsilon_g, epsilon_0,
                                                 playoutPolicy, forceExplorationOfNonSampledActions);
        clone.currentStrategy = this.currentStrategy;
        clone.aggression = this.aggression;
        clone.economyPriority = this.economyPriority;
        clone.targetPriority = this.targetPriority;
        return clone;
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        if (!gs.canExecuteAnyAction(player)) {
            return new PlayerAction();
        }

        int currentTime = gs.getTime();

        // Consult LLM for strategic guidance (once per interval)
        if (currentTime - lastLLMConsultation >= LLM_INTERVAL) {
            consultLLMForStrategy(player, gs);
            lastLLMConsultation = currentTime;
        }

        // Update evaluation function with current strategic weights
        if (useGoalBasedGuidance) {
            strategicEval.updateStrategicGoals(primaryGoal, secondaryGoal);
        } else {
            strategicEval.updateStrategicWeights(aggression, economyPriority, targetPriority);
        }

        // Run MCTS with LLM-biased evaluation
        return super.getAction(player, gs);
    }

    /**
     * Consult the LLM for strategic guidance
     */
    private void consultLLMForStrategy(int player, GameState gs) {
        llmConsultations++;

        try {
            String prompt = buildStrategicPrompt(player, gs);
            String response = callOllamaAPI(prompt);
            parseStrategicResponse(response, gs.getTime());
        } catch (Exception e) {
            llmErrors++;
            System.err.println("[LLMGuidedMCTS] LLM consultation failed: " + e.getMessage());
            // Keep current strategy on error
        }
    }

    /**
     * Build strategic prompt for LLM
     */
    private String buildStrategicPrompt(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);
        int enemyPlayer = 1 - player;

        // Count units
        int myWorkers = 0, myLight = 0, myHeavy = 0, myRanged = 0;
        int myBases = 0, myBarracks = 0;
        int enemyWorkers = 0, enemyLight = 0, enemyHeavy = 0, enemyRanged = 0;
        int enemyBases = 0, enemyBarracks = 0;
        int neutralResources = 0;

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
            } else if (u.getPlayer() == -1 && u.getType().isResource) {
                neutralResources++;
            }
        }

        // Strength calculation
        int myStrength = myWorkers + myLight * 2 + myHeavy * 4 + myRanged * 2;
        int enemyStrength = enemyWorkers + enemyLight * 2 + enemyHeavy * 4 + enemyRanged * 2;

        // Game phase
        int maxCycles = 5000;
        String gamePhase;
        if (gs.getTime() < maxCycles / 4) {
            gamePhase = "EARLY";
        } else if (gs.getTime() < maxCycles * 3 / 4) {
            gamePhase = "MID";
        } else {
            gamePhase = "LATE";
        }

        StringBuilder sb = new StringBuilder();
        sb.append("You are a strategic advisor for an RTS game using MCTS search.\n\n");

        sb.append("Your advice will BIAS the Monte Carlo Tree Search, not directly control units.\n");
        sb.append("Choose strategic GOALS to guide the search.\n\n");

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
        sb.append("- Enemy buildings: ").append(enemyBases).append(" base, ");
        sb.append(enemyBarracks).append(" barracks\n");
        sb.append("- Resources on map: ").append(neutralResources).append("\n");
        sb.append("- Strength: You=").append(myStrength).append(", Enemy=").append(enemyStrength).append("\n\n");

        if (useGoalBasedGuidance) {
            sb.append("STRATEGIC GOALS (choose primary and secondary):\n");
            sb.append("- EXPAND_ECONOMY: Prioritize resource gathering and worker production\n");
            sb.append("- BUILD_ARMY: Prioritize military unit production\n");
            sb.append("- ATTACK_BASE: Focus on destroying enemy base\n");
            sb.append("- ATTACK_WORKERS: Focus on killing enemy workers\n");
            sb.append("- DEFEND: Protect own base and units\n");
            sb.append("- CONTROL_RESOURCES: Control resource nodes on the map\n\n");

            sb.append("Reply with JSON:\n");
            sb.append("{\n");
            sb.append("  \"primary_goal\": \"BUILD_ARMY\",\n");
            sb.append("  \"secondary_goal\": \"EXPAND_ECONOMY\",\n");
            sb.append("  \"reasoning\": \"brief explanation\"\n");
            sb.append("}\n");
        } else {
            sb.append("STRATEGIES:\n");
            sb.append("- AGGRESSIVE: High aggression, attack immediately\n");
            sb.append("- DEFENSIVE: Build up forces before attacking\n");
            sb.append("- ECONOMIC: Focus on resource gathering\n");
            sb.append("- BALANCED: Mix of offense and economy\n");
            sb.append("- RUSH: All-in early attack\n\n");

            sb.append("Reply with JSON:\n");
            sb.append("{\n");
            sb.append("  \"strategy\": \"BALANCED\",\n");
            sb.append("  \"aggression\": 0.5,\n");
            sb.append("  \"economy_priority\": 0.5,\n");
            sb.append("  \"target_priority\": \"BASE\"\n");
            sb.append("}\n");
            sb.append("\nTarget options: BASE, WORKERS, ARMY\n");
        }

        return sb.toString();
    }

    /**
     * Call Ollama API
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

        JsonObject top = JsonParser.parseString(sb.toString()).getAsJsonObject();
        if (top.has("response") && !top.get("response").getAsString().isEmpty()) {
            return top.get("response").getAsString();
        }
        throw new IOException("No response field in Ollama output");
    }

    /**
     * Parse LLM response
     */
    private void parseStrategicResponse(String response, int currentTime) {
        if (response == null || response.isEmpty()) return;

        try {
            String cleaned = response.trim();
            if (cleaned.startsWith("{")) {
                JsonObject json = JsonParser.parseString(cleaned).getAsJsonObject();

                if (useGoalBasedGuidance) {
                    // Parse goal-based response
                    if (json.has("primary_goal")) {
                        String newPrimaryGoal = json.get("primary_goal").getAsString().toUpperCase();
                        StrategicGoal newGoal = parseGoal(newPrimaryGoal);
                        if (newGoal != null && newGoal != primaryGoal) {
                            System.out.println("[LLMGuidedMCTS] T=" + currentTime +
                                               ": Primary goal switch " + primaryGoal + " -> " + newGoal);
                            primaryGoal = newGoal;
                        }
                    }

                    if (json.has("secondary_goal")) {
                        String newSecondaryGoal = json.get("secondary_goal").getAsString().toUpperCase();
                        StrategicGoal newGoal = parseGoal(newSecondaryGoal);
                        if (newGoal != null) {
                            secondaryGoal = newGoal;
                        }
                    }

                    String reasoning = json.has("reasoning") ?
                            json.get("reasoning").getAsString() : "";

                    System.out.println("[LLMGuidedMCTS] T=" + currentTime +
                                       ": Goals - primary=" + primaryGoal +
                                       ", secondary=" + secondaryGoal +
                                       (reasoning.isEmpty() ? "" : " (" + reasoning + ")"));
                } else {
                    // Parse parameter-based response
                    if (json.has("strategy")) {
                        String newStrategy = json.get("strategy").getAsString().toUpperCase();
                        if (!newStrategy.equals(currentStrategy)) {
                            System.out.println("[LLMGuidedMCTS] T=" + currentTime +
                                               ": Strategy switch " + currentStrategy + " -> " + newStrategy);
                            currentStrategy = newStrategy;
                        }
                    }

                    if (json.has("aggression")) {
                        aggression = clamp(json.get("aggression").getAsFloat(), 0f, 1f);
                    }
                    if (json.has("economy_priority")) {
                        economyPriority = clamp(json.get("economy_priority").getAsFloat(), 0f, 1f);
                    }
                    if (json.has("target_priority")) {
                        targetPriority = json.get("target_priority").getAsString().toUpperCase();
                    }

                    System.out.println("[LLMGuidedMCTS] T=" + currentTime +
                                       ": Updated - strategy=" + currentStrategy +
                                       ", aggression=" + String.format("%.2f", aggression) +
                                       ", economy=" + String.format("%.2f", economyPriority) +
                                       ", target=" + targetPriority);
                }
            }
        } catch (Exception e) {
            System.err.println("[LLMGuidedMCTS] Failed to parse response: " + e.getMessage());
        }
    }

    /**
     * Parse a goal string to StrategicGoal enum
     */
    private StrategicGoal parseGoal(String goalStr) {
        if (goalStr == null) return null;
        try {
            return StrategicGoal.valueOf(goalStr.toUpperCase().replace(" ", "_"));
        } catch (IllegalArgumentException e) {
            System.err.println("[LLMGuidedMCTS] Unknown goal: " + goalStr);
            return null;
        }
    }

    private float clamp(float value, float min, float max) {
        return Math.max(min, Math.min(max, value));
    }

    // Getters
    public String getCurrentStrategy() { return currentStrategy; }
    public float getAggression() { return aggression; }
    public float getEconomyPriority() { return economyPriority; }
    public String getTargetPriority() { return targetPriority; }
    public int getLLMConsultations() { return llmConsultations; }
    public int getLLMErrors() { return llmErrors; }
    public StrategicGoal getPrimaryGoal() { return primaryGoal; }
    public StrategicGoal getSecondaryGoal() { return secondaryGoal; }
    public boolean isUsingGoalBasedGuidance() { return useGoalBasedGuidance; }
    public void setUseGoalBasedGuidance(boolean use) { this.useGoalBasedGuidance = use; }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = super.getParameters();
        // Add LLM-specific parameters if needed
        return parameters;
    }

    @Override
    public String toString() {
        if (useGoalBasedGuidance) {
            return "LLMGuidedMCTS(model=" + MODEL +
                   ", primary_goal=" + primaryGoal +
                   ", secondary_goal=" + secondaryGoal +
                   ", consultations=" + llmConsultations +
                   ", errors=" + llmErrors + ")";
        } else {
            return "LLMGuidedMCTS(model=" + MODEL +
                   ", strategy=" + currentStrategy +
                   ", aggression=" + String.format("%.2f", aggression) +
                   ", economy=" + String.format("%.2f", economyPriority) +
                   ", target=" + targetPriority +
                   ", consultations=" + llmConsultations +
                   ", errors=" + llmErrors + ")";
        }
    }

    @Override
    public String statisticsString() {
        return super.statisticsString() +
               ", LLM consultations: " + llmConsultations +
               ", LLM errors: " + llmErrors;
    }
}
