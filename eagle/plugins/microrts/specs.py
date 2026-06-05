"""MicroRTS framework plugin metadata."""

from __future__ import annotations

from eagle.core.registry import PLUGIN_REGISTRY, PluginSpec


def register_framework_specs() -> None:
    """Register MicroRTS metadata for replaceable framework components."""
    for spec in (
        PluginSpec(
            kind="algorithm",
            id="ga",
            label="GA",
            mode="SO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSGA",
            default_config={
                "parent_selection_operator": "ga_fitness_tournament",
                "env_selection_operator": "ga_fitness_elitism",
                "objective_mode": "single",
            },
        ),
        PluginSpec(
            kind="algorithm",
            id="nsga2",
            label="NSGA-II",
            mode="MO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSNSGA2",
            default_config={
                "parent_selection_operator": "nsga2_tournament",
                "env_selection_operator": "nsga2_environmental",
                "objective_mode": "multi",
            },
        ),
        PluginSpec(
            kind="algorithm",
            id="ga_surrogate",
            label="GA + Surrogate",
            mode="SO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSGASurrogate",
            default_config={
                "parent_selection_operator": "ga_fitness_tournament",
                "env_selection_operator": "ga_fitness_elitism",
                "objective_mode": "single",
                "surrogate": "early_end",
            },
        ),
        PluginSpec(
            kind="algorithm",
            id="nsga2_surrogate",
            label="NSGA-II + Surrogate",
            mode="MO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSNSGA2Surrogate",
            default_config={
                "parent_selection_operator": "nsga2_tournament",
                "env_selection_operator": "nsga2_environmental",
                "objective_mode": "multi",
                "surrogate": "early_end",
            },
        ),
        PluginSpec(
            kind="evaluation_mode",
            id="gameplay",
            label="Real Eval",
            default_config={"evaluator": "gameplay", "eval_mode": "gameplay"},
            factory="eagle.plugins.microrts.evaluation.full_game_evaluator:FullGameEvaluator",
        ),
        PluginSpec(
            kind="evaluation_mode",
            id="early_end",
            label="Early End",
            default_config={
                "evaluator": "gameplay",
                "eval_mode": "early_end",
                "llm_call_limit": 10,
                "fitness_metric": "resource_diff_mean",
            },
            factory="eagle.plugins.microrts.evaluation.full_game_evaluator:FullGameEvaluator",
        ),
        PluginSpec(
            kind="evaluation_mode",
            id="final_test",
            label="Final Test",
            default_config={"runtime_only": True},
            factory="eagle.plugins.microrts.evaluation.final_test_runner:run_final_test_suite",
        ),
        PluginSpec(kind="surrogate", id="none", label="None", default_config={"surrogate": "none"}),
        PluginSpec(
            kind="surrogate",
            id="early_end",
            label="Truncated Gameplay",
            default_config={"surrogate": "early_end"},
        ),
        PluginSpec(kind="surrogate", id="round", label="Round", default_config={"surrogate": "round"}),
        PluginSpec(
            kind="surrogate",
            id="policy_agent",
            label="Policy Agent",
            default_config={"surrogate": "policy_agent"},
        ),
        PluginSpec(kind="surrogate", id="java_agent", label="Java Agent", default_config={"surrogate": "java_agent"}),
        PluginSpec(kind="objective_set", id="microrts", label="MicroRTS Objectives", mode="both"),
        PluginSpec(
            kind="operator",
            id="uniform",
            label="Uniform Crossover",
            default_config={"operator_type": "crossover"},
            factory="eagle.operators.crossover.uniform:UniformCrossover",
        ),
        PluginSpec(
            kind="operator",
            id="llm_crossover",
            label="LLM Crossover",
            default_config={"operator_type": "crossover"},
            factory="eagle.operators.crossover.llm_crossover:LLMCrossover",
        ),
        PluginSpec(
            kind="operator",
            id="mix",
            label="Mutation Mix",
            default_config={"operator_type": "mutation"},
            factory="eagle.operators.mutation.mix:MixMutation",
        ),
        PluginSpec(
            kind="operator",
            id="pool_replacement",
            label="Pool Replacement",
            default_config={"operator_type": "mutation"},
            factory="eagle.operators.mutation.pool_replacement:PoolReplacementMutation",
        ),
        PluginSpec(
            kind="operator",
            id="identity_preserving_rewrite",
            label="Identity-Preserving Rewrite",
            default_config={"operator_type": "mutation"},
            factory="eagle.operators.mutation.identity_preserving_rewrite:IdentityPreservingRewriteMutation",
        ),
        PluginSpec(
            kind="operator",
            id="identity_shift_rewrite",
            label="Identity-Shift Rewrite",
            default_config={"operator_type": "mutation"},
            factory="eagle.operators.mutation.identity_shift_rewrite:IdentityShiftRewriteMutation",
        ),
        PluginSpec(
            kind="operator",
            id="bitmask_flip",
            label="Bitmask Flip",
            default_config={"operator_type": "mutation"},
            factory="eagle.operators.mutation.bitmask_flip:BitmaskFlipMutation",
        ),
        PluginSpec(
            kind="operator",
            id="round_reflection",
            label="Round Reflection",
            default_config={"operator_type": "reflection"},
            factory="eagle.operators.reflection.round_reflection:RoundReflectionOperator",
        ),
    ):
        PLUGIN_REGISTRY.register(spec)
