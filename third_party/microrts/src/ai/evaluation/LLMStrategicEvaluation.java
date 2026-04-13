package ai.evaluation;

import rts.GameState;
import rts.PhysicalGameState;
import rts.units.*;

import java.util.EnumSet;
import java.util.Set;

/**
 * LLMStrategicEvaluation: Evaluation function that combines base material evaluation
 * with LLM-guided strategic alignment bonuses.
 *
 * The function rewards game states that align with the current strategic priorities
 * set by the LLM, such as:
 * - Military buildup when aggression is high
 * - Economic development when economy priority is high
 * - Target focus bonuses (enemy base damage, worker kills, army destruction)
 * - Goal-progress bonuses for strategic goals
 */
public class LLMStrategicEvaluation extends EvaluationFunction {

    /**
     * Strategic goals that the LLM can prioritize.
     * Each goal adds specific bonuses to the evaluation function.
     */
    public enum StrategicGoal {
        EXPAND_ECONOMY,     // Prioritize resource gathering and worker production
        BUILD_ARMY,         // Prioritize military unit production
        ATTACK_BASE,        // Focus on destroying enemy base
        ATTACK_WORKERS,     // Focus on killing enemy workers
        DEFEND,             // Protect own base and units
        CONTROL_RESOURCES   // Control resource nodes on the map
    }

    // Base evaluation weights (same as SimpleSqrtEvaluationFunction3)
    public static float RESOURCE = 20;
    public static float RESOURCE_IN_WORKER = 10;
    public static float UNIT_BONUS_MULTIPLIER = 40.0f;

    // Goal bonus multiplier
    public static float GOAL_BONUS_MULTIPLIER = 50.0f;

    // Strategic alignment weights
    private float militaryWeight = 1.0f;     // Weight for military units
    private float economyWeight = 1.0f;      // Weight for workers and resources
    private float aggressionBonus = 0.0f;    // Bonus for being near enemy
    private float targetBaseBonus = 0.0f;    // Bonus for damaging enemy base
    private float targetWorkersBonus = 0.0f; // Bonus for killing enemy workers
    private float targetArmyBonus = 0.0f;    // Bonus for destroying enemy army

    // Strategic goals with priorities (higher index = higher priority)
    private Set<StrategicGoal> activeGoals = EnumSet.noneOf(StrategicGoal.class);
    private StrategicGoal primaryGoal = null;

    // Reference to UnitTypeTable for type lookups
    private UnitTypeTable utt;

    public LLMStrategicEvaluation() {
        // Default constructor with balanced weights
    }

    public LLMStrategicEvaluation(UnitTypeTable a_utt) {
        this.utt = a_utt;
    }

    /**
     * Update strategic weights based on LLM guidance
     */
    public void updateStrategicWeights(float aggression, float economyPriority, String targetPriority) {
        // Adjust military vs economy weight based on priorities
        this.militaryWeight = 1.0f + (aggression * 0.5f) - (economyPriority * 0.3f);
        this.economyWeight = 1.0f + (economyPriority * 0.5f) - (aggression * 0.3f);

        // Ensure weights don't go negative
        this.militaryWeight = Math.max(0.5f, this.militaryWeight);
        this.economyWeight = Math.max(0.5f, this.economyWeight);

        // Set aggression bonus
        this.aggressionBonus = aggression * 0.2f;

        // Set target-specific bonuses
        this.targetBaseBonus = 0.0f;
        this.targetWorkersBonus = 0.0f;
        this.targetArmyBonus = 0.0f;

        if (targetPriority != null) {
            switch (targetPriority.toUpperCase()) {
                case "BASE":
                    this.targetBaseBonus = 0.3f;
                    break;
                case "WORKERS":
                    this.targetWorkersBonus = 0.3f;
                    break;
                case "ARMY":
                    this.targetArmyBonus = 0.3f;
                    break;
            }
        }
    }

    /**
     * Update strategic goals based on LLM guidance.
     * Goals are more structured than raw parameters.
     *
     * @param primary The primary goal (highest priority)
     * @param secondary Additional goals to pursue
     */
    public void updateStrategicGoals(StrategicGoal primary, StrategicGoal... secondary) {
        this.activeGoals.clear();
        this.primaryGoal = primary;

        if (primary != null) {
            this.activeGoals.add(primary);
        }
        for (StrategicGoal goal : secondary) {
            if (goal != null) {
                this.activeGoals.add(goal);
            }
        }

        // Auto-adjust weights based on goals
        adjustWeightsFromGoals();
    }

