package ai.stochastic;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

import com.google.gson.*;

import rts.GameState;
import rts.PhysicalGameState;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitType;
import rts.units.UnitTypeTable;

/**
 * LLMPolicyProbabilityDistribution: LLM-guided action probability distribution.
 *
 * This class provides policy priors for MCTS tree exploration, similar to how
 * AlphaGo uses neural networks to guide search. The LLM provides prior probabilities
 * that bias the tree search toward promising actions.
 *
 * Situation Classification:
 * - worker_near_resource: Workers within 3 cells of a resource node
 * - worker_no_resource: Workers not near resources
 * - worker_carrying: Workers carrying resources
 * - military_combat: Combat units adjacent to enemies
 * - military_no_combat: Combat units not in immediate combat
 * - base_economy: Base with resources available
 * - base_low_resources: Base with low resources
 * - barracks: Barracks building
 *
 * The LLM is consulted periodically to update cached priors, which are then
 * used during tree expansion without additional LLM calls.
 */
public class LLMPolicyProbabilityDistribution extends UnitActionProbabilityDistribution {

    // LLM Configuration
    private static final String OLLAMA_HOST =
            System.getenv().getOrDefault("OLLAMA_HOST", "http://localhost:11434");
    private static final String MODEL =
            System.getenv().getOrDefault("OLLAMA_MODEL", "llama3.1:8b");
    private static final int PRIOR_CACHE_DURATION =
            Integer.parseInt(System.getenv().getOrDefault("MCTS_PRIOR_CACHE_DURATION", "300"));

    // Situation types for caching
    public enum SituationType {
        WORKER_NEAR_RESOURCE,
        WORKER_NO_RESOURCE,
        WORKER_CARRYING,
        MILITARY_COMBAT,
        MILITARY_NO_COMBAT,
        BASE_ECONOMY,
        BASE_LOW_RESOURCES,
        BARRACKS
    }

    // Cached priors by situation type
    // Maps: SituationType -> (ActionType -> relative probability)
    private Map<SituationType, Map<Integer, Double>> cachedPriors = new HashMap<>();

    // Last time priors were updated
    private int lastPriorUpdate = -9999;

    // Consultation statistics
    private int priorConsultations = 0;
    private int priorErrors = 0;

    // Fallback uniform distribution
    private boolean useFallback = false;

    public LLMPolicyProbabilityDistribution(UnitTypeTable a_utt) {
        super(a_utt);
        initializeDefaultPriors();
    }

    /**
     * Initialize default priors for each situation type.
     * These are used until the LLM provides updated priors.
     */
    private void initializeDefaultPriors() {
        // Worker near resource: prioritize harvest
        Map<Integer, Double> workerNearResource = new HashMap<>();
        workerNearResource.put(UnitAction.TYPE_HARVEST, 0.6);
        workerNearResource.put(UnitAction.TYPE_MOVE, 0.2);
        workerNearResource.put(UnitAction.TYPE_PRODUCE, 0.1);
        workerNearResource.put(UnitAction.TYPE_ATTACK_LOCATION, 0.05);
        workerNearResource.put(UnitAction.TYPE_NONE, 0.05);
        cachedPriors.put(SituationType.WORKER_NEAR_RESOURCE, workerNearResource);

        // Worker not near resource: prioritize movement
        Map<Integer, Double> workerNoResource = new HashMap<>();
        workerNoResource.put(UnitAction.TYPE_MOVE, 0.5);
        workerNoResource.put(UnitAction.TYPE_PRODUCE, 0.2);
        workerNoResource.put(UnitAction.TYPE_HARVEST, 0.1);
        workerNoResource.put(UnitAction.TYPE_ATTACK_LOCATION, 0.1);
        workerNoResource.put(UnitAction.TYPE_NONE, 0.1);
        cachedPriors.put(SituationType.WORKER_NO_RESOURCE, workerNoResource);

        // Worker carrying resources: prioritize return
        Map<Integer, Double> workerCarrying = new HashMap<>();
        workerCarrying.put(UnitAction.TYPE_RETURN, 0.7);
        workerCarrying.put(UnitAction.TYPE_MOVE, 0.2);
        workerCarrying.put(UnitAction.TYPE_ATTACK_LOCATION, 0.05);
        workerCarrying.put(UnitAction.TYPE_NONE, 0.05);
        cachedPriors.put(SituationType.WORKER_CARRYING, workerCarrying);

        // Military in combat: prioritize attack
        Map<Integer, Double> militaryCombat = new HashMap<>();
        militaryCombat.put(UnitAction.TYPE_ATTACK_LOCATION, 0.7);
        militaryCombat.put(UnitAction.TYPE_MOVE, 0.2);
        militaryCombat.put(UnitAction.TYPE_NONE, 0.1);
        cachedPriors.put(SituationType.MILITARY_COMBAT, militaryCombat);

        // Military not in combat: prioritize movement toward enemy
        Map<Integer, Double> militaryNoCombat = new HashMap<>();
        militaryNoCombat.put(UnitAction.TYPE_MOVE, 0.6);
        militaryNoCombat.put(UnitAction.TYPE_ATTACK_LOCATION, 0.3);
        militaryNoCombat.put(UnitAction.TYPE_NONE, 0.1);
        cachedPriors.put(SituationType.MILITARY_NO_COMBAT, militaryNoCombat);

        // Base with resources: prioritize training
        Map<Integer, Double> baseEconomy = new HashMap<>();
        baseEconomy.put(UnitAction.TYPE_PRODUCE, 0.8);
        baseEconomy.put(UnitAction.TYPE_NONE, 0.2);
        cachedPriors.put(SituationType.BASE_ECONOMY, baseEconomy);

        // Base with low resources: wait or idle
        Map<Integer, Double> baseLowResources = new HashMap<>();
        baseLowResources.put(UnitAction.TYPE_NONE, 0.6);
        baseLowResources.put(UnitAction.TYPE_PRODUCE, 0.4);
        cachedPriors.put(SituationType.BASE_LOW_RESOURCES, baseLowResources);

        // Barracks: prioritize training military
        Map<Integer, Double> barracks = new HashMap<>();
        barracks.put(UnitAction.TYPE_PRODUCE, 0.8);
        barracks.put(UnitAction.TYPE_NONE, 0.2);
        cachedPriors.put(SituationType.BARRACKS, barracks);
    }

