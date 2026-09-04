import json
import os
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from eagle.artifacts import write_candidate_artifacts
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.crossover import CrossoverContext, crossover
from eagle.evaluation import evaluate_candidate, print_progress
from eagle.mutation import MutationContext
from eagle.prompts import normalize_prompt
from eagle.search import (
    create_offspring,
    mutation_evidence_parent,
    population_signature,
    run_search,
)
from eagle.selection import select_parent
from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.game_performance import (
    GamePerformanceConfig,
    compute_performance_breakdown,
    parse_round_state,
    read_tick_telemetry,
    telemetry_summary,
    tick_telemetry,
)
from evaluation.game_metrics import GameMetrics, compute_game_metrics
from evaluation.runtime_evaluation import MatchResult, run_microrts_match
from evaluation.objectives import build_objectives
from eagle.opponent_cases import FAILED_OPPONENT_SCORE as FAILED_GAME_PERFORMANCE, LEXICASE_CASES
from evaluation.code_quality import CodeQualityBreakdown
from generation.agent_template import (
    STRATEGY_START_MARKER,
    JavaTemplatePaths,
    load_java_template,
    render_blank_strategy_agent,
)
from generation.backend import GenerationBackend, MockGenerationBackend, generated_class_name
from generation.java_agent_generator import (
    clean_generated_java_output,
    generate_java_agent,
    normalize_java_agent_source,
    validate_java_agent_source,
)


class RecordingMutationBackend:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses[len(self.prompts) - 1]



def quality_fixture() -> CodeQualityBreakdown:
    return CodeQualityBreakdown(
        compilation_score=0.0,
        function_score=0.0,
        strategy_alignment_score=0.0,
        successful_base=0.0,
        score=60.0,
        warning_count=0,
        compile_success=True,
        compile_error_count=0,
    )
