"""Focused contracts for the parent re-materialization diagnostic treatment."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from eagle.aos import ReflectionOperatorMode
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.resume import validate_resume_config
from eagle.search import (
    build_parent_evaluation_replicas,
    run_search,
    write_parent_evaluation_sidecar,
)
from eagle.selection import select_next_generation


class ParentEvaluationModeTests(unittest.TestCase):
    def test_default_reuses_cached_parents(self) -> None:
        config = ExperimentConfig.from_mapping({})
        self.assertEqual(config.parent_evaluation_mode, "reuse_cached")
        config.validate()

    def test_experimental_config_round_trip_and_guards(self) -> None:
        config = ExperimentConfig.from_mapping({
            "candidate_java_mode": "inherited_genotype",
            "reflection_operator_mode": "static",
            "parent_evaluation_mode": "regenerate_same_genotype",
        })
        config.validate()
        restored = ExperimentConfig.from_mapping(config.to_mapping())
        self.assertEqual(restored.parent_evaluation_mode, "regenerate_same_genotype")
        for invalid in (
            replace(config, candidate_java_mode="generated_phenotype"),
            replace(config, reflection_operator_mode=ReflectionOperatorMode.AOS_OPPONENT),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "parent_evaluation_mode"):
                    invalid.validate()

    def test_replicas_keep_genotype_but_clear_evaluation_state(self) -> None:
        source = Candidate(
            id="old-parent",
            generation=3,
            parent_ids=("grandparent",),
            strategy_prompt="policy bytes",
            generation_prompt="generation bytes",
            inherited_java="inherited Java bytes",
            java_parent_id="java-parent",
            generated_java="old generated Java",
            operator="crossover+mutation",
            mutation_type="code",
            strategy_parent_id="strategy-parent",
            generation_prompt_parent_id="prompt-parent",
            source_candidate_ids=("component-source",),
            compile_status="compiled",
            fitness_objectives={"passive": 7.0},
            status="evaluated",
            failure_stage="old_failure",
            failure_reason="old reason",
            artifacts={"old": "artifact"},
            timing={"evaluation": {"duration_seconds": 1}},
            metadata={"mutation": {"type": "code"}},
        )
        replica = build_parent_evaluation_replicas([source], generation=4)[0]
        self.assertNotEqual(replica.id, source.id)
        self.assertEqual(replica.generation, 4)
        self.assertEqual(
            (replica.strategy_prompt, replica.generation_prompt, replica.inherited_java),
            (source.strategy_prompt, source.generation_prompt, source.inherited_java),
        )
        self.assertEqual(replica.strategy_parent_id, source.strategy_parent_id)
        self.assertEqual(replica.generation_prompt_parent_id, source.generation_prompt_parent_id)
        self.assertEqual(replica.java_parent_id, source.java_parent_id)
        self.assertEqual(replica.generated_java, "")
        self.assertEqual(replica.fitness_objectives, {})
        self.assertEqual(replica.status, "pending")
        self.assertIsNone(replica.mutation_type)
        self.assertEqual(replica.operator, "experimental_parent_rematerialization")
        self.assertEqual(replica.artifacts, {})
        self.assertEqual(replica.timing, {})
        self.assertEqual(replica.metadata["experimental_parent_evaluation"], {
            "source_parent_id": "old-parent", "source_birth_generation": 3,
        })

    def test_selection_pool_can_only_select_replicas_and_offspring(self) -> None:
        source = Candidate(id="old-parent", fitness_objectives={"passive": 100.0})
        replica = Candidate(id="replica", fitness_objectives={"passive": 1.0})
        offspring = Candidate(id="offspring", fitness_objectives={"passive": 2.0})
        selected = select_next_generation(
            [replica], [offspring], population_size=2, rng=random.Random(7)
        )
        self.assertNotIn(source.id, {candidate.id for candidate in selected})
        self.assertEqual({candidate.id for candidate in selected}, {"replica", "offspring"})

    def test_sidecar_and_resume_config_record_experimental_mode(self) -> None:
        source = Candidate(
            id="old-parent", generation=1, strategy_prompt="policy",
            generation_prompt="generation", inherited_java="inherited", generated_java="old",
        )
        replica = replace(
            build_parent_evaluation_replicas([source], generation=2)[0],
            generated_java="new", status="evaluated", fitness_objectives={"passive": 4.0},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_parent_evaluation_sidecar(
                root, generation=2, source_parents=[source], replicas=[replica],
                selected_ids={replica.id},
            )
            payload = json.loads((root / "generations" / "generation_0002_parent_rematerialization.json").read_text())
        record = payload["records"][0]
        self.assertEqual(record["source_parent_id"], source.id)
        self.assertEqual(record["replica_candidate_id"], replica.id)
        self.assertEqual(
            record["genotype_sha256"]["source"],
            record["genotype_sha256"]["replica"],
        )
        self.assertTrue(record["genotype_hashes_match"])
        self.assertNotEqual(record["source_generated_java_sha256"], record["replica_generated_java_sha256"])
        self.assertTrue(record["generated_java_changed"])
        self.assertEqual(record["source_fitness_objectives"], {})
        self.assertEqual(record["replica_fitness_objectives"], {"passive": 4.0})
        self.assertEqual(record["source_status"], "pending")
        self.assertEqual(record["replica_status"], "evaluated")
        self.assertTrue(record["selected"])

        persisted = ExperimentConfig.from_mapping({
            "candidate_java_mode": "inherited_genotype",
            "reflection_operator_mode": "static",
            "parent_evaluation_mode": "regenerate_same_genotype",
        })
        with self.assertRaisesRegex(ValueError, "parent_evaluation_mode"):
            validate_resume_config(
                replace(persisted, parent_evaluation_mode="reuse_cached"), persisted
            )

    def test_experimental_run_selects_fresh_replicas_not_old_parents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                ExperimentConfig.from_mapping({
                    "generations": 1,
                    "population_size": 1,
                    "mutation_rate": 0.0,
                    "execution_mode": "mock",
                    "candidate_java_mode": "inherited_genotype",
                    "reflection_operator_mode": "static",
                    "parent_evaluation_mode": "regenerate_same_genotype",
                }),
                runs_dir=root / "runs",
            )
            result = run_search(config, mock=True)
            sidecar = json.loads(
                (result.run_dir / "generations" / "generation_0001_parent_rematerialization.json").read_text()
            )
            record = sidecar["records"][0]
            self.assertNotEqual(record["source_parent_id"], record["replica_candidate_id"])
            self.assertTrue((result.run_dir / "candidates" / record["source_parent_id"] / "candidate.json").is_file())
            self.assertTrue((result.run_dir / "candidates" / record["replica_candidate_id"] / "candidate.json").is_file())
            self.assertNotIn(record["source_parent_id"], {candidate.id for candidate in result.final_population})

    def test_default_run_evaluates_only_the_offspring_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                ExperimentConfig.from_mapping({
                    "generations": 1,
                    "population_size": 1,
                    "mutation_rate": 0.0,
                    "execution_mode": "mock",
                }),
                runs_dir=root / "runs",
            )
            result = run_search(config, mock=True)
            generation_one_ids = [
                path.name for path in (result.run_dir / "candidates").iterdir()
                if path.name.startswith("gen_0001_")
            ]
            self.assertEqual(len(generation_one_ids), 1)
            self.assertFalse(
                (result.run_dir / "generations" / "generation_0001_parent_rematerialization.json").exists()
            )

    def test_resume_reuses_the_same_experimental_replica_path(self) -> None:
        from eagle.resume import resume_search

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(
                ExperimentConfig.from_mapping({
                    "generations": 2,
                    "population_size": 1,
                    "mutation_rate": 0.0,
                    "execution_mode": "mock",
                    "candidate_java_mode": "inherited_genotype",
                    "reflection_operator_mode": "static",
                    "parent_evaluation_mode": "regenerate_same_genotype",
                }),
                runs_dir=root / "runs",
            )
            initial = run_search(config, mock=True)
            (initial.run_dir / "generations" / "generation_0002.json").unlink()
            manifest_path = initial.run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.update(status="interrupted", latest_generation=1)
            manifest_path.write_text(json.dumps(manifest))
            resumed = resume_search(run_dir=initial.run_dir, mock=True)
            self.assertEqual(resumed.completed_generation, 2)
            sidecar = json.loads(
                (resumed.run_dir / "generations" / "generation_0002_parent_rematerialization.json").read_text()
            )
            self.assertEqual(sidecar["mode"], "regenerate_same_genotype")
            self.assertEqual(len(sidecar["records"]), 1)
