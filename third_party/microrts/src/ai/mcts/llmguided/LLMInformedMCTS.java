package ai.mcts.llmguided;

import ai.RandomBiasedAI;
import ai.core.AI;
import ai.core.AIWithComputationBudget;
import ai.core.ParameterSpecification;
import ai.evaluation.EvaluationFunction;
import ai.evaluation.LLMStrategicEvaluation;
import ai.evaluation.LLMStrategicEvaluation.StrategicGoal;
import ai.mcts.informedmcts.InformedNaiveMCTS;
import ai.mcts.informedmcts.InformedNaiveMCTSNode;
import ai.stochastic.LLMPolicyProbabilityDistribution;
import ai.stochastic.UnitActionProbabilityDistribution;
import ai.core.InterruptibleAI;

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
 * LLMInformedMCTS: Monte Carlo Tree Search with LLM-guided policy priors.
 *
 * This agent combines MCTS with LLM-provided policy priors, similar to how
 * AlphaGo uses neural network priors to guide tree search. The key innovations:
 *
 * 1. Policy Priors: LLM provides action probability distributions that bias
 *    tree exploration toward promising actions, reducing effective branching factor.
 *
 * 2. Strategic Goals: LLM provides high-level strategic goals that adjust the
 *    evaluation function weights.
 *
 * 3. Cached Priors: Policy priors are cached and reused across many MCTS iterations,
 *    minimizing LLM calls while maximizing search quality.
 *
 * Architecture:
 * - LLMPolicyProbabilityDistribution provides per-unit action priors
 * - LLMStrategicEvaluation provides goal-biased state evaluation
 * - InformedNaiveMCTS tree search uses both for exploration and evaluation
 *
 * LLM Consultation Schedule:
 * - Policy priors: Updated every 200-500 game ticks
 * - Strategic goals: Updated every 500 game ticks
 * - Total LLM calls: ~2-3 per 500 ticks (much fewer than pure LLM agents)
 */
public class LLMInformedMCTS extends AIWithComputationBudget implements InterruptibleAI {

    public static int DEBUG = 0;

    // LLM Configuration
    private static final String OLLAMA_HOST =
            System.getenv().getOrDefault("OLLAMA_HOST", "http://localhost:11434");
    private static final String MODEL =
            System.getenv().getOrDefault("OLLAMA_MODEL", "llama3.1:8b");
    private static final int GOAL_UPDATE_INTERVAL =
            Integer.parseInt(System.getenv().getOrDefault("MCTS_GOAL_INTERVAL", "500"));

    // MCTS Parameters
    public int MAXSIMULATIONTIME = 100;
    public int MAX_TREE_DEPTH = 10;
    public float epsilon_0 = 0.4f;
    public float epsilon_l = 0.3f;
    public float epsilon_g = 0.0f;
    public int global_strategy = InformedNaiveMCTSNode.E_GREEDY;

    // Components
    protected UnitTypeTable utt;
    protected AI playoutPolicy;
    protected LLMPolicyProbabilityDistribution policyPriors;
    protected LLMStrategicEvaluation strategicEval;

    // Tree state
    protected GameState gs_to_start_from;
    protected InformedNaiveMCTSNode tree;
    protected int current_iteration = 0;
    protected int player;
    protected long max_actions_so_far = 0;

    // Strategic goals
    private StrategicGoal primaryGoal = StrategicGoal.BUILD_ARMY;
    private StrategicGoal secondaryGoal = StrategicGoal.EXPAND_ECONOMY;
    private int lastGoalUpdate = -9999;

    // Statistics
    public long total_runs = 0;
    public long total_cycles_executed = 0;
    public long total_actions_issued = 0;
    public long total_time = 0;
    private int goalConsultations = 0;
    private int goalErrors = 0;

    /**
     * Constructor with UnitTypeTable
     */
    public LLMInformedMCTS(UnitTypeTable a_utt) {
        super(200, -1); // 200ms time budget

        this.utt = a_utt;
        this.playoutPolicy = new RandomBiasedAI();
        this.policyPriors = new LLMPolicyProbabilityDistribution(a_utt);
        this.strategicEval = new LLMStrategicEvaluation(a_utt);

        System.out.println("[LLMInformedMCTS] Initialized with model=" + MODEL +
                           ", time_budget=" + TIME_BUDGET +
                           ", goal_interval=" + GOAL_UPDATE_INTERVAL);
    }