    /**
     * Adjust evaluation weights based on active goals
     */
    private void adjustWeightsFromGoals() {
        // Reset to defaults
        this.militaryWeight = 1.0f;
        this.economyWeight = 1.0f;
        this.aggressionBonus = 0.0f;
        this.targetBaseBonus = 0.0f;
        this.targetWorkersBonus = 0.0f;
        this.targetArmyBonus = 0.0f;

        for (StrategicGoal goal : activeGoals) {
            boolean isPrimary = (goal == primaryGoal);
            float multiplier = isPrimary ? 1.0f : 0.5f;

            switch (goal) {
                case EXPAND_ECONOMY:
                    economyWeight += 0.5f * multiplier;
                    break;
                case BUILD_ARMY:
                    militaryWeight += 0.5f * multiplier;
                    break;
                case ATTACK_BASE:
                    aggressionBonus += 0.2f * multiplier;
                    targetBaseBonus += 0.3f * multiplier;
                    break;
                case ATTACK_WORKERS:
                    aggressionBonus += 0.15f * multiplier;
                    targetWorkersBonus += 0.3f * multiplier;
                    break;
                case DEFEND:
                    // Defensive focus - slightly reduce aggression
                    militaryWeight += 0.3f * multiplier;
                    break;
                case CONTROL_RESOURCES:
                    economyWeight += 0.3f * multiplier;
                    aggressionBonus += 0.1f * multiplier;
                    break;
            }
        }
    }

    /**
     * Get current primary goal
     */
    public StrategicGoal getPrimaryGoal() {
        return primaryGoal;
    }

    /**
     * Get all active goals
     */
    public Set<StrategicGoal> getActiveGoals() {
        return EnumSet.copyOf(activeGoals);
    }

    @Override
    public float evaluate(int maxplayer, int minplayer, GameState gs) {
        float s1 = strategicScore(maxplayer, minplayer, gs);
        float s2 = strategicScore(minplayer, maxplayer, gs);

        if (s1 + s2 == 0) return 0.0f;
        return (2 * s1 / (s1 + s2)) - 1;
    }