class EaglePipelineTests(unittest.TestCase):
    def test_aos_comparison_parent_follows_mutation_evidence_provenance(self) -> None:
        parent_a = Candidate(
            id="parent-a",
            strategy_prompt="policy-a",
            generation_prompt="prompt-a",
            generated_java="java-a",
            fitness_objectives={case: 0.0 for case in LEXICASE_CASES},
        )
        parent_b = Candidate(
            id="parent-b",
            strategy_prompt="policy-b",
            generation_prompt="prompt-b",
            generated_java="java-b",
            fitness_objectives={case: 0.0 for case in LEXICASE_CASES},
        )
        child = Candidate(
            id="child",
            strategy_parent_id=parent_b.id,
            generation_prompt_parent_id=parent_a.id,
            java_parent_id=parent_b.id,
        )
        scenarios = (
            ("strategy", "generated_phenotype", parent_b.id),
            ("code", "generated_phenotype", parent_a.id),
            ("prompt_compliance", "generated_phenotype", parent_a.id),
            ("code", "inherited_genotype", parent_b.id),
            ("prompt_compliance", "inherited_genotype", parent_b.id),
        )
        for mutation_name, java_mode, expected in scenarios:
            with self.subTest(mutation_name=mutation_name, candidate_java_mode=java_mode):
                resolved = mutation_evidence_parent(
                    child,
                    mutation_name=mutation_name,
                    candidate_java_mode=java_mode,
                    parents=(parent_a, parent_b),
                )
                self.assertEqual(resolved.id, expected)

    def test_offspring_mutation_progress_includes_generation_and_candidate_ordinal(self) -> None:
        class StrategyOnlyController:
            mode = SimpleNamespace(value="static")

            @staticmethod
            def select_operator(rng, *, eligible):
                return "strategy_reflection"

            @staticmethod
            def probability(operator):
                return 1.0

        class SuccessfulMutation:
            @staticmethod
            def mutate(candidate, context, *, artifact_dir=None, mutation_intent=None):
                return replace(
                    candidate,
                    mutation_type="strategy",
                    metadata={
                        **candidate.metadata,
                        "mutation": {
                            "applied": True,
                            "type": "strategy",
                            "reflection_error": None,
                            "rewrite_error": None,
                        },
                    },
                )

        config = ExperimentConfig.from_mapping({
            "population_size": 1,
            "crossover_rate": 0.0,
            "mutation_rate": 1.0,
        })
        parent = Candidate(
            id="parent",
            strategy_prompt="worker rush",
            generation_prompt="generate Java",
            fitness_objectives={case: 0.0 for case in LEXICASE_CASES},
        )
        comparison_parent = replace(parent, id="strategy-evidence-parent")
        output = StringIO()
        with patch(
            "eagle.search.mutation_evidence_parent",
            return_value=comparison_parent,
        ), redirect_stdout(output):
            offspring = create_offspring(
                [parent],
                config=config,
                generation=7,
                rng=random.Random(3),
                mutations={"strategy": SuccessfulMutation()},
                operator_controller=StrategyOnlyController(),
            )

        self.assertEqual(len(offspring), 1)
        self.assertEqual(
            offspring[0].metadata["aos"]["comparison_parent_id"],
            comparison_parent.id,
        )
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(
            lines[0],
            r"^\[gen 7 cand 1/1\] gen_0007_[0-9a-f]{12} "
            r"stage=mutation status=started operator=strategy$",
        )
        self.assertRegex(
            lines[1],
            r"^\[gen 7 cand 1/1\] gen_0007_[0-9a-f]{12} "
            r"stage=mutation status=completed operator=strategy applied=true$",
        )

    def test_progress_prints_matching_code_quality_total_and_components(self) -> None:
        quality = quality_fixture()
        evaluation = SimpleNamespace(
            candidate=SimpleNamespace(
                id="score-test",
                status="evaluated",
                fitness_objectives={
                    "passive": 1.0,
                },
            ),
            error=None,
            compile_result=None,
            game_metrics=SimpleNamespace(
                match_summaries=[
                    {"performance": 100.0},
                    {"performance": -90.0},
                ],
            ),
            code_quality_breakdown=quality,
        )
        output = StringIO()
        with redirect_stdout(output):
            print_progress(
                generation=0,
                index=0,
                population_size=1,
                evaluation=evaluation,
            )
        text = output.getvalue()
        self.assertIn("code_quality_simplicity=60.0", text)
        self.assertIn("complexity_penalty=0.0", text)
        self.assertIn("game_performance_matches=[100.0, -90.0]", text)
        self.assertIn("aggregate_game_performance=None", text)
    def test_config_defaults_limit_evolved_prompt_length(self) -> None:
        config = ExperimentConfig.from_mapping({})
        self.assertEqual(config.max_prompt_chars, 4000)
        self.assertEqual(config.max_prompt_lines, 80)
        self.assertEqual(config.match_commentator_sample_count, 10)
        self.assertEqual(config.result_win_score, 100.0)
        self.assertEqual(config.result_draw_score, 0.0)
        self.assertEqual(config.result_loss_score, -100.0)

    def test_strategy_reflection_sample_budget_is_configurable(self) -> None:
        config = ExperimentConfig.from_mapping({
            "llm": {"match_commentator": {"sample_count": 6}},
        })
        self.assertEqual(config.match_commentator_sample_count, 6)

    def test_training_match_command_uses_candidate_player0_and_lightrush_player1(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_microrts_match(
                microrts_dir=Path("third_party/microrts"),
                classes_dir=Path(temp_dir) / "classes",
                agent_class="ai.generated.GeneratedAgent_test",
                opponent="ai.abstraction.LightRush",
                tick_limit=100,
                match_index=0,
                mock=True,
            )
        self.assertLess(result.command.index("--ai1"), result.command.index("--ai2"))
        self.assertEqual(result.command[result.command.index("--ai1") + 1], "ai.generated.GeneratedAgent_test")
        self.assertEqual(result.command[result.command.index("--ai2") + 1], "ai.abstraction.LightRush")

    def test_match_artifact_paths_are_absolute_for_java_process(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            relative_artifacts = Path(os.path.relpath(Path(temp_dir) / "candidate_a" / "matches", Path.cwd()))
            result = run_microrts_match(
                microrts_dir=Path("third_party/microrts"),
                classes_dir=Path("relative_classes"),
                agent_class="ai.generated.GeneratedAgent_test",
                opponent="ai.abstraction.LightRush",
                tick_limit=100,
                match_index=0,
                match_artifacts_dir=relative_artifacts,
                mock=True,
            )
        trace_arg = next(arg for arg in result.command if arg.startswith("-Dmicrorts.trace.path="))
        round_state_arg = next(arg for arg in result.command if arg.startswith("-Dmicrorts.round_state_dir="))
        result_json_arg = result.command[result.command.index("--result-json") + 1]
        self.assertTrue(Path(trace_arg.split("=", 1)[1]).is_absolute())
        self.assertTrue(Path(round_state_arg.split("=", 1)[1]).is_absolute())
        self.assertTrue(Path(result_json_arg).is_absolute())

    def test_completed_loss_is_ok_and_preserves_total_performance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_microrts_match(
                microrts_dir=Path("third_party/microrts"),
                classes_dir=Path(temp_dir) / "classes",
                agent_class="ai.generated.GeneratedAgent_test",
                opponent="ai.abstraction.LightRush",
                tick_limit=100,
                match_index=0,
                match_artifacts_dir=Path(temp_dir) / "matches",
                mock=True,
                mock_score=-5.0,
            )
        metrics = compute_game_metrics([result])
        objectives = build_objectives(game_metrics=metrics, code_quality=quality_fixture(), game_failure=False)
        self.assertTrue(result.ok)
        self.assertEqual(result.winner, 1)
        self.assertEqual(result.performance_breakdown.result_score, -100)
        self.assertTrue(all(value == FAILED_GAME_PERFORMANCE for value in objectives.values()))
        self.assertEqual(metrics.completed_match_count, 1)

    def test_normalize_prompt_truncates_long_prompt(self) -> None:
        prompt = "\n".join(f"line {index}" for index in range(10))
        normalized = normalize_prompt(prompt, max_chars=20, max_lines=4)
        self.assertLessEqual(len(normalized), 20)
        self.assertLessEqual(len(normalized.splitlines()), 4)
        self.assertTrue(normalized.startswith("line 0"))

    def test_normalize_prompt_collapses_blank_lines(self) -> None:
        prompt = "  first\n\n\n\nsecond\n\n\nthird  "
        normalized = normalize_prompt(prompt, max_chars=100, max_lines=10)
        self.assertEqual(normalized, "first\n\nsecond\n\nthird")
    def test_crossover_uniform_selects_complete_java_source(self) -> None:
        source_a = load_java_template(JavaTemplatePaths()).replace("private void decide", "private void decideA", 1)
        source_b = load_java_template(JavaTemplatePaths()).replace("private void decide", "private void decideB", 1)
        parent_a = Candidate(id="a", strategy_prompt="policy-a", generation_prompt="code-a", generated_java=source_a)
        parent_b = Candidate(id="b", strategy_prompt="policy-b", generation_prompt="code-b", generated_java=source_b)
        child = crossover(parent_a, parent_b, CrossoverContext(generation=2, index=0, rng=random.Random(1)))
        self.assertEqual(child.parent_ids, ("a", "b"))
        self.assertEqual(child.operator, "crossover")
        self.assertEqual(child.generated_java, "")
        self.assertFalse(hasattr(child, "previous_code"))

    def test_selection_binary_tournament_returns_candidates(self) -> None:
        population = [
            Candidate(id="a", fitness_objectives={case: 1.0 for case in LEXICASE_CASES}),
            Candidate(id="b", fitness_objectives={case: 2.0 for case in LEXICASE_CASES}),
            Candidate(id="c", fitness_objectives={case: 3.0 for case in LEXICASE_CASES}),
        ]
        selected = [select_parent(population, random.Random(index)) for index in range(5)]
        self.assertEqual(len(selected), 5)
        self.assertTrue(all(candidate in population for candidate in selected))

    def test_mock_generation_returns_valid_java_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Candidate(strategy_prompt="Generate an agent.")
            agent = generate_java_agent(candidate, MockGenerationBackend(), Path(temp_dir))
            self.assertIn("package ai.generated;", agent.source)
            self.assertIn("extends AbstractionLayerAI", agent.source)
            self.assertIn("public PlayerAction getAction", agent.source)
            self.assertIn(f"return new {agent.class_name}(utt, new AStarPathFinding());", agent.source)
            self.assertIn("private void economy", agent.source)
            self.assertIn("private Unit selectTarget", agent.source)
            self.assertIn("private boolean commandMove", agent.source)
            self.assertIn("private boolean commandIdle", agent.source)
            self.assertEqual(agent.source_paths, (agent.source_path,))
            self.assertTrue(agent.strategy_region)

    def test_missing_java_strategy_marker_fails_fixed_scaffold_validation(self) -> None:
        class StaticGenerationBackend(GenerationBackend):
            def generate(self, candidate: Candidate, class_name: str) -> str:
                source = load_java_template(JavaTemplatePaths())
                return source.replace(STRATEGY_START_MARKER, "")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ExperimentConfig.from_mapping({})
            evaluation = evaluate_candidate(
                Candidate(strategy_prompt="Generate an agent."),
                config=config,
                backend=StaticGenerationBackend(),
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
        self.assertIsNone(evaluation.agent)
        self.assertIsNone(evaluation.compile_result)
        self.assertIsNone(evaluation.integration_result)
        self.assertEqual(evaluation.match_results, [])
        self.assertEqual(evaluation.candidate.status, "failed")
        self.assertEqual(evaluation.candidate.failure_stage, "validation")
        self.assertEqual(evaluation.result.failure_category, "Java validation failure")
        self.assertFalse(evaluation.code_quality_breakdown.compile_success)
        self.assertEqual(evaluation.code_quality_breakdown.strategy_region_score, -100)

    def test_empty_java_response_fails_before_compile_or_matches(self) -> None:
        class NonJavaBackend(GenerationBackend):
            def generate(self, candidate: Candidate, class_name: str) -> str:
                return ""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ExperimentConfig.from_mapping({})
            evaluation = evaluate_candidate(
                Candidate(strategy_prompt="Generate an agent."),
                config=config,
                backend=NonJavaBackend(),
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
        self.assertIsNone(evaluation.agent)
        self.assertIsNone(evaluation.compile_result)
        self.assertEqual(evaluation.match_results, [])
        self.assertEqual(evaluation.candidate.status, "failed")
        self.assertEqual(evaluation.result.failure_category, "Java validation failure")
        self.assertFalse(evaluation.code_quality_breakdown.compile_success)
        self.assertEqual(evaluation.code_quality_breakdown.strategy_region_score, -100)
        self.assertIn("strategy region", " ".join(evaluation.strategy_region_score_result.strategy_region_validation["agent_strategy_region"].errors).lower())

    def test_mock_search_writes_lexicase_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "generations: 2",
                        "population_size: 3",
                        "crossover_rate: 1.0",
                        "mutation_rate: 1.0",
                        f'runs_dir: "{(root / "runs").as_posix()}"',
                    ]
                ),
                encoding="utf-8",
            )
            config = ExperimentConfig.from_file(config_path)
            result = run_search(config, config_path=config_path, mock=True, run_id="test_run")
            self.assertEqual(
                {path.name for path in result.run_dir.iterdir()},
                {
                    "manifest.json", "config.yaml", "summary.json", "timing.jsonl",
                    "generations", "candidates", "generated_agents", "classes",
                    "archives", "llm_logs", "final_test",
                },
            )
            self.assertTrue((result.run_dir / "config.yaml").exists())
            self.assertTrue((result.run_dir / "candidates").is_dir())
            self.assertTrue((result.run_dir / "generated_agents").is_dir())
            self.assertFalse((result.run_dir / "results.jsonl").exists())
            self.assertFalse((result.run_dir / "source_config").exists())
            self.assertFalse((result.run_dir / "source_config.json").exists())
            summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["objectives"], list(LEXICASE_CASES))
            self.assertEqual(len(summary["final_population_ids"]), 3)
            self.assertFalse((result.run_dir / "resolved_config.json").exists())
            self.assertFalse((result.run_dir / "prompt_snapshot.json").exists())
            self.assertFalse((result.run_dir / "final_population.json").exists())
            candidate_dir = next((result.run_dir / "candidates").iterdir())
            self.assertTrue((candidate_dir / "lineage.json").exists())
            self.assertTrue((candidate_dir / "genotype" / "policy_prompt.txt").exists())
            self.assertTrue(
                (candidate_dir / "generation" / "normalized_candidate.java").exists()
            )
            self.assertFalse((candidate_dir / "CandidateBehaviors.java").exists())
            self.assertTrue((candidate_dir / "compilation" / "compilation_result.json").exists())
            self.assertFalse((candidate_dir / "evaluation" / "matches.json").exists())
            self.assertTrue((candidate_dir / "evaluation" / "game_performance.json").exists())
            self.assertTrue((candidate_dir / "evaluation" / "code_quality.json").exists())
            quality = json.loads((candidate_dir / "evaluation" / "code_quality.json").read_text(encoding="utf-8"))
            self.assertIn("score", quality)
            self.assertEqual(quality["score"], quality["code_quality"])
            self.assertEqual(
                quality["code_quality"],
                round(100 - quality["code_quality_details"]["complexity_penalty"], 6),
            )
            self.assertTrue((candidate_dir / "evaluation" / "objectives.json").exists())
            self.assertTrue((candidate_dir / "candidate.json").exists())
            individual = json.loads((candidate_dir / "candidate.json").read_text(encoding="utf-8"))
            self.assertNotIn("prompt_length", individual["fitness_objectives"])
            metrics = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((result.run_dir / "generations").glob("generation_*.json"))
            ]
            generation_one_aos = next(item["aos"] for item in metrics if item["generation"] == 1)
            self.assertEqual(
                set(generation_one_aos["operators"]),
                {
                    "strategy_reflection",
                    "generate_code_reflection",
                    "prompt_compliance_reflection",
                },
            )
            self.assertAlmostEqual(
                sum(generation_one_aos["post_update_probabilities"].values()), 1.0
            )
            self.assertTrue(list((result.run_dir / "candidates").glob("*/aos/reward.json")))
            aos_reward_path = next((result.run_dir / "candidates").glob("*/aos/reward.json"))
            aos_reward = json.loads(aos_reward_path.read_text(encoding="utf-8"))
            self.assertEqual(aos_reward["schema_version"], "eagle-aos-reward-v3")
            self.assertEqual(aos_reward["offspring_id"], aos_reward_path.parents[1].name)
            self.assertIn(aos_reward["operator"], {"strategy", "code"})
            self.assertIn(aos_reward["operator_id"], generation_one_aos["operators"])
            self.assertTrue(
                aos_reward_path.parents[2].joinpath(aos_reward["comparison_parent_id"]).is_dir()
            )
            self.assertEqual(aos_reward["head_to_head"]["total_matches"], 18)
            self.assertEqual(aos_reward["reward_source"], "head2head")
            self.assertIn("operator_quality_before", aos_reward)
            self.assertIn("operator_quality_after", aos_reward)

    def test_population_signature_tracks_opponent_cases_not_candidate_ids(self) -> None:
        first = [
            Candidate(id="front-a", fitness_objectives={case: 10.0 for case in LEXICASE_CASES}),
            Candidate(id="dominated-a", fitness_objectives={case: 1.0 for case in LEXICASE_CASES}),
        ]
        second = [
            Candidate(id="front-b", fitness_objectives={case: 10.0 for case in LEXICASE_CASES}),
            Candidate(id="dominated-b", fitness_objectives={case: 1.0 for case in LEXICASE_CASES}),
        ]

        self.assertEqual(population_signature(first), population_signature(second))

    def test_search_stops_when_population_stagnates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "generations: 10",
                        "population_size: 1",
                        "stagnation_generations: 2",
                        f'runs_dir: "{(root / "runs").as_posix()}"',
                    ]
                ),
                encoding="utf-8",
            )
            config = ExperimentConfig.from_file(config_path)

            def fake_evaluate_population(population, *, generation, **kwargs):
                return [
                    Candidate(
                        id=f"evaluated-{generation}",
                        generation=generation,
                        fitness_objectives={case: 10.0 for case in LEXICASE_CASES},
                    )
                ]

            with patch("eagle.search.evaluate_population", side_effect=fake_evaluate_population) as evaluate, patch(
                "eagle.search.create_offspring",
                return_value=[Candidate(generation=1)],
            ):
                result = run_search(config, config_path=config_path, mock=True, run_id="stagnation_run")

            self.assertEqual(evaluate.call_count, 3)
            self.assertEqual(result.completed_generation, 2)
            self.assertEqual(result.stop_reason, "stagnation_2_generations")
            summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["completed_generation"], 2)
            self.assertEqual(summary["stop_reason"], "stagnation_2_generations")
            self.assertTrue((result.run_dir / "generations" / "generation_0002.json").exists())
            self.assertFalse((result.run_dir / "generations" / "generation_0003.json").exists())
            self.assertFalse((result.run_dir / "generation_002_population.json").exists())

    def test_generate_java_agent_uses_stable_template_class_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Candidate(strategy_prompt="Generate a Java MicroRTS agent.")
            agent = generate_java_agent(candidate, MockGenerationBackend(), Path(temp_dir))
            self.assertEqual(agent.class_name, "CandidateAgent")
            self.assertTrue(agent.source_path.exists())

    def test_validate_java_agent_source_rejects_non_java_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "package must be ai.generated"):
            validate_java_agent_source("Here is a strategy explanation with no Java.", "GeneratedAgent_test")

    def test_game_metrics_use_resource_difference(self) -> None:
        result = MatchResult(
            ok=True,
            score=0.5,
            command=[],
            raw_result={
                "winner": 0,
                "players": {
                    "p0": {"resource_total": 14, "material_total": 3},
                    "p1": {"resource_total": 8, "material_total": 1},
                },
            },
        )
        metrics = compute_game_metrics([result])
        self.assertEqual(metrics.resource_difference, 8)
        self.assertEqual(metrics.weighted_resource_difference, 8)
        self.assertEqual(metrics.player0_resource, 14)
        self.assertEqual(metrics.player1_resource, 8)
        self.assertEqual(metrics.player_resource, 14)
        self.assertEqual(metrics.enemy_resource, 8)
        self.assertEqual(metrics.winner, 0)
        self.assertEqual(metrics.to_json_dict()["player0_resource"], 14)
        self.assertEqual(metrics.resource_breakdown["player0_resource"], 14)
        self.assertEqual(metrics.objective, FAILED_GAME_PERFORMANCE)

    def test_player0_resource_advantage_is_positive(self) -> None:
        metrics = compute_game_metrics(
            [
                MatchResult(
                    ok=True,
                    score=0.0,
                    command=[],
                    raw_result={
                        "players": {
                            "p0": {"resource_total": 20, "material_total": 0},
                            "p1": {"resource_total": 5, "material_total": 0},
                        }
                    },
                )
            ]
        )
        self.assertEqual(metrics.weighted_resource_difference, 15)

    def test_player1_resource_advantage_is_negative(self) -> None:
        metrics = compute_game_metrics(
            [
                MatchResult(
                    ok=True,
                    score=0.0,
                    command=[],
                    raw_result={
                        "players": {
                            "p0": {"resource_total": 4, "material_total": 0},
                            "p1": {"resource_total": 11, "material_total": 0},
                        }
                    },
                )
            ]
        )
        self.assertEqual(metrics.weighted_resource_difference, -7)

    def test_equal_resources_have_zero_weighted_difference(self) -> None:
        metrics = compute_game_metrics(
            [
                MatchResult(
                    ok=True,
                    score=0.0,
                    command=[],
                    raw_result={
                        "players": {
                            "p0": {"resource_total": 9, "material_total": 0},
                            "p1": {"resource_total": 9, "material_total": 0},
                        }
                    },
                )
            ]
        )
        self.assertEqual(metrics.weighted_resource_difference, 0)
        self.assertEqual(metrics.objective, FAILED_GAME_PERFORMANCE)

    def test_win_loss_bonus_is_plus_or_minus_100(self) -> None:
        win_metrics = compute_game_metrics(
            [
                MatchResult(
                    ok=True,
                    score=0.0,
                    command=[],
                    raw_result={
                        "winner": 0,
                        "players": {
                            "p0": {"resource_total": 5, "material_total": 0},
                            "p1": {"resource_total": 5, "material_total": 0},
                        },
                    },
                )
            ]
        )
        loss_metrics = compute_game_metrics(
            [
                MatchResult(
                    ok=True,
                    score=0.0,
                    command=[],
                    raw_result={
                        "winner": 1,
                        "players": {
                            "p0": {"resource_total": 5, "material_total": 0},
                            "p1": {"resource_total": 5, "material_total": 0},
                        },
                    },
                )
            ]
        )
        self.assertEqual(win_metrics.performance_breakdown["result_score"], 100)
        self.assertEqual(loss_metrics.performance_breakdown["result_score"], -100)
        self.assertEqual(win_metrics.objective, FAILED_GAME_PERFORMANCE)
        self.assertEqual(loss_metrics.objective, FAILED_GAME_PERFORMANCE)

    def test_draw_or_timeout_result_score_is_zero(self) -> None:
        metrics = compute_game_metrics(
            [
                MatchResult(
                    ok=True,
                    score=0.0,
                    command=[],
                    raw_result={
                        "winner": -1,
                        "tick_timeout": True,
                        "players": {
                            "p0": {"resource_total": 5, "material_total": 0},
                            "p1": {"resource_total": 5, "material_total": 0},
                        },
                    },
                )
            ]
        )
        self.assertEqual(metrics.performance_breakdown["result_score"], 0)
        self.assertEqual(metrics.objective, FAILED_GAME_PERFORMANCE)

    def test_unit_material_cost_is_added_to_resource_difference(self) -> None:
        metrics = compute_game_metrics(
            [
                MatchResult(
                    ok=True,
                    score=0.0,
                    command=[],
                    raw_result={
                        "players": {
                            "p0": {"resource_total": 3, "material_total": 10},
                            "p1": {"resource_total": 5, "material_total": 1},
                        }
                    },
                )
            ]
        )
        self.assertEqual(metrics.weighted_resource_difference, 7)

    def test_longer_survival_scores_higher_for_matching_losses(self) -> None:
        config = GamePerformanceConfig()
        tick = tick_telemetry(0, 5, 5, {}, {}, config)
        short_loss = compute_performance_breakdown(
            result="p1_win",
            winner=1,
            end_tick=10,
            max_tick=100,
            ticks=[tick],
            scoring_config=config,
        )
        long_loss = compute_performance_breakdown(
            result="p1_win",
            winner=1,
            end_tick=30,
            max_tick=100,
            ticks=[tick],
            scoring_config=config,
        )
        self.assertGreater(long_loss.total_performance, short_loss.total_performance)
        self.assertGreater(long_loss.survival_score, short_loss.survival_score)

    def test_average_state_score_ignores_trace_length(self) -> None:
        config = GamePerformanceConfig()
        one_tick = [tick_telemetry(0, 5, 3, {}, {}, config)]
        three_ticks = [
            tick_telemetry(0, 5, 3, {}, {}, config),
            tick_telemetry(1, 5, 3, {}, {}, config),
            tick_telemetry(2, 5, 3, {}, {}, config),
        ]
        short = compute_performance_breakdown(
            result="draw",
            winner=-1,
            end_tick=1,
            max_tick=10,
            ticks=one_tick,
            scoring_config=config,
        )
        long = compute_performance_breakdown(
            result="draw",
            winner=-1,
            end_tick=3,
            max_tick=10,
            ticks=three_ticks,
            scoring_config=config,
        )
        self.assertEqual(short.average_state_score, long.average_state_score)

    def test_player_enemy_perspective_inverts_state_differences(self) -> None:
        text = "\n".join(
            [
                "current time 7 p0 player 0(9) p1 player 1(4)",
                "(1,1) Ally Worker Unit {HP=1, resources=0}",
                "(2,2) Enemy Light Unit {HP=4, resources=0}",
            ]
        )
        config = GamePerformanceConfig()
        player0 = parse_round_state(text, player_index=0, scoring_config=config)
        player1 = parse_round_state(text, player_index=1, scoring_config=config)
        self.assertEqual(player0.resource_diff, -player1.resource_diff)
        self.assertEqual(player0.army_value_diff, -player1.army_value_diff)
        self.assertEqual(player0.state_score, -player1.state_score)

    def test_terminal_tick_appears_once_in_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content = "\n".join(
                [
                    "current time 3 p0 player 0(5) p1 player 1(5)",
                    "(1,1) Ally Base Unit {HP=10, resources=0}",
                    "(6,6) Enemy Base Unit {HP=10, resources=0}",
                ]
            )
            (root / "round_000000.log").write_text("current time 0 p0 player 0(5) p1 player 1(5)\n", encoding="utf-8")
            (root / "round_000003.log").write_text(content, encoding="utf-8")
            (root / "round_000003_duplicate.log").write_text(content, encoding="utf-8")
            ticks = read_tick_telemetry(root, player_index=0, scoring_config=GamePerformanceConfig())
        self.assertEqual([tick.tick for tick in ticks], [0, 3])

    def test_separate_matches_do_not_overwrite_replay_and_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = run_microrts_match(
                microrts_dir=Path("third_party/microrts"),
                classes_dir=root / "classes",
                agent_class="ai.generated.GeneratedAgent_test",
                opponent="ai.abstraction.LightRush",
                tick_limit=10,
                match_index=0,
                match_artifacts_dir=root / "matches",
                mock=True,
                artifact_mode="full",
            )
            second = run_microrts_match(
                microrts_dir=Path("third_party/microrts"),
                classes_dir=root / "classes",
                agent_class="ai.generated.GeneratedAgent_test",
                opponent="ai.abstraction.LightRush",
                tick_limit=10,
                match_index=1,
                match_artifacts_dir=root / "matches",
                mock=True,
                artifact_mode="full",
            )
            self.assertNotEqual(first.replay_path, second.replay_path)
            self.assertNotEqual(first.telemetry_path, second.telemetry_path)
            self.assertTrue((root / first.replay_path).exists())
            self.assertTrue((root / first.telemetry_path).exists())
            self.assertTrue((root / second.replay_path).exists())
            self.assertTrue((root / second.telemetry_path).exists())

    def test_performance_total_is_sum_of_four_components(self) -> None:
        config = GamePerformanceConfig()
        breakdown = compute_performance_breakdown(
            result="p0_win",
            winner=0,
            end_tick=5,
            max_tick=10,
            ticks=[tick_telemetry(5, 7, 2, {"Worker": 1}, {"Light": 1}, config)],
            scoring_config=config,
        )
        self.assertEqual(
            breakdown.total_performance,
            breakdown.result_score
            + breakdown.average_state_score
            + breakdown.survival_score
            + breakdown.final_resource_diff,
        )

    def test_backend_failure_gets_failed_game_performance(self) -> None:
        class FailingBackend(GenerationBackend):
            def generate(self, candidate: Candidate, class_name: str) -> str:
                raise RuntimeError("backend down")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation = evaluate_candidate(Candidate(strategy_prompt="Generate an agent."), config=ExperimentConfig.from_mapping({}), backend=FailingBackend(), generated_agents_dir=root / "generated_agents", classes_dir=root / "classes", mock=True, ordinal=0)
        self.assertEqual(evaluation.candidate.status, "failed")
        self.assertEqual(evaluation.result.failure_category, "Backend request failure")
        self.assertTrue(all(value == FAILED_GAME_PERFORMANCE for value in evaluation.candidate.fitness_objectives.values()))

    def test_non_java_response_fails_before_compile_or_matches(self) -> None:
        class NonJavaBackend(GenerationBackend):
            def generate(self, candidate: Candidate, class_name: str) -> str:
                return "```json\n{}\n```"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = Candidate(id="badjson", strategy_prompt="Generate an agent.")
            evaluation = evaluate_candidate(
                candidate,
                config=ExperimentConfig.from_mapping({}),
                backend=NonJavaBackend(),
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                mock=True,
                ordinal=0,
            )

        self.assertIsNone(evaluation.agent)
        self.assertIsNone(evaluation.compile_result)
        self.assertEqual(evaluation.match_results, [])
        self.assertEqual(evaluation.candidate.status, "failed")
        self.assertEqual(evaluation.result.failure_category, "Java validation failure")
        self.assertIn("package must be ai.generated", evaluation.result.failure_reason or "")
        self.assertEqual(evaluation.candidate.compile_status, "not_run")
        self.assertTrue(all(value == FAILED_GAME_PERFORMANCE for value in evaluation.candidate.fitness_objectives.values()))
        self.assertEqual(evaluation.candidate.failure_stage, "validation")
        self.assertTrue(evaluation.result.validation_result.error)

    def test_lexicase_cases_are_the_only_selection_dimensions(self) -> None:
        strong_passive = Candidate(id="passive", fitness_objectives={"passive": 10.0, "random": 0.0})
        strong_random = Candidate(id="random", fitness_objectives={"passive": 0.0, "random": 10.0})
        selected = select_parent([strong_passive, strong_random], random.Random(4))
        self.assertIn(selected, (strong_passive, strong_random))

if __name__ == "__main__":
    unittest.main()