    /**
     * Full constructor with all parameters
     */
    public LLMInformedMCTS(UnitTypeTable a_utt, int available_time, int max_playouts,
                           int lookahead, int max_depth,
                           float e_l, float e_g, float e_0,
                           AI policy) {
        super(available_time, max_playouts);

        this.utt = a_utt;
        this.MAXSIMULATIONTIME = lookahead;
        this.MAX_TREE_DEPTH = max_depth;
        this.epsilon_l = e_l;
        this.epsilon_g = e_g;
        this.epsilon_0 = e_0;
        this.playoutPolicy = policy;
        this.policyPriors = new LLMPolicyProbabilityDistribution(a_utt);
        this.strategicEval = new LLMStrategicEvaluation(a_utt);
    }

    @Override
    public void reset() {
        tree = null;
        gs_to_start_from = null;
        total_runs = 0;
        total_cycles_executed = 0;
        total_actions_issued = 0;
        total_time = 0;
        current_iteration = 0;
        lastGoalUpdate = -9999;
    }

    @Override
    public AI clone() {
        LLMInformedMCTS clone = new LLMInformedMCTS(utt, TIME_BUDGET, ITERATIONS_BUDGET,
                                                     MAXSIMULATIONTIME, MAX_TREE_DEPTH,
                                                     epsilon_l, epsilon_g, epsilon_0,
                                                     playoutPolicy);
        clone.primaryGoal = this.primaryGoal;
        clone.secondaryGoal = this.secondaryGoal;
        return clone;
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        if (gs.canExecuteAnyAction(player)) {
            // Update strategic goals periodically
            int currentTime = gs.getTime();
            if (currentTime - lastGoalUpdate >= GOAL_UPDATE_INTERVAL) {
                updateStrategicGoals(player, gs);
                lastGoalUpdate = currentTime;
            }

            // Update evaluation function with current goals
            strategicEval.updateStrategicGoals(primaryGoal, secondaryGoal);

            // Run MCTS
            startNewComputation(player, gs.clone());
            computeDuringOneGameFrame();
            return getBestActionSoFar();
        } else {
            return new PlayerAction();
        }
    }

    public void startNewComputation(int a_player, GameState gs) throws Exception {
        player = a_player;
        current_iteration = 0;

        // Create tree root with LLM policy priors
        tree = new InformedNaiveMCTSNode(player, 1-player, gs, policyPriors, null,
                                          strategicEval.upperBound(gs), current_iteration++);

        if (tree.moveGenerator == null) {
            max_actions_so_far = 0;
        } else {
            max_actions_so_far = Math.max(tree.moveGenerator.getSize(), max_actions_so_far);
        }
        gs_to_start_from = gs;
    }

    public void resetSearch() {
        if (DEBUG >= 2) System.out.println("Resetting search...");
        tree = null;
        gs_to_start_from = null;
    }

    public void computeDuringOneGameFrame() throws Exception {
        if (DEBUG >= 2) System.out.println("Search...");
        long start = System.currentTimeMillis();
        long end = start;
        long count = 0;

        while (true) {
            if (!iteration(player)) break;
            count++;
            end = System.currentTimeMillis();
            if (TIME_BUDGET >= 0 && (end - start) >= TIME_BUDGET) break;
            if (ITERATIONS_BUDGET >= 0 && count >= ITERATIONS_BUDGET) break;
        }

        total_time += (end - start);
        total_cycles_executed++;
    }

    public boolean iteration(int player) throws Exception {
        InformedNaiveMCTSNode leaf = tree.selectLeaf(player, 1-player,
                                                      epsilon_l, epsilon_g, epsilon_0,
                                                      global_strategy, MAX_TREE_DEPTH,
                                                      current_iteration++);

        if (leaf != null) {
            GameState gs2 = leaf.gs.clone();
            simulate(gs2, gs2.getTime() + MAXSIMULATIONTIME);

            int time = gs2.getTime() - gs_to_start_from.getTime();
            double evaluation = strategicEval.evaluate(player, 1-player, gs2) *
                               Math.pow(0.99, time/10.0);

            leaf.propagateEvaluation(evaluation, null);
            total_runs++;
        } else {
            System.err.println(this.getClass().getSimpleName() +
                               ": claims there are no more leafs to explore...");
            return false;
        }
        return true;
    }

