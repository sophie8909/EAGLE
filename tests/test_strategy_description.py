from __future__ import annotations

import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_framework_slots_artifacts as fixtures

from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.evolution.offspring import plan_offspring
from eagle.evolution.parent_refresh import (
    build_parent_evaluation_replicas,
    build_self_play_fitness_refresh_replicas,
)
from eagle.operators.adaptive import build_reflection_operator_controller
from eagle.run_artifacts import load_candidate


class StrategyDescriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixtures = fixtures.FrameworkSlotsArtifactTests()
        _, _, self.config, _ = self.fixtures.initialize_run(self.root)
        self.run_dir = self.root / "run"
        self.seed = self.fixtures.write_seed_candidate(self.run_dir, self.config)

    def persist(self, candidate: Candidate) -> None:
        write_candidate_inputs(self.run_dir / "candidates", candidate)
        write_candidate_snapshot(self.run_dir / "candidates", candidate)

    def test_round_trip_preserves_description_without_adding_a_gene(self) -> None:
        description = "工人快攻：先集中工人。\n再攻擊敵方基地。\r\n"
        candidate = replace(self.seed, strategy_description=description)
        self.persist(candidate)
        restored = load_candidate(self.run_dir, candidate.id)
        self.assertEqual(restored.strategy_description, description)
        self.assertEqual(restored.active_genotype_components, ("control_genome",))
        self.assertEqual(restored.to_json_dict()["strategy_description"], description)
        self.assertEqual(restored.to_summary_dict()["strategy_description"], description)
        self.assertNotIn("strategy_description", restored.materialization_to_json_dict())
        description_path = self.run_dir / "candidates" / candidate.id / "genotype/strategy_description.txt"
        self.assertEqual(description_path.read_bytes(), description.encode("utf-8"))

    def test_reader_rejects_description_type_text_and_reference_tampering(self) -> None:
        candidate = replace(self.seed, strategy_description="Build workers, then rush.")
        self.persist(candidate)
        candidate_dir = self.run_dir / "candidates" / candidate.id
        snapshot = candidate_dir / "candidate.json"
        description_path = candidate_dir / "genotype/strategy_description.txt"
        for value in (None, 12, ["rush"]):
            self.persist(candidate)
            payload = json.loads(snapshot.read_text())
            payload["strategy_description"] = value
            snapshot.write_text(json.dumps(payload))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "must be a string"):
                load_candidate(self.run_dir, candidate.id)
        self.persist(candidate)
        description_path.write_text("Different strategy.")
        with self.assertRaisesRegex(ValueError, "artifact mismatch"):
            load_candidate(self.run_dir, candidate.id)
        self.persist(candidate)
        payload = json.loads(snapshot.read_text())
        payload["artifacts"]["strategy_description"] = "../../outside.txt"
        snapshot.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "artifact reference"):
            load_candidate(self.run_dir, candidate.id)
        self.persist(candidate)
        description_path.unlink()
        with self.assertRaisesRegex(ValueError, "artifact mismatch"):
            load_candidate(self.run_dir, candidate.id)

    def test_historical_snapshots_default_to_empty_and_clearing_removes_text(self) -> None:
        described = replace(self.seed, strategy_description="A previous strategy.")
        self.persist(described)
        self.persist(self.seed)
        candidate_dir = self.run_dir / "candidates" / self.seed.id
        self.assertFalse((candidate_dir / "genotype/strategy_description.txt").exists())
        snapshot = candidate_dir / "candidate.json"
        payload = json.loads(snapshot.read_text())
        payload.pop("strategy_description")
        self.assertNotIn("strategy_description", payload["artifacts"])
        snapshot.write_text(json.dumps(payload))
        self.assertEqual(load_candidate(self.run_dir, self.seed.id).strategy_description, "")

    def test_framework_offspring_inherit_parent_a_description_for_local_variation(self) -> None:
        parent_a = replace(self.seed, id="parent_a", control_genome={"horizon": 2}, strategy_description="Rush early.")
        parent_b = replace(self.seed, id="parent_b", control_genome={"horizon": 8}, strategy_description="Wait and defend.")
        for crossover_rate, mutation_rate in ((0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)):
            config = replace(self.config, population_size=1, crossover_rate=crossover_rate, mutation_rate=mutation_rate)
            with patch("eagle.evolution.offspring.select_parent", side_effect=[parent_a, parent_b]):
                plans = plan_offspring(
                    [parent_a, parent_b], config=config, generation=1,
                    rng=random.Random(1), mutations={},
                    operator_controller=build_reflection_operator_controller(config),
                )
            with self.subTest(crossover_rate=crossover_rate, mutation_rate=mutation_rate):
                self.assertEqual(plans[0].candidate.strategy_description, parent_a.strategy_description)
                self.assertIsNone(plans[0].mutation)

    def test_parent_replica_factories_preserve_description(self) -> None:
        source = replace(self.seed, strategy_description="Worker rush.")
        for factory in (build_parent_evaluation_replicas, build_self_play_fitness_refresh_replicas):
            with self.subTest(factory=factory.__name__):
                replica = factory([source], generation=5)[0]
                self.assertEqual(replica.strategy_description, source.strategy_description)
                self.assertEqual(replica.active_genotype_components, ("control_genome",))

    def test_candidate_rejects_non_string_description(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a string"):
            Candidate(id="invalid", strategy_description=None)


if __name__ == "__main__":
    unittest.main()
