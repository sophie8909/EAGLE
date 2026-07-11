import json
import os
import random
import tempfile
import unittest
from pathlib import Path

from eagle.artifacts import write_candidate_artifacts
from eagle.candidate import Candidate, DEFAULT_MODULE_BODIES, MODULE_NAMES
from eagle.config import ExperimentConfig, parse_minimal_yaml
from eagle.crossover import Crossover, CrossoverContext
from eagle.evaluation import evaluate_candidate
from eagle.mutation import Mutation, MutationContext
from eagle.offspring import normalize_prompt
from eagle.search import choose_mutation, run_search
from eagle.selection import Selection, SelectionContext, dominates
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
from evaluation.microrts_runner import MatchResult, persist_match_artifacts, run_microrts_match
from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE, build_objectives
from evaluation.strategy_alignment import StrategyAlignmentResult
from generation.agent_template import microrts_blank_strategy_prompt, render_blank_strategy_agent, render_function_agent
from generation.backend import GenerationBackend, MockGenerationBackend, generated_class_name
from generation.java_agent_generator import (
    clean_generated_java_output,
    generate_java_agent,
    normalize_java_agent_source,
    validate_java_agent_source,
)
from scripts.analyze_run import analyze_run, format_report


class RecordingMutationBackend:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses[len(self.prompts) - 1]