    public void simulate(GameState gs, int time) throws Exception {
        boolean gameover = false;

        do {
            if (gs.isComplete()) {
                gameover = gs.cycle();
            } else {
                gs.issue(playoutPolicy.getAction(0, gs));
                gs.issue(playoutPolicy.getAction(1, gs));
            }
        } while (!gameover && gs.getTime() < time);
    }

    public PlayerAction getBestActionSoFar() {
        int idx = getMostVisitedActionIdx();
        if (idx == -1) {
            if (DEBUG >= 1) System.out.println("LLMInformedMCTS no children selected. Returning empty action");
            return new PlayerAction();
        }
        if (DEBUG >= 2) tree.showNode(0, 1, strategicEval);
        if (DEBUG >= 1) {
            InformedNaiveMCTSNode best = (InformedNaiveMCTSNode) tree.children.get(idx);
            System.out.println("LLMInformedMCTS selected: " + tree.actions.get(idx) +
                               " explored " + best.visit_count +
                               " avg_eval: " + (best.accum_evaluation / best.visit_count));
        }
        return tree.actions.get(idx);
    }

    public int getMostVisitedActionIdx() {
        total_actions_issued++;

        int bestIdx = -1;
        InformedNaiveMCTSNode best = null;

        if (DEBUG >= 2) {
            System.out.println("Number of playouts: " + tree.visit_count);
            tree.printUnitActionTable();
        }

        if (tree.children == null) return -1;

        for (int i = 0; i < tree.children.size(); i++) {
            InformedNaiveMCTSNode child = (InformedNaiveMCTSNode) tree.children.get(i);
            if (DEBUG >= 2) {
                System.out.println("child " + tree.actions.get(i) +
                                   " explored " + child.visit_count +
                                   " avg_eval: " + (child.accum_evaluation / child.visit_count));
            }
            if (best == null || child.visit_count > best.visit_count) {
                best = child;
                bestIdx = i;
            }
        }

        return bestIdx;
    }

    /**
     * Update strategic goals from LLM
     */
    private void updateStrategicGoals(int player, GameState gs) {
        goalConsultations++;

        try {
            String prompt = buildGoalPrompt(player, gs);
            String response = callOllamaAPI(prompt);
            parseGoalResponse(response, gs.getTime());
        } catch (Exception e) {
            goalErrors++;
            System.err.println("[LLMInformedMCTS] Goal consultation failed: " + e.getMessage());
        }
    }

    /**
     * Build prompt for strategic goal selection
     */
    private String buildGoalPrompt(int player, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);
        int enemyPlayer = 1 - player;

        int myWorkers = 0, myMilitary = 0, myBases = 0, myBarracks = 0;
        int enemyWorkers = 0, enemyMilitary = 0, enemyBases = 0;

        for (Unit u : pgs.getUnits()) {
            UnitType ut = u.getType();
            if (u.getPlayer() == player) {
                if (ut.canHarvest) myWorkers++;
                else if (ut.canAttack && !ut.isStockpile) myMilitary++;
                if (ut.isStockpile) myBases++;
                if (ut.name.equals("Barracks")) myBarracks++;
            } else if (u.getPlayer() == enemyPlayer) {
                if (ut.canHarvest) enemyWorkers++;
                else if (ut.canAttack && !ut.isStockpile) enemyMilitary++;
                if (ut.isStockpile) enemyBases++;
            }
        }

        int maxCycles = 5000;
        String phase = gs.getTime() < maxCycles/4 ? "EARLY" :
                       gs.getTime() < maxCycles*3/4 ? "MID" : "LATE";

        StringBuilder sb = new StringBuilder();
        sb.append("You are a strategic advisor for an RTS game using MCTS with policy priors.\n\n");
        sb.append("Select strategic goals to guide the search.\n\n");

        sb.append("GAME STATE:\n");
        sb.append("- Phase: ").append(phase).append("\n");
        sb.append("- Resources: ").append(p.getResources()).append("\n");
        sb.append("- Your units: ").append(myWorkers).append(" workers, ");
        sb.append(myMilitary).append(" military, ");
        sb.append(myBases).append(" bases, ").append(myBarracks).append(" barracks\n");
        sb.append("- Enemy: ").append(enemyWorkers).append(" workers, ");
        sb.append(enemyMilitary).append(" military, ").append(enemyBases).append(" bases\n\n");