    @Override
    public double[] predictDistribution(Unit u, GameState gs, List<UnitAction> actions) throws Exception {
        int nActions = actions.size();
        if (nActions == 0) {
            return new double[0];
        }

        // Update priors periodically via LLM
        int currentTime = gs.getTime();
        if (currentTime - lastPriorUpdate >= PRIOR_CACHE_DURATION) {
            updatePriorsFromLLM(gs);
            lastPriorUpdate = currentTime;
        }

        // Classify the situation for this unit
        SituationType situation = classifySituation(u, gs);

        // Get cached priors for this situation
        Map<Integer, Double> priors = cachedPriors.getOrDefault(situation, new HashMap<>());

        // Build probability distribution
        double[] distribution = new double[nActions];
        double total = 0;

        for (int i = 0; i < nActions; i++) {
            UnitAction action = actions.get(i);
            int actionType = action.getType();

            // Get prior probability for this action type
            double prior = priors.getOrDefault(actionType, 0.1);

            // Apply action-specific adjustments
            prior = adjustPriorForAction(prior, action, u, gs, situation);

            distribution[i] = prior;
            total += prior;
        }

        // Normalize to sum to 1.0
        if (total > 0) {
            for (int i = 0; i < nActions; i++) {
                distribution[i] /= total;
            }
        } else {
            // Fallback to uniform distribution
            for (int i = 0; i < nActions; i++) {
                distribution[i] = 1.0 / nActions;
            }
        }

        return distribution;
    }

    /**
     * Classify the situation for a given unit
     */
    private SituationType classifySituation(Unit u, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        UnitType unitType = u.getType();
        int player = u.getPlayer();

        // Check if unit is a building
        if (unitType.isStockpile) {
            // It's a base
            int resources = gs.getPlayer(player).getResources();
            if (resources >= unitType.produceTime) {
                return SituationType.BASE_ECONOMY;
            } else {
                return SituationType.BASE_LOW_RESOURCES;
            }
        }

        if (unitType.name.equals("Barracks")) {
            return SituationType.BARRACKS;
        }

        // Check if worker
        if (unitType.canHarvest) {
            // Check if carrying resources
            if (u.getResources() > 0) {
                return SituationType.WORKER_CARRYING;
            }

            // Check if near a resource
            for (Unit other : pgs.getUnits()) {
                if (other.getType().isResource) {
                    int dist = Math.abs(u.getX() - other.getX()) + Math.abs(u.getY() - other.getY());
                    if (dist <= 3) {
                        return SituationType.WORKER_NEAR_RESOURCE;
                    }
                }
            }
            return SituationType.WORKER_NO_RESOURCE;
        }

        // Must be military unit
        if (unitType.canAttack) {
            // Check if adjacent to enemy
            for (Unit other : pgs.getUnits()) {
                if (other.getPlayer() != player && other.getPlayer() >= 0) {
                    int dist = Math.abs(u.getX() - other.getX()) + Math.abs(u.getY() - other.getY());
                    if (dist <= unitType.attackRange) {
                        return SituationType.MILITARY_COMBAT;
                    }
                }
            }
            return SituationType.MILITARY_NO_COMBAT;
        }

        // Default
        return SituationType.WORKER_NO_RESOURCE;
    }