    /**
     * Calculate strategic score incorporating LLM priorities
     */
    private float strategicScore(int player, int opponent, GameState gs) {
        PhysicalGameState pgs = gs.getPhysicalGameState();
        float score = gs.getPlayer(player).getResources() * RESOURCE * economyWeight;

        boolean anyunit = false;
        int myMilitaryCount = 0;
        int myWorkerCount = 0;
        int myBarracksCount = 0;
        int myBaseCount = 0;
        float myBaseHP = 0;
        float myBaseTotalHP = 0;
        int enemyWorkerCount = 0;
        int enemyMilitaryCount = 0;
        float enemyBaseHP = 0;
        float enemyBaseTotalHP = 0;
        int neutralResourceCount = 0;
        int myControlledResources = 0; // Resources near my workers

        // First pass: count units and get base info
        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player) {
                anyunit = true;
                if (u.getType().canHarvest) {
                    myWorkerCount++;
                    score += u.getResources() * RESOURCE_IN_WORKER * economyWeight;
                    score += UNIT_BONUS_MULTIPLIER * economyWeight * u.getCost() *
                             Math.sqrt((float) u.getHitPoints() / u.getMaxHitPoints());
                } else if (u.getType().canAttack && !u.getType().isStockpile) {
                    myMilitaryCount++;
                    score += UNIT_BONUS_MULTIPLIER * militaryWeight * u.getCost() *
                             Math.sqrt((float) u.getHitPoints() / u.getMaxHitPoints());
                } else {
                    // Buildings
                    score += UNIT_BONUS_MULTIPLIER * u.getCost() *
                             Math.sqrt((float) u.getHitPoints() / u.getMaxHitPoints());
                    if (u.getType().isStockpile) {
                        myBaseCount++;
                        myBaseHP += u.getHitPoints();
                        myBaseTotalHP += u.getMaxHitPoints();
                    }
                    if (u.getType().name.equals("Barracks")) {
                        myBarracksCount++;
                    }
                }
            } else if (u.getPlayer() == opponent) {
                if (u.getType().canHarvest) {
                    enemyWorkerCount++;
                } else if (u.getType().canAttack && !u.getType().canHarvest) {
                    enemyMilitaryCount++;
                }
                // Track enemy base damage
                if (u.getType().isStockpile) {
                    enemyBaseHP += u.getHitPoints();
                    enemyBaseTotalHP += u.getMaxHitPoints();
                }
            } else if (u.getPlayer() == -1) {
                // Neutral resources
                if (u.getType().isResource) {
                    neutralResourceCount++;
                }
            }
        }

        if (!anyunit) return 0;

        // Count resources near my workers (for CONTROL_RESOURCES goal)
        for (Unit worker : pgs.getUnits()) {
            if (worker.getPlayer() == player && worker.getType().canHarvest) {
                for (Unit resource : pgs.getUnits()) {
                    if (resource.getPlayer() == -1 && resource.getType().isResource) {
                        int dist = Math.abs(worker.getX() - resource.getX()) +
                                   Math.abs(worker.getY() - resource.getY());
                        if (dist <= 4) {
                            myControlledResources++;
                            break; // Count each resource only once
                        }
                    }
                }
            }
        }

        // Strategic bonuses based on LLM guidance

        // Target bonus: reward states where enemy target is damaged/destroyed
        if (targetBaseBonus > 0 && enemyBaseTotalHP > 0) {
            // Bonus for damaging enemy base (1 - current HP ratio)
            float baseDamageRatio = 1.0f - (enemyBaseHP / enemyBaseTotalHP);
            score += baseDamageRatio * targetBaseBonus * 100;
        }

        if (targetWorkersBonus > 0) {
            // Bonus for fewer enemy workers (assume max 5 workers)
            float workerKillRatio = Math.max(0, 5 - enemyWorkerCount) / 5.0f;
            score += workerKillRatio * targetWorkersBonus * 100;
        }

        if (targetArmyBonus > 0) {
            // Bonus for military advantage
            int militaryAdvantage = myMilitaryCount - enemyMilitaryCount;
            if (militaryAdvantage > 0) {
                score += militaryAdvantage * targetArmyBonus * 20;
            }
        }

        // Aggression bonus: reward having military near enemy
        if (aggressionBonus > 0 && myMilitaryCount > 0) {
            score += myMilitaryCount * aggressionBonus * 10;
        }

        // Goal-specific bonuses
        score += calculateGoalProgressBonus(player, opponent, gs, pgs,
                myWorkerCount, myMilitaryCount, myBarracksCount, myBaseCount,
                myBaseHP, myBaseTotalHP, enemyWorkerCount, enemyMilitaryCount,
                enemyBaseHP, enemyBaseTotalHP, neutralResourceCount, myControlledResources);

        return score;
    }

    /**
     * Calculate bonus based on progress toward active strategic goals
     */
    private float calculateGoalProgressBonus(int player, int opponent, GameState gs,
            PhysicalGameState pgs, int myWorkers, int myMilitary, int myBarracks, int myBases,
            float myBaseHP, float myBaseTotalHP, int enemyWorkers, int enemyMilitary,
            float enemyBaseHP, float enemyBaseTotalHP, int neutralResources, int controlledResources) {

        float bonus = 0;

        for (StrategicGoal goal : activeGoals) {
            boolean isPrimary = (goal == primaryGoal);
            float multiplier = isPrimary ? GOAL_BONUS_MULTIPLIER : GOAL_BONUS_MULTIPLIER * 0.5f;

            switch (goal) {
                case EXPAND_ECONOMY:
                    // Reward worker count and resource income potential
                    bonus += myWorkers * multiplier * 0.3f;
                    bonus += gs.getPlayer(player).getResources() * multiplier * 0.1f;
                    break;

                case BUILD_ARMY:
                    // Reward military buildup and barracks
                    bonus += myMilitary * multiplier * 0.4f;
                    bonus += myBarracks * multiplier * 0.5f;
                    break;

                case ATTACK_BASE:
                    // Reward damage to enemy base
                    if (enemyBaseTotalHP > 0) {
                        float damageRatio = 1.0f - (enemyBaseHP / enemyBaseTotalHP);
                        bonus += damageRatio * multiplier * 2.0f;
                    }
                    // Extra bonus if enemy base is destroyed
                    if (enemyBaseTotalHP == 0 || enemyBaseHP <= 0) {
                        bonus += multiplier * 3.0f;
                    }
                    break;

                case ATTACK_WORKERS:
                    // Reward killing enemy workers (assume enemy started with ~3 workers)
                    int estimatedWorkersKilled = Math.max(0, 3 - enemyWorkers);
                    bonus += estimatedWorkersKilled * multiplier * 0.5f;
                    break;

                case DEFEND:
                    // Reward keeping our base healthy
                    if (myBaseTotalHP > 0) {
                        float healthRatio = myBaseHP / myBaseTotalHP;
                        bonus += healthRatio * multiplier * 1.0f;
                    }
                    // Reward military presence
                    bonus += myMilitary * multiplier * 0.2f;
                    break;

                case CONTROL_RESOURCES:
                    // Reward having workers near resource nodes
                    bonus += controlledResources * multiplier * 0.3f;
                    break;
            }
        }

        return bonus;
    }

    @Override
    public float upperBound(GameState gs) {
        return 1.0f;
    }

    // Getters for current weights
    public float getMilitaryWeight() { return militaryWeight; }
    public float getEconomyWeight() { return economyWeight; }
    public float getAggressionBonus() { return aggressionBonus; }

    @Override
    public String toString() {
        return "LLMStrategicEvaluation(mil=" + String.format("%.2f", militaryWeight) +
               ", econ=" + String.format("%.2f", economyWeight) +
               ", aggr=" + String.format("%.2f", aggressionBonus) + ")";
    }
}