        sb.append("GOALS:\n");
        sb.append("- EXPAND_ECONOMY: Resource gathering and worker production\n");
        sb.append("- BUILD_ARMY: Military unit production\n");
        sb.append("- ATTACK_BASE: Focus on destroying enemy base\n");
        sb.append("- ATTACK_WORKERS: Kill enemy workers\n");
        sb.append("- DEFEND: Protect own base\n");
        sb.append("- CONTROL_RESOURCES: Control resource nodes\n\n");

        sb.append("Reply with JSON:\n");
        sb.append("{\"primary_goal\": \"BUILD_ARMY\", \"secondary_goal\": \"EXPAND_ECONOMY\"}\n");

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
     * Parse goal response from LLM
     */
    private void parseGoalResponse(String response, int currentTime) {
        if (response == null || response.isEmpty()) return;

        try {
            String cleaned = response.trim();
            if (cleaned.startsWith("{")) {
                JsonObject json = JsonParser.parseString(cleaned).getAsJsonObject();

                if (json.has("primary_goal")) {
                    String goalStr = json.get("primary_goal").getAsString().toUpperCase();
                    try {
                        StrategicGoal newGoal = StrategicGoal.valueOf(goalStr);
                        if (newGoal != primaryGoal) {
                            System.out.println("[LLMInformedMCTS] T=" + currentTime +
                                               ": Primary goal: " + primaryGoal + " -> " + newGoal);
                            primaryGoal = newGoal;
                        }
                    } catch (IllegalArgumentException e) {
                        // Unknown goal, keep current
                    }
                }

                if (json.has("secondary_goal")) {
                    String goalStr = json.get("secondary_goal").getAsString().toUpperCase();
                    try {
                        secondaryGoal = StrategicGoal.valueOf(goalStr);
                    } catch (IllegalArgumentException e) {
                        // Unknown goal, keep current
                    }
                }
            }
        } catch (Exception e) {
            System.err.println("[LLMInformedMCTS] Failed to parse goal response: " + e.getMessage());
        }
    }

    // Getters
    public InformedNaiveMCTSNode getTree() { return tree; }
    public GameState getGameStateToStartFrom() { return gs_to_start_from; }
    public StrategicGoal getPrimaryGoal() { return primaryGoal; }
    public StrategicGoal getSecondaryGoal() { return secondaryGoal; }
    public int getGoalConsultations() { return goalConsultations; }
    public int getGoalErrors() { return goalErrors; }
    public LLMPolicyProbabilityDistribution getPolicyPriors() { return policyPriors; }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("TimeBudget", int.class, 200));
        parameters.add(new ParameterSpecification("IterationsBudget", int.class, -1));
        parameters.add(new ParameterSpecification("PlayoutLookahead", int.class, 100));
        parameters.add(new ParameterSpecification("MaxTreeDepth", int.class, 10));
        parameters.add(new ParameterSpecification("E_l", float.class, 0.3));
        parameters.add(new ParameterSpecification("E_g", float.class, 0.0));
        parameters.add(new ParameterSpecification("E_0", float.class, 0.4));
        parameters.add(new ParameterSpecification("DefaultPolicy", AI.class, playoutPolicy));
        return parameters;
    }

    @Override
    public String toString() {
        return "LLMInformedMCTS(model=" + MODEL +
               ", primary_goal=" + primaryGoal +
               ", secondary_goal=" + secondaryGoal +
               ", goal_consultations=" + goalConsultations +
               ", prior_consultations=" + policyPriors.getPriorConsultations() + ")";
    }

    @Override
    public String statisticsString() {
        return "Total runs: " + total_runs +
               ", runs per action: " + (total_runs / (float) total_actions_issued) +
               ", runs per cycle: " + (total_runs / (float) total_cycles_executed) +
               ", avg time per cycle: " + (total_time / (float) total_cycles_executed) +
               ", max branching: " + max_actions_so_far +
               ", goal consultations: " + goalConsultations +
               ", prior consultations: " + policyPriors.getPriorConsultations();
    }
}