    /**
     * Adjust prior probability based on specific action details
     */
    private double adjustPriorForAction(double basePrior, UnitAction action, Unit u,
                                        GameState gs, SituationType situation) {
        PhysicalGameState pgs = gs.getPhysicalGameState();

        switch (action.getType()) {
            case UnitAction.TYPE_MOVE:
                // Boost moves toward objectives
                int targetX = action.getLocationX();
                int targetY = action.getLocationY();

                // Check if move is toward an enemy (for military)
                if (situation == SituationType.MILITARY_NO_COMBAT) {
                    Unit closestEnemy = findClosestEnemy(u, pgs);
                    if (closestEnemy != null) {
                        int distBefore = Math.abs(u.getX() - closestEnemy.getX()) +
                                         Math.abs(u.getY() - closestEnemy.getY());
                        int distAfter = Math.abs(targetX - closestEnemy.getX()) +
                                        Math.abs(targetY - closestEnemy.getY());
                        if (distAfter < distBefore) {
                            return basePrior * 1.5; // Boost moves toward enemy
                        }
                    }
                }

                // Check if move is toward resource (for workers)
                if (situation == SituationType.WORKER_NO_RESOURCE) {
                    Unit closestResource = findClosestResource(u, pgs);
                    if (closestResource != null) {
                        int distBefore = Math.abs(u.getX() - closestResource.getX()) +
                                         Math.abs(u.getY() - closestResource.getY());
                        int distAfter = Math.abs(targetX - closestResource.getX()) +
                                        Math.abs(targetY - closestResource.getY());
                        if (distAfter < distBefore) {
                            return basePrior * 1.5;
                        }
                    }
                }
                break;

            case UnitAction.TYPE_ATTACK_LOCATION:
                // Boost attacks on high-value targets
                Unit target = pgs.getUnitAt(action.getLocationX(), action.getLocationY());
                if (target != null) {
                    if (target.getType().isStockpile) {
                        return basePrior * 2.0; // Prioritize base attacks
                    }
                    if (target.getType().canHarvest) {
                        return basePrior * 1.5; // Prioritize worker kills
                    }
                }
                break;

            case UnitAction.TYPE_PRODUCE:
                // Adjust based on what's being produced
                UnitType producedType = action.getUnitType();
                if (producedType != null) {
                    if (producedType.canHarvest && situation == SituationType.BASE_ECONOMY) {
                        // Prioritize workers early
                        return basePrior * 1.2;
                    }
                    if (producedType.canAttack && !producedType.canHarvest) {
                        // Military units
                        return basePrior * 1.3;
                    }
                }
                break;
        }

        return basePrior;
    }

    /**
     * Find the closest enemy unit
     */
    private Unit findClosestEnemy(Unit u, PhysicalGameState pgs) {
        Unit closest = null;
        int minDist = Integer.MAX_VALUE;

        for (Unit other : pgs.getUnits()) {
            if (other.getPlayer() != u.getPlayer() && other.getPlayer() >= 0) {
                int dist = Math.abs(u.getX() - other.getX()) + Math.abs(u.getY() - other.getY());
                if (dist < minDist) {
                    minDist = dist;
                    closest = other;
                }
            }
        }
        return closest;
    }

    /**
     * Find the closest resource
     */
    private Unit findClosestResource(Unit u, PhysicalGameState pgs) {
        Unit closest = null;
        int minDist = Integer.MAX_VALUE;

        for (Unit other : pgs.getUnits()) {
            if (other.getType().isResource) {
                int dist = Math.abs(u.getX() - other.getX()) + Math.abs(u.getY() - other.getY());
                if (dist < minDist) {
                    minDist = dist;
                    closest = other;
                }
            }
        }
        return closest;
    }

