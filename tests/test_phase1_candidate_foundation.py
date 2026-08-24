import json
import random
import tempfile
import unittest
from itertools import product
from pathlib import Path

import yaml

from eagle.artifacts import write_candidate_artifacts, write_candidate_inputs, write_run_config
from eagle.candidate import Candidate, LINEAGE_SCHEMA_VERSION
from eagle.config import ExperimentConfig
from eagle.crossover import CrossoverContext, crossover
from eagle.evaluation import evaluate_candidate
from eagle.search import initialize_population, run_search
from eagle.run_artifacts import load_candidate
from generation.agent_template import JavaTemplatePaths, load_java_template
from generation.backend import MockGenerationBackend


class Phase1CandidateFoundationTests(unittest.TestCase):
    def test_automatic_candidate_id_includes_zero_padded_generation(self) -> None:
        first = Candidate(generation=7)
        second = Candidate(generation=7)
        self.assertRegex(first.id, r"^gen_0007_[0-9a-f]{12}$")
        self.assertNotEqual(first.id, second.id)

    def test_explicit_candidate_id_is_preserved_for_resume_and_fixtures(self) -> None:
        self.assertEqual(Candidate(id="legacy-candidate-id", generation=7).id, "legacy-candidate-id")

    def test_serialized_genotype_has_exactly_two_evolvable_components(self) -> None:
        payload = Candidate(
            id="candidate-a",
            strategy_prompt="policy",
            generation_prompt="translation",
            generated_java="class Generated {}",
        ).to_json_dict()
        self.assertEqual(payload["strategy_prompt"], "policy")
        self.assertEqual(payload["generation_prompt"], "translation")
        self.assertEqual(payload["generated_java"], "class Generated {}")
        self.assertNotIn("previous_code", payload)
        self.assertNotIn("previous_code_parent_id", payload)

    def test_evaluation_does_not_mutate_two_gene_genotype(self) -> None:
        candidate = Candidate(
            id="candidate-a",
            strategy_prompt="defend then expand",
            generation_prompt="translate every policy condition explicitly",
        )
        before = (candidate.strategy_prompt, candidate.generation_prompt)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation = evaluate_candidate(
                candidate,
                config=ExperimentConfig.from_mapping({}),
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
        self.assertEqual(
            (evaluation.candidate.strategy_prompt, evaluation.candidate.generation_prompt),
            before,
        )
        self.assertIn("package ai.generated;", evaluation.candidate.generated_java)

    def test_generator_uses_checked_in_scaffold_not_parent_phenotype(self) -> None:
        parent_java = "package ai.generated;\n// PARENT_PHENOTYPE_SENTINEL\n"
        candidate = Candidate(
            strategy_prompt="policy",
            generation_prompt="translation",
            generated_java=parent_java,
        )
        request = candidate.generation_input(class_name="CandidateAgent")
        scaffold = load_java_template(JavaTemplatePaths())
        self.assertIn(scaffold, request)
        self.assertNotIn("PARENT_PHENOTYPE_SENTINEL", request)

    def test_uniform_crossover_records_only_two_component_parent_ids(self) -> None:
        parent_a = Candidate(id="a", strategy_prompt="policy-a", generation_prompt="code-a", generated_java="java-a")
        parent_b = Candidate(id="b", strategy_prompt="policy-b", generation_prompt="code-b", generated_java="java-b")
        child = crossover(parent_a, parent_b, CrossoverContext(2, 0, random.Random(11)))
        self.assertIn(child.strategy_parent_id, {"a", "b"})
        self.assertIn(child.generation_prompt_parent_id, {"a", "b"})
        self.assertFalse(hasattr(child, "previous_code_parent_id"))
        self.assertNotIn(child.generated_java, {"java-a", "java-b"})
        self.assertEqual(child.parent_ids, ("a", "b"))

    def test_all_four_two_gene_crossover_combinations_preserve_provenance(self) -> None:
        class ChoiceSequence:
            def __init__(self, choices: tuple[int, int]) -> None:
                self.choices = iter(choices)

            def choice(self, values):
                return values[next(self.choices)]

        parent_a = Candidate(id="a", strategy_prompt="same", generation_prompt="same")
        parent_b = Candidate(id="b", strategy_prompt="same", generation_prompt="same")
        observed = set()
        for choices in product((0, 1), repeat=2):
            child = crossover(parent_a, parent_b, CrossoverContext(1, 0, ChoiceSequence(choices)))
            provenance = (child.strategy_parent_id, child.generation_prompt_parent_id)
            observed.add(provenance)
            self.assertEqual(provenance, tuple("a" if choice == 0 else "b" for choice in choices))
        self.assertEqual(len(observed), 4)

    def test_lineage_contains_only_two_component_provenance_fields(self) -> None:
        lineage = Candidate(
            id="child",
            generation=2,
            parent_ids=("a", "b"),
            operator="crossover",
            strategy_parent_id="a",
            generation_prompt_parent_id="b",
        ).lineage_to_json_dict()
        self.assertEqual(lineage["lineage_schema_version"], LINEAGE_SCHEMA_VERSION)
        self.assertEqual(lineage["strategy_parent_id"], "a")
        self.assertEqual(lineage["generation_prompt_parent_id"], "b")
        self.assertEqual(lineage["source_candidate_ids"], ["a", "b"])
        self.assertNotIn("previous_code_parent_id", lineage)

    def test_lineage_json_is_written_for_seed_copy_crossover_and_mutation(self) -> None:
        candidates = (
            Candidate(id="seed", operator="seed"),
            Candidate(id="copy", parent_ids=("seed",), operator="copy", strategy_parent_id="seed", generation_prompt_parent_id="seed"),
            Candidate(id="cross", parent_ids=("a", "b"), operator="crossover", strategy_parent_id="a", generation_prompt_parent_id="b"),
            Candidate(id="mutated", parent_ids=("a", "b"), operator="crossover+mutation", mutation_type="strategy", strategy_parent_id="a", generation_prompt_parent_id="b"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for candidate in candidates:
                write_candidate_inputs(root, candidate)
            payloads = [json.loads((root / candidate.id / "lineage.json").read_text(encoding="utf-8")) for candidate in candidates]
        self.assertTrue(all("previous_code_parent_id" not in payload for payload in payloads))

    def test_candidate_artifacts_separate_two_gene_genotype_and_java_phenotype(self) -> None:
        candidate = Candidate(id="candidate-a", strategy_prompt="policy", generation_prompt="translation")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evaluation = evaluate_candidate(
                candidate,
                config=ExperimentConfig.from_mapping({}),
                backend=MockGenerationBackend(),
                generated_agents_dir=root / "generated",
                classes_dir=root / "classes",
                mock=True,
                ordinal=0,
            )
            write_candidate_artifacts(root / "candidates", evaluation)
            candidate_dir = root / "candidates" / candidate.id
            self.assertEqual((candidate_dir / "genotype" / "policy_prompt.txt").read_text(), "policy")
            self.assertEqual((candidate_dir / "genotype" / "code_generation_prompt.txt").read_text(), "translation")
            self.assertEqual((candidate_dir / "phenotype" / "CandidateAgent.java").read_text(), evaluation.candidate.generated_java)
            self.assertFalse((candidate_dir / "genotype" / "previous_code.java").exists())

    def test_legacy_loader_reads_old_paths_but_discards_previous_code_gene(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            candidate_dir = run_dir / "candidates" / "legacy"
            (candidate_dir / "genotype").mkdir(parents=True)
            (candidate_dir / "generation").mkdir()
            (candidate_dir / "candidate.json").write_text(json.dumps({
                "candidate_id": "legacy",
                "generation": 1,
                "previous_code_parent_id": "old-java-parent",
            }))
            (candidate_dir / "genotype" / "strategy_prompt.txt").write_text("legacy policy")
            (candidate_dir / "genotype" / "generation_prompt.txt").write_text("legacy translation")
            (candidate_dir / "genotype" / "previous_code.java").write_text("LEGACY_PREVIOUS_CODE")
            (candidate_dir / "generation" / "normalized_candidate.java").write_text("legacy phenotype")
            loaded = load_candidate(run_dir, "legacy")
        self.assertEqual(loaded.strategy_prompt, "legacy policy")
        self.assertEqual(loaded.generation_prompt, "legacy translation")
        self.assertEqual(loaded.generated_java, "legacy phenotype")
        self.assertFalse(hasattr(loaded, "previous_code"))
        self.assertFalse(hasattr(loaded, "previous_code_parent_id"))

    def test_every_generation_zero_candidate_has_seed_lineage(self) -> None:
        population = initialize_population(ExperimentConfig.from_mapping({"population_size": 4}))
        self.assertEqual(len(population), 4)
        self.assertTrue(all(candidate.lineage_to_json_dict()["source_candidate_ids"] == [] for candidate in population))

    def test_run_lineage_ids_resolve_to_earlier_acyclic_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text("\n".join(("generations: 2", "population_size: 2", "crossover_rate: 1.0", "mutation_rate: 0.0", f'runs_dir: "{(root / "runs").as_posix()}"')), encoding="utf-8")
            result = run_search(ExperimentConfig.from_file(config_path), config_path=config_path, mock=True, run_id="lineage_run")
            records = [json.loads(path.read_text()) for path in (result.run_dir / "candidates").glob("*/lineage.json")]
        by_id = {record["candidate_id"]: record for record in records}
        for record in records:
            for parent_id in record["parent_ids"]:
                self.assertLess(by_id[parent_id]["generation"], record["generation"])

    def test_run_config_is_the_resolved_single_source_of_truth(self) -> None:
        config = ExperimentConfig.from_mapping({"generations": 4, "population_size": 6, "random_seed": 41})
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            write_run_config(run_dir, config, mock=True)
            payload = yaml.safe_load((run_dir / "config.yaml").read_text())
        self.assertEqual(payload["population_size"], 6)
        self.assertEqual(payload["execution_mode"], "mock")
        self.assertNotIn("match_seeds", payload)

    def test_obsolete_match_seeds_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "match_seeds is obsolete"):
            ExperimentConfig.from_mapping({"match_seeds": [0, 1, 2]})


if __name__ == "__main__":
    unittest.main()
