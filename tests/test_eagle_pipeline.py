import json
import random
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.artifacts import write_candidate_artifacts
from eagle.config import ExperimentConfig, parse_minimal_yaml
from eagle.evaluation import evaluate_candidate
from eagle.offspring import make_offspring, normalize_prompt
from eagle.search import run_search
from eagle.selection import dominates
from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.game_metrics import GameMetrics, compute_game_metrics
from evaluation.microrts_runner import MatchResult
from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE, build_objectives
from evaluation.strategy_alignment import StrategyAlignmentResult
from generation.agent_template import microrts_blank_strategy_prompt, render_blank_strategy_agent, render_strategy_agent
from generation.backend import GenerationBackend, MockGenerationBackend, generated_class_name
from generation.java_agent_generator import (
    clean_generated_java_output,
    extract_strategy_body,
    generate_java_agent,
    normalize_java_agent_source,
    validate_strategy_body,
    validate_java_agent_source,
)
from scripts.analyze_run import analyze_run, format_report


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

    def test_make_offspring_prompts_stay_under_limits(self) -> None:
        parent = Candidate(strategy_prompt=("keep this intent\n" + "extra\n" * 200).strip())
        config = ExperimentConfig.from_mapping(
            {
                "seed_prompts": ["seed"],
                "population_size": 2,
                "crossover_rate": 1.0,
                "mutation_rate": 1.0,
                "max_prompt_chars": 120,
                "max_prompt_lines": 6,
            }
        )
        offspring = make_offspring(
            [parent, Candidate(strategy_prompt="second parent\n" + "more\n" * 200)],
            config=config,
            generation=1,
            rng=random.Random(1),
            parent_selector=lambda population, rng: population[0],
        )
        self.assertEqual(len(offspring), 2)
        for child in offspring:
            self.assertLessEqual(len(child.strategy_prompt), 120)
            self.assertLessEqual(len(child.strategy_prompt.splitlines()), 6)
            self.assertTrue(child.strategy_prompt.startswith("Blend these two MicroRTS"))

    def test_mock_generation_returns_valid_java_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Candidate(strategy_prompt="Generate an agent.")
            agent = generate_java_agent(candidate, MockGenerationBackend(), Path(temp_dir))
            self.assertIn("package ai.generated;", agent.source)
            self.assertIn("extends AI", agent.source)
            self.assertIn("public PlayerAction getAction", agent.source)
            self.assertIn("return new PlayerAction();", agent.source)
            self.assertIn(f"return new {agent.class_name}();", agent.source)
            self.assertIn("private PlayerAction chooseAction", agent.source)
            self.assertIn("PlayerActionGenerator pag = new PlayerActionGenerator(gs, player);", agent.source)
            self.assertIn("return pag.getRandom();", agent.source)

    def test_seed_prompt_template_expands_to_blank_strategy_prompt(self) -> None:
        config = ExperimentConfig.from_mapping({"seed_prompt_template": "microrts_blank_strategy_agent"})
        self.assertEqual(len(config.seed_prompts), 1)
        self.assertEqual(config.seed_prompts[0], microrts_blank_strategy_prompt())
        self.assertIn("based directly on ai.RandomAI", config.seed_prompts[0])
        self.assertIn("PlayerActionGenerator", config.seed_prompts[0])

    def test_random_ai_baseline_compiles_against_microrts(self) -> None:
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
            self.assertEqual(summary["objectives"], ["game_performance", "strategy_alignment", "prompt_length"])
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
            self.assertIn("prompt_chars", individual["metadata"])
            self.assertIn("prompt_lines", individual["metadata"])

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
        source = render_strategy_agent("GeneratedAgent_test", "nearestIdleAlly(null, 0, null);")
        with self.assertRaisesRegex(ValueError, "nearestIdleAlly"):
            validate_java_agent_source(source, "GeneratedAgent_test")

    def test_validate_java_agent_source_rejects_direct_unit_iteration(self) -> None:
        source = render_strategy_agent(
            "GeneratedAgent_test",
            """for (Unit unit : gs.getUnits()) {
            return new PlayerAction();
        }""",
        )
        with self.assertRaisesRegex(ValueError, "gs.getUnits"):
            validate_java_agent_source(source, "GeneratedAgent_test")

    def test_validate_java_agent_source_accepts_random_ai_body(self) -> None:
        source = render_strategy_agent(
            "GeneratedAgent_test",
            """PlayerActionGenerator pag = new PlayerActionGenerator(gs, player);
        return pag.getRandom();""",
        )
        validate_java_agent_source(source, "GeneratedAgent_test")

    def test_validate_strategy_body_rejects_duplicate_helper_method(self) -> None:
        body = """private boolean commandMove(Unit unit, int x, int y) {
            return false;
        }"""
        with self.assertRaisesRegex(ValueError, "must not define methods"):
            validate_strategy_body(body)

    def test_extract_strategy_body_keeps_only_choose_action_logic(self) -> None:
        source = """package ai.generated;

    private PlayerAction chooseAction(int player, GameState gs) throws Exception {
        PlayerActionGenerator pag = new PlayerActionGenerator(gs, player);
        return pag.getRandom();
    }

    public PlayerAction getAction(int player, GameState gs) {
        return new PlayerAction();
    }
}
"""
        body = extract_strategy_body(source)
        self.assertIn("pag.getRandom()", body)
        self.assertNotIn("getAction", body)

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
            raw_result={"winner": 0, "final_scoreboard": {"p0_resources": 14, "p1_resources": 8}},
        )
        metrics = compute_game_metrics([result])
        self.assertEqual(metrics.resource_difference, 6)
        self.assertGreater(metrics.objective, 6)

    def test_compile_failure_gets_failed_game_performance(self) -> None:
        objectives = build_objectives(
            compile_result=CompileResult(ok=False, command=[], stderr="javac failed", returncode=1),
            game_metrics=None,
            alignment_result=None,
            failure_category="Java compile failure",
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
                return """for (Unit unit : gs.getUnits()) {
                    return new PlayerAction();
                }"""

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
        self.assertIn("gs.getUnits()", evaluation.result.assembled_java)
        self.assertEqual(evaluation.candidate.fitness_objectives["game_performance"], FAILED_GAME_PERFORMANCE)
        self.assertIn("gs.getUnits", evaluation.error or "")
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
