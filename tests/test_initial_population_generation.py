from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.artifacts import write_candidate_snapshot
from eagle.config import ExperimentConfig
from eagle.initial_population import generation_zero_uses_fixed_java
from eagle.llm import LLMCallLogger
from eagle.search import initialize_population, run_search
from generation.agent_template import JavaTemplatePaths, validate_java_template
from generation.backend import InitialJavaSeedBackend
from generation.java_agent_generator import validate_generated_java_source


CONFIG_PATH = Path(
    "configs/experiments/0903_llm_initial_population/"
    "ministral3_8b_static_0.2_0.2_0.6_llm_mixed.yaml"
)


class ScriptedPolicyBackend:
    model = "scripted-policy-model"
    base_url = "mock://policy"

    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.requests: list[str] = []

    def generate(self, prompt: str) -> str:
        self.requests.append(prompt)
        return next(self.responses)


class InitialPopulationGenerationTests(unittest.TestCase):
    def test_config_generates_nine_policy_prompts_but_keeps_worker_rush_java(self) -> None:
        config = ExperimentConfig.from_file(CONFIG_PATH)
        config.validate()
        self.assertEqual(config.initial_policy_temperature, 0.8)
        backend = ScriptedPolicyBackend(
            [
                json.dumps(
                    {
                        "strategy_prompt": (
                            f"Generated RTS strategy {index}: expand economy, train units, "
                            "defend the base, then attack."
                        )
                    }
                )
                for index in range(1, 10)
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            timing_path = root / "timing.jsonl"
            population = initialize_population(
                config,
                policy_backend=backend,
                candidates_dir=root / "candidates",
                timing_logger=LLMCallLogger(
                    root / "llm_logs",
                    run_id="initial-population-test",
                    timing_path=timing_path,
                ),
            )

            events = [
                json.loads(line)
                for line in timing_path.read_text(encoding="utf-8").splitlines()
            ]
            results = [
                json.loads(
                    (
                        root
                        / "candidates"
                        / candidate.id
                        / "initialization"
                        / "policy_generation"
                        / "result.json"
                    ).read_text(encoding="utf-8")
                )
                for candidate in population[1:]
            ]
            raw_responses = [
                (
                    root
                    / "candidates"
                    / candidate.id
                    / "initialization"
                    / "policy_generation"
                    / "attempts"
                    / "attempt_001"
                    / "response_raw.txt"
                ).read_text(encoding="utf-8")
                for candidate in population[1:]
            ]
            write_candidate_snapshot(root / "candidates", population[1])
            candidate_snapshot = json.loads(
                (root / "candidates" / population[1].id / "candidate.json").read_text(
                    encoding="utf-8"
                )
            )

        worker_policy = Path("seeds/worker_rush_policy.txt").read_text(encoding="utf-8").strip()
        worker_java = config.initial_java_seed_path.read_text(encoding="utf-8")
        self.assertEqual(len(population), 10)
        self.assertEqual(population[0].strategy_prompt, worker_policy)
        self.assertEqual(len({candidate.strategy_prompt for candidate in population}), 10)
        self.assertEqual(
            [candidate.metadata["initial_policy_sample_index"] for candidate in population[1:]],
            list(range(1, 10)),
        )
        self.assertEqual({candidate.inherited_java for candidate in population}, {worker_java})
        self.assertEqual(len(backend.requests), 9)
        self.assertTrue(all("Generate one RTS strategy" in request for request in backend.requests))
        self.assertTrue(
            all(
                "IMMUTABLE MICRORTS GAMEPLAY CONTRACT" in request
                for request in backend.requests
            )
        )
        self.assertTrue(
            all("Opponent implementation name/class" in request for request in backend.requests)
        )
        self.assertTrue(all(result["status"] == "success" for result in results))
        self.assertTrue(all(json.loads(raw)["strategy_prompt"] for raw in raw_responses))
        self.assertEqual(
            candidate_snapshot["artifacts"]["initial_policy_generation"],
            "initialization/policy_generation/result.json",
        )
        self.assertEqual(len(events), 9)
        self.assertTrue(
            all(event["operation_type"] == "initialization" for event in events)
        )
        self.assertTrue(
            all(event["operation_stage"] == "initial_policy_generation" for event in events)
        )
        self.assertTrue(generation_zero_uses_fixed_java(config))
        seed_backend = InitialJavaSeedBackend(config.initial_java_seed_path)
        self.assertEqual(
            {seed_backend.generate(candidate, "CandidateAgent") for candidate in population},
            {worker_java},
        )

    def test_duplicate_generated_policy_is_retried_with_candidate_evidence(self) -> None:
        worker_policy = Path("seeds/worker_rush_policy.txt").read_text(encoding="utf-8").strip()
        config = ExperimentConfig.from_mapping(
            {
                "candidate_java_mode": "inherited_genotype",
                "initial_population_mode": "llm_generated_policies",
                "initial_policy_max_attempts": 2,
                "population_size": 2,
                "seed_prompt_files": ["seeds/worker_rush_policy.txt"],
                "initial_java_seed_path": "eagle/java_seeds/worker_rush/CandidateAgent.java",
            }
        )
        backend = ScriptedPolicyBackend(
            [
                json.dumps({"strategy_prompt": worker_policy}),
                json.dumps({"strategy_prompt": "Build a Barracks and use a timed Ranged attack."}),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            population = initialize_population(
                config,
                policy_backend=backend,
                candidates_dir=root / "candidates",
            )
            artifact_root = (
                root
                / "candidates"
                / population[1].id
                / "initialization"
                / "policy_generation"
            )
            summary = json.loads((artifact_root / "result.json").read_text(encoding="utf-8"))
            first = json.loads(
                (artifact_root / "attempts" / "attempt_001" / "result.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(population[1].strategy_prompt, "Build a Barracks and use a timed Ranged attack.")
        self.assertEqual(summary["selected_attempt"], 2)
        self.assertEqual(first["status"], "failed")
        self.assertIn("duplicates", first["error"])
        self.assertIn("duplicates", backend.requests[1])

    def test_generation_accepts_fenced_json_with_literal_newlines(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "candidate_java_mode": "inherited_genotype",
                "initial_population_mode": "llm_generated_policies",
                "population_size": 2,
                "seed_prompt_files": ["seeds/worker_rush_policy.txt"],
                "initial_java_seed_path": "eagle/java_seeds/worker_rush/CandidateAgent.java",
            }
        )
        backend = ScriptedPolicyBackend(
            [
                """```json
{"strategy_prompt":"Train Workers.
Harvest resources.
Attack the nearest enemy Base."}
```"""
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            population = initialize_population(
                config,
                policy_backend=backend,
                candidates_dir=Path(temp_dir) / "candidates",
            )

        self.assertEqual(
            population[1].strategy_prompt,
            "Train Workers.\nHarvest resources.\nAttack the nearest enemy Base.",
        )
        self.assertIn("Do not use Markdown", backend.requests[0])
        self.assertIn("escape line breaks", backend.requests[0])

    def test_llm_population_mode_rejects_incompatible_boundaries(self) -> None:
        for payload, message in (
            (
                {"initial_population_mode": "llm_generated_policies"},
                "candidate_java_mode=inherited_genotype",
            ),
            (
                {
                    "candidate_java_mode": "inherited_genotype",
                    "initial_population_mode": "llm_generated_policies",
                    "population_size": 1,
                },
                "population_size",
            ),
        ):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, message):
                ExperimentConfig.from_mapping(payload).validate()

    def test_worker_rush_java_seed_satisfies_complete_candidate_contract(self) -> None:
        path = Path("eagle/java_seeds/worker_rush/CandidateAgent.java")
        paths = JavaTemplatePaths(path)
        validate_java_template(paths)
        result = validate_generated_java_source(
            path.read_text(encoding="utf-8"),
            "CandidateAgent",
            template_paths=paths,
        )
        self.assertTrue(result.ok, result.failure_reason)
        strategy = path.read_text(encoding="utf-8").split(
            "// EAGLE_AGENT_STRATEGY_START", 1
        )[1].split("// EAGLE_AGENT_STRATEGY_END", 1)[0]
        self.assertIn("trainWorkers", strategy)
        self.assertIn("commandHarvest", strategy)
        self.assertIn("commandAttack", strategy)

    def test_mock_search_skips_java_generation_only_for_generation_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ExperimentConfig.from_mapping(
                {
                    "runs_dir": temp_dir,
                    "model": {"name": "ministral"},
                    "generation_model": {"name": "qwen3.5-9b"},
                    "candidate_java_mode": "inherited_genotype",
                    "initial_population_mode": "llm_generated_policies",
                    "population_size": 2,
                    "generations": 1,
                    "seed_prompt_files": ["seeds/worker_rush_policy.txt"],
                    "initial_java_seed_path": "eagle/java_seeds/worker_rush/CandidateAgent.java",
                    "mutation_rate": 0.0,
                    "crossover_rate": 0.0,
                    "reflection_operator_mode": "static",
                    "strategy_reflection_probability": 0.2,
                    "prompt_reflection_probability": 0.2,
                    "code_reflection_probability": 0.6,
                }
            )
            result = run_search(config, mock=True, run_id="mixed-initialization")
            generation_zero = json.loads(
                (result.run_dir / "generations" / "generation_0000.json").read_text(
                    encoding="utf-8"
                )
            )
            candidate_ids = [row["candidate_id"] for row in generation_zero["population"]]
            generation_zero_operations = [
                json.loads(
                    (
                        result.run_dir
                        / "candidates"
                        / candidate_id
                        / "generation"
                        / "result.json"
                    ).read_text(encoding="utf-8")
                )["operation"]
                for candidate_id in candidate_ids
            ]
            generation_one_results = list(
                (result.run_dir / "candidates").glob(
                    "gen_0001_*/generation/attempts/attempt_001/result.json"
                )
            )

        self.assertEqual(generation_zero_operations, ["initial_java_seed"] * 2)
        self.assertEqual(len(generation_one_results), 2)


if __name__ == "__main__":
    unittest.main()
