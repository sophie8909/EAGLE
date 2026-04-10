from __future__ import annotations

from eagle.algorithm.steady_state_nsga2 import SteadyStateNSGA2
from eagle.operator.reflection import Reflection
from eagle.tools.component_pool import ComponentPool
from eagle.tools.config import EAConfig, load_config_payload
from eagle.tools.individual import Individual


def _build_component_pool() -> ComponentPool:
    return ComponentPool(
        {
            "game_rule": [["Game rule"]],
            "strategy": {
                "strategy_identity": [["Identity A"], ["Identity B"]],
                "phase_transition_rule": [["Transition A"], ["Transition B"]],
                "early_game_plan": [["Early A"], ["Early B"]],
                "mid_game_plan": [["Mid A"], ["Mid B"]],
                "late_game_plan": [["Late A"], ["Late B"]],
                "decision_priority": [["Priority A"], ["Priority B"]],
                "tactical_heuristics": [["Tactics A"], ["Tactics B"]],
                "anti_stall_rules": [["Anti-stall A"], ["Anti-stall B"]],
            },
        }
    )


def _build_parent(component_pool: ComponentPool) -> Individual:
    parent = Individual()
    parent.initialize_randomly(component_pool)
    parent.fitness = [0.0, 0.25]
    return parent


def test_config_legacy_reproduction_fallback_and_validation() -> None:
    loaded = load_config_payload({"algorithm": "steady_state_nsga2"})
    assert loaded.reproduction_operator_probs == {
        "crossover": 0.5,
        "mutation": 0.5,
        "reflection": 0.0,
    }

    disabled_reflection = EAConfig(enable_reflection_operator=False)
    assert disabled_reflection.reproduction_operator_weights() == {
        "crossover": 0.5,
        "mutation": 0.5,
    }

    try:
        EAConfig(reproduction_operator_probs={"crossover": 0.6, "mutation": 0.3, "reflection": 0.3})
    except ValueError as exc:
        assert "sum to 1.0" in str(exc)
    else:
        raise AssertionError("Expected invalid reproduction_operator_probs to raise ValueError.")


def test_build_compact_reflection_context() -> None:
    parsed_log = {
        "summary": {
            "winner": "0",
            "target_side": "1",
            "llm_move_count": 8,
            "applied_success_count": 2,
            "applied_failure_count": 2,
            "duplicate_skipped_count": 2,
            "direct_failure_count": 2,
            "resource_history": [{"time": 10}, {"time": 60}, {"time": 90}],
        },
        "segments": [
            {
                "current_time": 10,
                "llm_move_count": 2,
                "applied_success_count": 1,
                "applied_failure_count": 0,
                "duplicate_skipped_count": 0,
                "direct_failure_count": 1,
            },
            {
                "current_time": 60,
                "llm_move_count": 2,
                "applied_success_count": 1,
                "applied_failure_count": 1,
                "duplicate_skipped_count": 0,
                "direct_failure_count": 0,
            },
            {
                "current_time": 90,
                "llm_move_count": 4,
                "applied_success_count": 0,
                "applied_failure_count": 1,
                "duplicate_skipped_count": 2,
                "direct_failure_count": 1,
            },
        ],
        "all_move_results": [
            {"action_type": "attack", "status": "direct_failed"},
            {"action_type": "attack", "status": "duplicate_skipped"},
            {"action_type": "attack", "status": "applied_failed"},
            {"action_type": "attack", "status": "not_executed"},
            {"action_type": "build", "status": "applied_success"},
        ],
    }

    context = Reflection.build_compact_reflection_context(
        parsed_log=parsed_log,
        fitness=[0.0, 0.1],
        timeout=True,
        max_turn_hint=100,
    )

    assert context["outcome"] == "loss"
    assert context["final_turn"] == 90
    assert context["max_turn"] == 100
    assert context["global_instruction_quality"]["llm_move_count"] == 8
    assert context["phase_instruction_quality"]["late"]["duplicate_skipped_count"] == 2
    assert context["action_type_stats"]["intent_counts"]["attack"] == 4
    assert context["action_type_stats"]["executed_counts"]["attack"] == 1
    assert context["diagnosis_notes"]


def test_reflection_operator_falls_back_to_mutation_when_context_missing() -> None:
    component_pool = _build_component_pool()
    config = EAConfig(
        population_size=2,
        reproduction_operator_probs={"crossover": 0.0, "mutation": 0.0, "reflection": 1.0},
        enable_reflection_operator=True,
        strategy_mutation_pool_replacement_prob=1.0,
        strategy_mutation_identity_preserving_rewrite_prob=0.0,
        strategy_mutation_identity_shift_rewrite_prob=0.0,
        strategy_mutation_crossover_repair_rewrite_prob=0.0,
    )
    algorithm = SteadyStateNSGA2(config, component_pool, opponent_list=["ai.RandomAI"])

    parent = _build_parent(component_pool)
    algorithm.population = [parent, _build_parent(component_pool)]
    algorithm.select_parent = lambda: parent  # type: ignore[method-assign]

    generation_stats: dict[str, float] = {}
    child = algorithm._generate_single_offspring(generation_stats)

    assert child.operator_profile["operator_type"] == "reflection"
    assert child.operator_profile["reflection_context_used_fallback"] is True
    assert child.operator_profile["reflection_fell_back_to_mutation"] is True
    assert child.operator_profile["mutation_mode"] == "pool_replacement"
