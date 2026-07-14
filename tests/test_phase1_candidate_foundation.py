import json
import random
import tempfile
import unittest
from itertools import product
from pathlib import Path

from eagle.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    OBJECTIVE_FORMULA_VERSION,
    write_candidate_artifacts,
    write_candidate_inputs,
    write_resolved_config,
)
from eagle.candidate import Candidate, LINEAGE_SCHEMA_VERSION
from eagle.config import ExperimentConfig
from eagle.crossover import Crossover, CrossoverContext
from eagle.evaluation import evaluate_candidate
from eagle.search import initialize_population, run_search
from generation.backend import MockGenerationBackend


class Phase1CandidateFoundationTests(unittest.TestCase):
    def test_previous_code_and_generated_java_are_distinct_serialized_state(self) -> None:
        candidate = Candidate(
            id="candidate-a",
            previous_code="class Previous {}",
            generated_java="class Generated {}",
        )

        payload = candidate.to_json_dict()

        self.assertEqual(payload["previous_code"], "class Previous {}")
        self.assertEqual(payload["generated_java"], "class Generated {}")
        self.assertEqual(payload["candidate_id"], "candidate-a")

    def test_evaluation_does_not_overwrite_input_genotype(self) -> None:
        previous_code = "class PreGenerationInput {}"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation = evaluate_candidate(
                Candidate(id="candidate-a", previous_code=previous_code),
                config=ExperimentConfig.from_mapping({"seed_prompts": ["seed"]}),
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )

        self.assertEqual(evaluation.candidate.previous_code, previous_code)
        self.assertIn("package ai.generated;", evaluation.candidate.generated_java)
        self.assertNotEqual(
            evaluation.candidate.previous_code,
            evaluation.candidate.generated_java,
        )

    def test_child_previous_code_inherits_parent_generated_java(self) -> None:
        parents = (
            Candidate(
                id="a",
                previous_code="old-a",
                generated_java="generated-a",
                strategy_prompt="strategy-a",
                generation_prompt="prompt-a",
            ),
            Candidate(
                id="b",
                previous_code="old-b",
                generated_java="generated-b",
                strategy_prompt="strategy-b",
                generation_prompt="prompt-b",
            ),
        )

        child = Crossover().crossover(
            *parents,
            CrossoverContext(1, 0, random.Random(3)),
        )

        source = next(
            parent for parent in parents if parent.id == child.previous_code_parent_id
        )
        self.assertEqual(child.previous_code, source.generated_java)
        self.assertNotIn(child.previous_code, {"old-a", "old-b"})

    def test_uniform_crossover_records_all_component_parent_ids(self) -> None:
        parent_a = Candidate(
            id="a",
            strategy_prompt="strategy-a",
            generated_java="generated-a",
            generation_prompt="prompt-a",
        )
        parent_b = Candidate(
            id="b",
            strategy_prompt="strategy-b",
            generated_java="generated-b",
            generation_prompt="prompt-b",
        )

        child = Crossover().crossover(
            parent_a,
            parent_b,
            CrossoverContext(2, 0, random.Random(11)),
        )

        self.assertIn(child.strategy_parent_id, {"a", "b"})
        self.assertIn(child.previous_code_parent_id, {"a", "b"})
        self.assertIn(child.generation_prompt_parent_id, {"a", "b"})
        self.assertEqual(child.operator, "crossover")
        self.assertEqual(child.parent_ids, ("a", "b"))

    def test_crossover_provenance_is_deterministic_for_seeded_rng(self) -> None:
        parent_a = Candidate(
            id="a",
            strategy_prompt="strategy-a",
            generated_java="generated-a",
            generation_prompt="prompt-a",
        )
        parent_b = Candidate(
            id="b",
            strategy_prompt="strategy-b",
            generated_java="generated-b",
            generation_prompt="prompt-b",
        )

        first = Crossover().crossover(
            parent_a,
            parent_b,
            CrossoverContext(1, 0, random.Random(19)),
        )
        second = Crossover().crossover(
            parent_a,
            parent_b,
            CrossoverContext(1, 0, random.Random(19)),
        )

        self.assertEqual(
            (
                first.strategy_parent_id,
                first.previous_code_parent_id,
                first.generation_prompt_parent_id,
            ),
            (
                second.strategy_parent_id,
                second.previous_code_parent_id,
                second.generation_prompt_parent_id,
            ),
        )
        self.assertEqual(first.previous_code, second.previous_code)

    def test_all_crossover_source_combinations_remain_exact_with_equal_text(self) -> None:
        class ChoiceSequence:
            def __init__(self, choices: tuple[int, int, int]) -> None:
                self.choices = iter(choices)

            def choice(self, values):
                return values[next(self.choices)]

        parent_a = Candidate(
            id="a",
            strategy_prompt="equal strategy",
            previous_code="old-a",
            generated_java="equal generated java",
            generation_prompt="equal prompt",
        )
        parent_b = Candidate(
            id="b",
            strategy_prompt="equal strategy",
            previous_code="old-b",
            generated_java="equal generated java",
            generation_prompt="equal prompt",
        )

        observed = set()
        for choices in product((0, 1), repeat=3):
            child = Crossover().crossover(
                parent_a,
                parent_b,
                CrossoverContext(1, 0, ChoiceSequence(choices)),
            )
            provenance = (
                child.strategy_parent_id,
                child.previous_code_parent_id,
                child.generation_prompt_parent_id,
            )
            observed.add(provenance)
            self.assertEqual(
                provenance,
                tuple("a" if choice == 0 else "b" for choice in choices),
            )
            self.assertEqual(child.previous_code, "equal generated java")

        self.assertEqual(len(observed), 8)

    def test_seed_lineage_serializes_canonical_null_provenance(self) -> None:
        lineage = Candidate(id="seed-a", generation=0).lineage_to_json_dict()

        self.assertEqual(lineage["lineage_schema_version"], LINEAGE_SCHEMA_VERSION)
        self.assertEqual(lineage["candidate_id"], "seed-a")
        self.assertEqual(lineage["parent_ids"], [])
        self.assertEqual(lineage["operator"], "seed")
        self.assertIsNone(lineage["mutation_type"])
        self.assertIsNone(lineage["strategy_parent_id"])
        self.assertIsNone(lineage["previous_code_parent_id"])
        self.assertIsNone(lineage["generation_prompt_parent_id"])
        self.assertEqual(lineage["source_candidate_ids"], [])

    def test_every_generation_zero_candidate_has_seed_lineage(self) -> None:
        population = initialize_population(
            ExperimentConfig.from_mapping(
                {"seed_prompts": ["seed"], "population_size": 4}
            )
        )

        self.assertEqual(len(population), 4)
        for candidate in population:
            lineage = candidate.lineage_to_json_dict()
            self.assertEqual(lineage["operator"], "seed")
            self.assertEqual(lineage["parent_ids"], [])
            self.assertEqual(lineage["source_candidate_ids"], [])

    def test_crossover_lineage_serializes_exact_provenance(self) -> None:
        candidate = Candidate(
            id="child",
            generation=2,
            parent_ids=("a", "b"),
            operator="crossover",
            strategy_parent_id="a",
            previous_code_parent_id="b",
            generation_prompt_parent_id="a",
        )

        lineage = candidate.lineage_to_json_dict()

        self.assertEqual(lineage["parent_ids"], ["a", "b"])
        self.assertEqual(lineage["strategy_parent_id"], "a")
        self.assertEqual(lineage["previous_code_parent_id"], "b")
        self.assertEqual(lineage["generation_prompt_parent_id"], "a")
        self.assertEqual(lineage["source_candidate_ids"], ["a", "b"])

    def test_lineage_json_is_written_for_every_operator_shape(self) -> None:
        candidates = (
            Candidate(id="seed", operator="seed"),
            Candidate(
                id="copy",
                parent_ids=("seed",),
                operator="copy",
                strategy_parent_id="seed",
                previous_code_parent_id="seed",
                generation_prompt_parent_id="seed",
            ),
            Candidate(
                id="cross",
                parent_ids=("a", "b"),
                operator="crossover",
                strategy_parent_id="a",
                previous_code_parent_id="b",
                generation_prompt_parent_id="a",
            ),
            Candidate(
                id="cross-mutation",
                parent_ids=("a", "b"),
                operator="crossover+mutation",
                mutation_type="strategy",
                strategy_parent_id="a",
                previous_code_parent_id="b",
                generation_prompt_parent_id="a",
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for candidate in candidates:
                write_candidate_inputs(root, candidate)
            payloads = {
                candidate.id: json.loads(
                    (root / candidate.id / "lineage.json").read_text(encoding="utf-8")
                )
                for candidate in candidates
            }

        self.assertEqual(set(payloads), {candidate.id for candidate in candidates})
        self.assertEqual(payloads["cross-mutation"]["mutation_type"], "strategy")

    def test_run_lineage_ids_resolve_to_earlier_acyclic_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                "\n".join(
                    (
                        "seed_prompts:",
                        '  - "seed-a"',
                        '  - "seed-b"',
                        "generations: 2",
                        "population_size: 2",
                        "crossover_rate: 1.0",
                        "mutation_rate: 0.0",
                        f'runs_dir: "{(root / "runs").as_posix()}"',
                    )
                ),
                encoding="utf-8",
            )
            config = ExperimentConfig.from_file(config_path)
            result = run_search(
                config,
                config_path=config_path,
                mock=True,
                run_id="lineage_run",
            )
            lineage_records = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (result.run_dir / "candidates").glob("*/lineage.json")
            ]

        by_id = {record["candidate_id"]: record for record in lineage_records}
        self.assertEqual(len(by_id), 4)
        for record in lineage_records:
            for parent_id in record["parent_ids"]:
                self.assertIn(parent_id, by_id)
                self.assertLess(by_id[parent_id]["generation"], record["generation"])

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(candidate_id: str) -> None:
            self.assertNotIn(candidate_id, visiting)
            if candidate_id in visited:
                return
            visiting.add(candidate_id)
            for parent_id in by_id[candidate_id]["parent_ids"]:
                visit(parent_id)
            visiting.remove(candidate_id)
            visited.add(candidate_id)

        for candidate_id in by_id:
            visit(candidate_id)

    def test_candidate_artifacts_preserve_genotype_and_phenotype_files(self) -> None:
        previous_code = "class PreGenerationInput {}"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation = evaluate_candidate(
                Candidate(id="candidate-a", previous_code=previous_code),
                config=ExperimentConfig.from_mapping({"seed_prompts": ["seed"]}),
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=True,
                ordinal=0,
            )
            candidates_dir = root / "candidates"
            write_candidate_artifacts(candidates_dir, evaluation)
            candidate_dir = candidates_dir / "candidate-a"
            genotype = (candidate_dir / "genotype" / "previous_code.java").read_text(
                encoding="utf-8"
            )
            phenotype = (
                candidate_dir / "generation" / "normalized_candidate.java"
            ).read_text(encoding="utf-8")

        self.assertEqual(genotype, previous_code)
        self.assertEqual(phenotype, evaluation.candidate.generated_java)
        self.assertNotEqual(genotype, phenotype)

    def test_resolved_config_reflects_parsed_values_and_runtime_overrides(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "seed_prompts": ["seed"],
                "generations": 4,
                "population_size": 6,
                "crossover_rate": 0.25,
                "mutation_rate": 0.5,
                "random_seed": 41,
                "generation_backend": "openai",
                "llm_model": "configured-model",
                "tick_limit": 345,
                "opponent": "ai.PassiveAI",
                "matches_per_candidate": 3,
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            write_resolved_config(run_dir, config, mock=True)
            payload = json.loads(
                (run_dir / "resolved_config.json").read_text(encoding="utf-8")
            )

        self.assertEqual(payload["population_size"], 6)
        self.assertEqual(payload["generation_count"], 4)
        self.assertEqual(payload["crossover_rate"], 0.25)
        self.assertEqual(payload["mutation_rate"], 0.5)
        self.assertEqual(payload["matches_per_candidate"], 3)
        self.assertEqual(payload["opponent"], "ai.abstraction.LightRush")
        self.assertEqual(payload["max_cycles"], 345)
        self.assertEqual(payload["ea_random_seed"], 41)
        self.assertEqual(payload["llm_backend"], "mock")
        self.assertIsNone(payload["llm_model"])
        self.assertIsNone(payload["llm_temperature"])
        self.assertEqual(payload["retry_policy"]["max_attempts"], 1)
        self.assertEqual(payload["artifact_schema_version"], ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(
            payload["objective_formula_version"],
            OBJECTIVE_FORMULA_VERSION,
        )
        self.assertRegex(payload["git_commit_hash"], r"^[0-9a-f]{40}$")
        self.assertIsNone(payload["microrts_match_seeds"])
        self.assertIsNone(payload["prompt_version"])
        self.assertIn("microrts_match_seeds", payload["unsupported"])
        self.assertIn("prompt_version", payload["unsupported"])

    def test_generic_metadata_is_not_needed_to_reconstruct_lineage(self) -> None:
        candidate = Candidate(
            id="child",
            parent_ids=("a", "b"),
            operator="crossover",
            strategy_parent_id="b",
            previous_code_parent_id="a",
            generation_prompt_parent_id="b",
            metadata={},
        )

        lineage = candidate.lineage_to_json_dict()

        self.assertEqual(lineage["strategy_parent_id"], "b")
        self.assertEqual(lineage["previous_code_parent_id"], "a")
        self.assertEqual(lineage["generation_prompt_parent_id"], "b")
        self.assertEqual(lineage["source_candidate_ids"], ["b", "a"])


if __name__ == "__main__":
    unittest.main()
