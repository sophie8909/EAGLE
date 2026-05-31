import json
from types import SimpleNamespace

from eagle.analysis.evolution_result_analysis import parse_final_test_analysis
from eagle.objectives.aggregation import aggregate_fitness
from eagle.plugins.microrts.evaluation.evaluator_parts import GameplayAggregator
from eagle.utils.microrts_result_fitness import microrts_result_fitness


def test_microrts_result_parser_matches_evolution_and_analysis_fitness():
    result_json = {
        "ai1": "ai.eagle.EAGLE",
        "ai2": "ai.abstraction.HeavyRush",
        "winner": 1,
        "llm_call_limit_reached": True,
        "players": {
            "p0": {"resource_total": 0, "unit_types": {}},
            "p1": {"resource_total": 4, "unit_types": {"Worker": 5}},
        },
        "final_scoreboard": {"p0_eval": 0, "p1_eval": 22},
    }

    parsed = microrts_result_fitness(result_json)

    assert parsed["win_score"] == -1.0
    assert parsed["raw_resource_advantage_score"] == -22.0

    evolution_payload = {
        "scores": [{"normalized_match_score": parsed}],
        "eval_mode": "full_game",
        "evaluation_mode": "gameplay",
        "prompt_token_count": 12,
    }
    GameplayAggregator.aggregate_raw_eval_result(evolution_payload)
    config = SimpleNamespace(
        application="microrts",
        algorithm="nsga2",
        objective_config={"mode": "multi", "objectives": ["resource_advantage", "win_score"]},
        min_token_length=1,
    )

    evolution_fitness = aggregate_fitness(evolution_payload, config)

    assert evolution_fitness == {"resource_advantage": -22.0, "win_score": -1.0}

    analysis = parse_final_test_analysis(
        json.dumps(
            {
                "source_run_dir": "run",
                "results": [
                    {
                        "individual_id": "ind-1",
                        "opponent": result_json["ai2"],
                        "raw_result": result_json,
                    }
                ],
            }
        )
    )

    assert analysis["losses"] == 1
    assert analysis["mean_fitness_win_score"] == evolution_fitness["win_score"]
    assert analysis["mean_fitness_resource_advantage"] == evolution_fitness["resource_advantage"]
    assert analysis["mean_raw_p0_units"] == 0.0
    assert analysis["mean_raw_p1_units"] == 5.0
    assert analysis["mean_raw_p0_eval"] == 0.0
    assert analysis["mean_raw_p1_eval"] == 22.0