class EaglePipelineTests(unittest.TestCase):
    def test_parse_minimal_yaml(self) -> None:
        payload = parse_minimal_yaml(
            """
seed_prompts:
  - "Generate an agent."
generations: 2
population_size: 3
"""
        )
        self.assertEqual(payload["seed_prompts"], ["Generate an agent."])
        self.assertEqual(payload["generations"], 2)
        self.assertEqual(payload["population_size"], 3)

    def test_config_defaults_limit_evolved_prompt_length(self) -> None:
        config = ExperimentConfig.from_mapping({"seed_prompts": ["Generate an agent."]})
        self.assertEqual(config.max_prompt_chars, 4000)
        self.assertEqual(config.max_prompt_lines, 80)
        self.assertEqual(config.result_win_score, 100.0)
        self.assertEqual(config.result_draw_score, 0.0)
        self.assertEqual(config.result_loss_score, -100.0)

    def test_training_opponent_defaults_to_lightrush_player1(self) -> None:
        config = ExperimentConfig.from_mapping({"seed_prompts": ["Generate an agent."]})
        self.assertEqual(config.opponent, "ai.abstraction.LightRush")

    def test_training_config_ignores_non_lightrush_opponent(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "seed_prompts": ["Generate an agent."],
                "opponent": "ai.PassiveAI",
            }
        )
        self.assertEqual(config.opponent, "ai.abstraction.LightRush")

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
        with tempfile.TemporaryDirectory() as temp_dir:
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
        objectives = build_objectives(
            compile_result=CompileResult(ok=True, command=[]),
            game_metrics=metrics,
            alignment_result=StrategyAlignmentResult(score=0.0, rationale=""),
            failure_category=None,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.winner, 1)
        self.assertEqual(result.performance_breakdown.result_score, -100)
        self.assertEqual(objectives["game_performance"], result.performance_breakdown.total_performance)
        self.assertNotEqual(objectives["game_performance"], FAILED_GAME_PERFORMANCE)

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

    def test_candidate_serializes_function_modules(self) -> None:
        candidate = Candidate(
            module_prompts={"economy": "save resources"},
            module_bodies={"economy": "return new ArrayList<>();"},
        )
        payload = candidate.to_json_dict()
        self.assertEqual(set(payload["module_prompts"]), set(MODULE_NAMES))
        self.assertEqual(set(payload["module_bodies"]), set(MODULE_NAMES))
        self.assertEqual(payload["module_prompts"]["economy"], "save resources")

    def test_generation_input_includes_one_module_prompt_and_body(self) -> None:
        candidate = Candidate(
            module_prompts={"economy": "economy prompt part"},
            module_bodies={"economy": "economy body part"},
            generation_prompt="generation prompt part",
        )
        generation_input = candidate.generation_input(module_name="economy")
        self.assertLess(generation_input.index("economy"), generation_input.index("economy prompt part"))
        self.assertLess(generation_input.index("economy prompt part"), generation_input.index("economy body part"))
        self.assertLess(generation_input.index("economy body part"), generation_input.index("generation prompt part"))

    def test_initial_candidate_has_default_module_bodies(self) -> None:
        candidate = Candidate(strategy_prompt="strategy", generation_prompt="generate")
        self.assertEqual(set(candidate.module_bodies), set(MODULE_NAMES))
        self.assertIn("Decision decision", candidate.module_bodies["controller"])

    def test_mutation_dispatch_calls_strategy_reflection(self) -> None:
        backend = RecordingMutationBackend(["strategy analysis", "return new ArrayList<>();"])
        config = ExperimentConfig.from_mapping(
            {
                "seed_prompts": ["seed"],
                "max_prompt_chars": 300,
                "max_prompt_lines": 8,
            }
        )
        parent = Candidate(
            id="parent",
            strategy_prompt="keep this intent",
            previous_code="old code",
            generation_prompt="generate",
        )
        child = Mutation(config, method="strategy_reflection", backend=backend).mutate(
            parent,
            MutationContext(generation=1, index=0, game_performance=3.0, player_resource=12.0, enemy_resource=7.0),
        )
        self.assertEqual(child.generation, 1)
        self.assertEqual(child.parent_ids, ("parent",))
        self.assertEqual(len(backend.prompts), 2)
        self.assertIn("Analyze this strategy's result.", backend.prompts[0])
        self.assertIn("strategy analysis", backend.prompts[1])
        self.assertEqual(child.module_bodies["controller"], "return new ArrayList<>();")
        for module_name in MODULE_NAMES:
            if module_name != "controller":
                self.assertEqual(child.module_bodies[module_name], parent.module_bodies[module_name])
        self.assertEqual(child.previous_code, parent.previous_code)
        self.assertEqual(child.generation_prompt, parent.generation_prompt)
        self.assertEqual(child.metadata["mutation_reflection"], "strategy analysis")
        self.assertEqual(child.metadata["mutation_rewrite"], "return new ArrayList<>();")
        self.assertEqual(child.metadata["mutation_module"], "controller")
        self.assertEqual(child.metadata["operator"], "mutation")

    def test_mutation_dispatch_calls_code_generation_reflection(self) -> None:
        backend = RecordingMutationBackend(["code analysis", "return candidates.isEmpty() ? null : candidates.get(0);"])
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
        parent = Candidate(
            id="parent",
            strategy_prompt="keep this strategy",
            previous_code="return pag.getRandom();",
            generation_prompt="generate",
        )
        child = Mutation(config, method="code_generation_reflection", backend=backend).mutate(
            parent,
            MutationContext(
                generation=1,
                index=0,
                alignment_score=0.25,
                alignment_reason="used random action",
                compile_success=False,
                validation_success=True,
                runtime_success=False,
                error_category="Java compile failure",
                error_message="cannot find symbol in selectTarget",
            ),
        )
        self.assertEqual(len(backend.prompts), 2)
        self.assertIn("Analyze why this code-generation instruction produced this result.", backend.prompts[0])
        self.assertIn("cannot find symbol", backend.prompts[0])
        self.assertIn("code analysis", backend.prompts[1])
        self.assertEqual(child.module_bodies["target_selection"], "return candidates.isEmpty() ? null : candidates.get(0);")
        for module_name in MODULE_NAMES:
            if module_name != "target_selection":
                self.assertEqual(child.module_bodies[module_name], parent.module_bodies[module_name])
        self.assertEqual(child.previous_code, parent.previous_code)
        self.assertEqual(child.generation_prompt, parent.generation_prompt)
        self.assertEqual(child.metadata["mutation_module"], "target_selection")
        self.assertEqual(child.metadata["mutation_reflection"], "code analysis")
        self.assertEqual(child.metadata["mutation_rewrite"], "return candidates.isEmpty() ? null : candidates.get(0);")

    def test_failed_game_performance_selects_code_generation_reflection(self) -> None:
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
        strategy_mutation = Mutation(config, method="strategy_reflection")
        code_mutation = Mutation(config, method="code_generation_reflection")
        failed_parent = Candidate(fitness_objectives={"game_performance": FAILED_GAME_PERFORMANCE})
        selected = choose_mutation(failed_parent, (strategy_mutation, code_mutation), random.Random(1))
        self.assertIs(selected, code_mutation)

    def test_unknown_mutation_method_raises_value_error(self) -> None:
        config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
        with self.assertRaisesRegex(ValueError, "Unknown mutation method"):
            Mutation(config, method="unknown").mutate(
                Candidate(strategy_prompt="strategy"),
                MutationContext(generation=1, index=0),
            )

    def test_crossover_uniform_selects_function_modules(self) -> None:
        bodies_a = {module_name: f"{module_name} body A" for module_name in MODULE_NAMES}
        bodies_b = {module_name: f"{module_name} body B" for module_name in MODULE_NAMES}
        parent_a = Candidate(
            id="a",
            module_bodies=bodies_a,
        )
        parent_b = Candidate(
            id="b",
            module_bodies=bodies_b,
        )
        child = Crossover(method="uniform").crossover(
            parent_a,
            parent_b,
            CrossoverContext(generation=2, index=0, rng=random.Random(1)),
        )
        self.assertEqual(child.generation, 2)
        self.assertEqual(child.parent_ids, ("a", "b"))
        self.assertEqual(child.metadata["operator"], "crossover")
        for module_name in MODULE_NAMES:
            self.assertIn(child.module_bodies[module_name], {bodies_a[module_name], bodies_b[module_name]})
            self.assertNotIn("body A\n", child.module_bodies[module_name])

    def test_unknown_crossover_method_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown crossover method"):
            Crossover(method="unknown").crossover(
                Candidate(strategy_prompt="a"),
                Candidate(strategy_prompt="b"),
                CrossoverContext(generation=1, index=0, rng=random.Random(1)),
            )

    def test_selection_binary_tournament_returns_k_candidates(self) -> None:
        population = [
            Candidate(id="a", fitness_objectives={"game_performance": 1.0, "strategy_alignment": 0.1}),
            Candidate(id="b", fitness_objectives={"game_performance": 2.0, "strategy_alignment": 0.2}),
            Candidate(id="c", fitness_objectives={"game_performance": 3.0, "strategy_alignment": 0.3}),
        ]
        selected = Selection(method="binary_tournament").select(
            population,
            5,
            SelectionContext(rng=random.Random(1)),
        )
        self.assertEqual(len(selected), 5)
        self.assertTrue(all(candidate in population for candidate in selected))

    def test_unknown_selection_method_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown selection method"):
            Selection(method="unknown").select(
                [Candidate(strategy_prompt="strategy")],
                1,
                SelectionContext(rng=random.Random(1)),
            )

    def test_mock_generation_returns_valid_java_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Candidate(strategy_prompt="Generate an agent.")
            agent = generate_java_agent(candidate, MockGenerationBackend(), Path(temp_dir))
            self.assertIn("package ai.generated;", agent.source)
            self.assertIn("extends AI", agent.source)
            self.assertIn("public PlayerAction getAction", agent.source)
            self.assertIn(f"return new {agent.class_name}();", agent.source)
            self.assertIn("private Decision decide", agent.source)
            self.assertIn("private List<ActionProposal> economy", agent.source)
            self.assertIn("private Unit selectTarget", agent.source)
            self.assertEqual(set(agent.module_bodies), set(MODULE_NAMES))

    def test_seed_prompt_template_expands_to_blank_strategy_prompt(self) -> None:
        config = ExperimentConfig.from_mapping({"seed_prompt_template": "microrts_blank_strategy_agent"})
        self.assertEqual(len(config.seed_prompts), 1)
        self.assertEqual(config.seed_prompts[0], microrts_blank_strategy_prompt())
        self.assertIn("six evolvable functions", config.seed_prompts[0])
        self.assertIn("PlayerAction assembly", config.seed_prompts[0])

    def test_passive_ai_initial_baseline_compiles_against_microrts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "src" / "ai" / "generated"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "GeneratedAgent_test.java"
            source_path.write_text(render_blank_strategy_agent("GeneratedAgent_test"), encoding="utf-8")
            result = compile_generated_agent(
                source_path,
                microrts_dir=Path("third_party/microrts"),
                output_dir=root / "classes",
                mock=False,
            )
        self.assertTrue(result.ok, result.stderr)

    def test_mock_search_writes_nsga2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "seed_prompts:",
                        '  - "Generate a Java MicroRTS economy agent."',
                        '  - "Generate a Java MicroRTS defensive agent."',
                        "generations: 2",
                        "population_size: 3",
                        "crossover_rate: 1.0",
                        "mutation_rate: 1.0",
                        'generation_backend: "mock"',
                        'alignment_backend: "mock"',
                        f'runs_dir: "{(root / "runs").as_posix()}"',
                        "matches_per_candidate: 1",
                    ]
                ),
                encoding="utf-8",
            )
            config = ExperimentConfig.from_file(config_path)
            result = run_search(config, config_path=config_path, mock=True, run_id="test_run")
            self.assertTrue((result.run_dir / "config.yaml").exists())
            self.assertTrue((result.run_dir / "candidates").is_dir())
            self.assertTrue((result.run_dir / "generated_agents").is_dir())
            self.assertTrue((result.run_dir / "results.jsonl").exists())
            summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["objectives"], ["game_performance", "strategy_alignment"])
            self.assertEqual(len(summary["final_population"]), 3)
            candidate_dir = next((result.run_dir / "candidates").iterdir())
            self.assertTrue((candidate_dir / "strategy_prompt.txt").exists())
            self.assertTrue((candidate_dir / "generated_java_source.java").exists())
            self.assertTrue((candidate_dir / "compile_result.json").exists())
            self.assertTrue((candidate_dir / "raw_microrts_result.json").exists())
            self.assertTrue((candidate_dir / "game_metrics.json").exists())
            self.assertTrue((candidate_dir / "strategy_alignment.json").exists())
            self.assertTrue((candidate_dir / "objectives.json").exists())
            self.assertTrue((candidate_dir / "candidate_result.json").exists())
            individual = json.loads((candidate_dir / "individual.json").read_text(encoding="utf-8"))
            self.assertNotIn("prompt_length", individual["fitness_objectives"])

    def test_generate_java_agent_uses_candidate_class_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Candidate(strategy_prompt="Generate a Java MicroRTS agent.")
            agent = generate_java_agent(candidate, MockGenerationBackend(), Path(temp_dir))
            self.assertEqual(agent.class_name, generated_class_name(candidate.id))
            self.assertTrue(agent.source_path.exists())

    def test_clean_generated_java_output_strips_markdown_fences(self) -> None:
        output = """Here is the Java:
```java
package ai.generated;

import rts.units.UnitTypeTable;

public class GeneratedAgent_test {
    public GeneratedAgent_test(UnitTypeTable utt) {
    }
}
```
Done.
"""
        cleaned = clean_generated_java_output(output)
        self.assertNotIn("```", cleaned)
        self.assertTrue(cleaned.startswith("package ai.generated;"))
        self.assertTrue(cleaned.endswith("}"))

    def test_validate_java_agent_source_rejects_non_java_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "class declaration"):
            validate_java_agent_source("Here is a strategy explanation with no Java.", "GeneratedAgent_test")

    def test_validate_java_agent_source_rejects_nonexistent_helper(self) -> None:
        source = render_function_agent("GeneratedAgent_test", {"controller": "nearestIdleAlly(null, 0, null);"})
        with self.assertRaisesRegex(ValueError, "nearestIdleAlly"):
            validate_java_agent_source(source, "GeneratedAgent_test")

    def test_validate_java_agent_source_rejects_direct_unit_iteration(self) -> None:
        source = render_function_agent(
            "GeneratedAgent_test",
            {"controller": """for (Unit unit : gs.getUnits()) {
            return new Decision();
        }"""},
        )
        with self.assertRaisesRegex(ValueError, "gs.getUnits"):
            validate_java_agent_source(source, "GeneratedAgent_test")

    def test_validate_java_agent_source_accepts_random_ai_body(self) -> None:
        source = render_function_agent("GeneratedAgent_test", {"controller": "private Decision decide(AgentContext context) { return new Decision(); }"})
        validate_java_agent_source(source, "GeneratedAgent_test")

    def test_clean_generated_java_output_preserves_valid_java_source(self) -> None:
        source = """package ai.generated;

import ai.RandomBiasedAI;
import rts.units.UnitTypeTable;

public class GeneratedAgent_test extends RandomBiasedAI {
    public GeneratedAgent_test(UnitTypeTable utt) {
        super(utt);
    }
}
"""
        self.assertEqual(clean_generated_java_output(source), source.strip())

    def test_normalize_java_agent_source_repairs_common_llm_imports(self) -> None:
        source = """package ai.generated;

import ai.RandomBiasedAI;
import ai.UnitTypeTable;

public class GeneratedAgent_test extends RandomBiasedAI {
    public GeneratedAgent_test(UnitTypeTable utt) {
        super(utt);
    }

    @Override
    public void act() {
    }
}
"""
        normalized = normalize_java_agent_source(source)
        self.assertIn("import rts.units.UnitTypeTable;", normalized)
        self.assertNotIn("import ai.UnitTypeTable;", normalized)
        self.assertNotIn("@Override\n    public void act", normalized)

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
        self.assertEqual(metrics.objective, 112)

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
        self.assertEqual(metrics.objective, 0)

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
        self.assertEqual(win_metrics.objective, 100)
        self.assertEqual(loss_metrics.objective, -100)

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
        self.assertEqual(metrics.objective, 0)

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
        config = GamePerformanceConfig(survival_weight=200.0)
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

    def test_persistence_failure_reports_error_without_false_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            round_state_dir = root / "round_states"
            round_state_dir.mkdir()
            (round_state_dir / "round_000000.log").write_text(
                "current time 0 p0 player 0(5) p1 player 1(5)\n",
                encoding="utf-8",
            )
            telemetry_path = root / "telemetry.json"
            telemetry_path.mkdir()
            telemetry, summary, error = persist_match_artifacts(
                raw_result={"winner": 0, "final_tick": 0, "result": "p0_win"},
                round_state_dir=round_state_dir,
                replay_path=root / "replay.xml",
                telemetry_path=telemetry_path,
                summary_path=root / "summary.json",
                match_dir=root,
                tick_limit=10,
                scoring_config=GamePerformanceConfig(),
            )
        self.assertIsNotNone(error)
        self.assertEqual(summary["result"], "p0_win")
        self.assertEqual(telemetry.performance.result_score, 100)

    def test_compile_failure_gets_failed_game_performance(self) -> None:
        objectives = build_objectives(
            compile_result=CompileResult(ok=False, command=[], stderr="javac failed", returncode=1),
            game_metrics=None,
            alignment_result=None,
            failure_category="Java compile failure",
        )
        self.assertEqual(objectives["game_performance"], FAILED_GAME_PERFORMANCE)
        self.assertEqual(objectives["strategy_alignment"], 0.0)

    def test_runtime_failure_gets_failed_game_performance(self) -> None:
        objectives = build_objectives(
            compile_result=CompileResult(ok=True, command=[]),
            game_metrics=None,
            alignment_result=None,
            failure_category="Runtime match failure",
        )
        self.assertEqual(objectives["game_performance"], FAILED_GAME_PERFORMANCE)
        self.assertEqual(objectives["strategy_alignment"], 0.0)

    def test_backend_failure_gets_failed_game_performance(self) -> None:
        class FailingBackend(GenerationBackend):
            def generate(self, candidate: Candidate, class_name: str) -> str:
                raise RuntimeError("backend down")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation = evaluate_candidate(
                Candidate(strategy_prompt="Generate an agent."),
                config=ExperimentConfig.from_mapping({"seed_prompts": ["Generate an agent."]}),
                backend=FailingBackend(),
                alignment_backend="mock",
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                mock=True,
                ordinal=0,
            )
        self.assertEqual(evaluation.candidate.status, "failed")
        self.assertEqual(evaluation.candidate.compile_status, "not_run")
        self.assertEqual(evaluation.result.failure_category, "Backend request failure")
        self.assertEqual(evaluation.candidate.fitness_objectives["game_performance"], FAILED_GAME_PERFORMANCE)
        self.assertEqual(evaluation.candidate.fitness_objectives["strategy_alignment"], 0.0)

    def test_validation_failure_gets_failed_game_performance(self) -> None:
        class UnsafeIterationBackend(GenerationBackend):
            def generate(self, candidate: Candidate, class_name: str) -> str:
                return DEFAULT_MODULE_BODIES["controller"]

            def generate_module(self, candidate: Candidate, class_name: str, module_name: str) -> str:
                if module_name == "controller":
                    return """private Decision decide(AgentContext context) {
                        for (Unit unit : gs.getUnits()) {
                            return new Decision();
                        }
                        return new Decision();
                    }"""
                return DEFAULT_MODULE_BODIES[module_name]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = Candidate(strategy_prompt="Generate an agent.")
            evaluation = evaluate_candidate(
                candidate,
                config=ExperimentConfig.from_mapping({"seed_prompts": ["Generate an agent."]}),
                backend=UnsafeIterationBackend(),
                alignment_backend="mock",
                generated_agents_dir=root / "generated_agents",
                classes_dir=root / "classes",
                mock=True,
                ordinal=0,
            )
        self.assertEqual(evaluation.candidate.status, "failed")
        self.assertEqual(evaluation.result.failure_category, "Java validation failure")
        self.assertIn("gs.getUnits()", evaluation.result.extracted_code)
        self.assertEqual(evaluation.candidate.fitness_objectives["game_performance"], FAILED_GAME_PERFORMANCE)
        self.assertTrue("gs.getUnits" in (evaluation.error or "") or "PlayerAction" in (evaluation.error or ""))
        write_candidate_artifacts(root / "candidates", evaluation)
        debug_dir = root / "failed_candidates" / candidate.id
        self.assertTrue((debug_dir / "raw_llm_output.txt").exists())
        self.assertTrue((debug_dir / "extracted_code.java").exists())
        self.assertTrue((debug_dir / "assembled_java.java").exists())
        self.assertTrue((debug_dir / "failure.json").exists())

    def test_valid_evaluated_candidate_keeps_actual_game_score(self) -> None:
        objectives = build_objectives(
            compile_result=CompileResult(ok=True, command=[]),
            game_metrics=GameMetrics(resource_difference=-24.0, objective=-24.0),
            alignment_result=StrategyAlignmentResult(score=0.5, rationale="ok"),
            failure_category=None,
        )
        self.assertEqual(objectives["game_performance"], -24.0)
        self.assertEqual(objectives["strategy_alignment"], 0.5)

    def test_dominates_uses_objective_vector(self) -> None:
        strong = Candidate(fitness_objectives={"game_performance": 2, "strategy_alignment": 0.8})
        weak = Candidate(fitness_objectives={"game_performance": 1, "strategy_alignment": 0.8})
        tradeoff = Candidate(fitness_objectives={"game_performance": 3, "strategy_alignment": 0.2})
        self.assertTrue(dominates(strong, weak))
        self.assertFalse(dominates(strong, tradeoff))

    def test_analyze_run_falls_back_to_failed_candidate_debug(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "failed_candidates" / "cand_a"
            second = root / "failed_candidates" / "cand_b"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "failure.json").write_text(
                json.dumps(
                    {
                        "failure_category": "Java validation failure",
                        "failure_reason": "Generated Java agent must not iterate directly over gs.getUnits().",
                        "validation_result": {
                            "ok": False,
                            "error": "Generated Java agent must not iterate directly over gs.getUnits().",
                        },
                        "compile_result": None,
                    }
                ),
                encoding="utf-8",
            )
            (second / "failure.json").write_text(
                json.dumps(
                    {
                        "failure_category": "Java compile failure",
                        "failure_reason": "compile failed",
                        "validation_result": {"ok": True, "error": ""},
                        "compile_result": {
                            "stderr": "Agent.java:1: error: cannot find symbol\nStrategyTable table;\n^\n"
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = analyze_run(root)
            report = format_report(summary)

        self.assertEqual(summary["total_candidates"], 2)
        self.assertEqual(summary["failed_candidates"], 2)
        self.assertIsNone(summary["success_count"])
        self.assertEqual(summary["failure_category_counts"]["Java validation failure"], 1)
        self.assertEqual(summary["compile_root_cause_counts"]["cannot find symbol"], 1)
        self.assertIn("Success count: unknown", report)

    def test_analyze_run_reads_legacy_results_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record = {
                "candidate": {
                    "id": "cand_a",
                    "parent_ids": [],
                    "status": "failed",
                    "compile_status": "failed",
                    "fitness_objectives": {"game_performance": -1000.0},
                },
                "compile": {
                    "stderr": "Agent.java:1: error: incompatible types: UnitType cannot be converted to Unit\n"
                },
                "error": None,
            }
            (root / "results.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            summary = analyze_run(root)

        self.assertEqual(summary["total_candidates"], 1)
        self.assertEqual(summary["failed_candidates"], 1)
        self.assertEqual(summary["success_count"], 0)
        self.assertEqual(summary["failure_category_counts"]["Java compile failure"], 1)
        self.assertEqual(summary["compile_root_cause_counts"]["incompatible types"], 1)


if __name__ == "__main__":
    unittest.main()