    /**
     * Update priors from LLM based on current game state
     */
    private void updatePriorsFromLLM(GameState gs) {
        if (useFallback) {
            return; // Don't attempt if fallback mode is active
        }

        priorConsultations++;

        try {
            String prompt = buildPriorPrompt(gs);
            String response = callOllamaAPI(prompt);
            parsePriorResponse(response);

            System.out.println("[LLMPolicyPriors] T=" + gs.getTime() + ": Updated priors from LLM");
        } catch (Exception e) {
            priorErrors++;
            System.err.println("[LLMPolicyPriors] LLM consultation failed: " + e.getMessage());

            // After multiple failures, switch to fallback mode
            if (priorErrors > 3) {
                useFallback = true;
                System.out.println("[LLMPolicyPriors] Switching to fallback mode (default priors)");
            }
        }
    }

    /**
     * Build prompt for LLM to provide policy priors
     */
    private String buildPriorPrompt(GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();

        StringBuilder sb = new StringBuilder();
        sb.append("You are providing action probability priors for an RTS game MCTS search.\n\n");
        sb.append("For each situation type, provide relative probabilities for action types.\n");
        sb.append("Higher probability = action is more likely to be good.\n\n");

        sb.append("GAME STATE:\n");
        sb.append("- Map size: ").append(pgs.getWidth()).append("x").append(pgs.getHeight()).append("\n");
        sb.append("- Time: ").append(gs.getTime()).append("\n\n");

        sb.append("SITUATION TYPES:\n");
        sb.append("- WORKER_NEAR_RESOURCE: Worker within 3 cells of resource\n");
        sb.append("- WORKER_NO_RESOURCE: Worker not near resources\n");
        sb.append("- WORKER_CARRYING: Worker carrying resources back to base\n");
        sb.append("- MILITARY_COMBAT: Combat unit adjacent to enemies\n");
        sb.append("- MILITARY_NO_COMBAT: Combat unit not in immediate combat\n");
        sb.append("- BASE_ECONOMY: Base with resources available\n");
        sb.append("- BASE_LOW_RESOURCES: Base with low resources\n");
        sb.append("- BARRACKS: Barracks building\n\n");

        sb.append("ACTION TYPES (integers):\n");
        sb.append("- 0: NONE (idle)\n");
        sb.append("- 1: MOVE\n");
        sb.append("- 2: HARVEST\n");
        sb.append("- 3: RETURN (return resources)\n");
        sb.append("- 4: PRODUCE (train unit)\n");
        sb.append("- 5: ATTACK_LOCATION\n\n");

        sb.append("Reply with JSON mapping situation to action probabilities:\n");
        sb.append("{\n");
        sb.append("  \"WORKER_NEAR_RESOURCE\": {\"2\": 0.6, \"1\": 0.2, \"4\": 0.1, \"5\": 0.05, \"0\": 0.05},\n");
        sb.append("  \"MILITARY_COMBAT\": {\"5\": 0.7, \"1\": 0.2, \"0\": 0.1}\n");
        sb.append("}\n");
        sb.append("\nOnly include situations you want to adjust. Values should sum to ~1.0.\n");

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
     * Parse LLM response and update cached priors
     */
    private void parsePriorResponse(String response) {
        if (response == null || response.isEmpty()) return;

        try {
            String cleaned = response.trim();
            if (cleaned.startsWith("{")) {
                JsonObject json = JsonParser.parseString(cleaned).getAsJsonObject();

                for (SituationType sit : SituationType.values()) {
                    String sitName = sit.name();
                    if (json.has(sitName)) {
                        JsonObject actionProbs = json.getAsJsonObject(sitName);
                        Map<Integer, Double> priors = new HashMap<>();

                        for (String actionKey : actionProbs.keySet()) {
                            try {
                                int actionType = Integer.parseInt(actionKey);
                                double prob = actionProbs.get(actionKey).getAsDouble();
                                priors.put(actionType, prob);
                            } catch (NumberFormatException e) {
                                // Skip invalid action keys
                            }
                        }

                        if (!priors.isEmpty()) {
                            cachedPriors.put(sit, priors);
                        }
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("[LLMPolicyPriors] Failed to parse response: " + e.getMessage());
        }
    }

    // Getters for statistics
    public int getPriorConsultations() { return priorConsultations; }
    public int getPriorErrors() { return priorErrors; }
    public boolean isUsingFallback() { return useFallback; }

    @Override
    public String toString() {
        return "LLMPolicyProbabilityDistribution(model=" + MODEL +
               ", consultations=" + priorConsultations +
               ", errors=" + priorErrors +
               ", fallback=" + useFallback + ")";
    }
}
