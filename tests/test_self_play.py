"""Contracts for config-gated immutable-snapshot self-play."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from eagle.aos import ReflectionOperatorMode
from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.opponent_cases import SELF_PLAY_CASES
from eagle.search import (
    build_self_play_fitness_refresh_replicas,
    run_search,
)
from eagle.resume import resume_search
from eagle.self_play import (
    assert_shared_self_play_context,
    select_self_play_library_candidates,
    update_self_play_opponent_library,
    write_self_play_snapshot,
)


class SelfPlayTests(unittest.TestCase):
    def test_default_is_fixed_roster_and_self_play_round_trips(self) -> None:
        self.assertEqual(ExperimentConfig.from_mapping({}).evaluation_mode, "fixed_roster")
        config = ExperimentConfig.from_mapping({
            "reflection_operator_mode": "static",
            "evaluation": {
                "mode": "self_play",
                "self_play_refresh_interval": 3,
                "self_play_opponent_library_capacity": 10,
            },
        })
        config.validate()
        restored = ExperimentConfig.from_mapping(config.to_mapping())
        self.assertEqual(restored.evaluation_mode, "self_play")
        self.assertEqual(restored.self_play_refresh_interval, 3)
        self.assertEqual(restored.self_play_opponent_library_capacity, 10)
        self.assertEqual(restored.algorithm, "game_performance_semantic_tiebreak")
        self.assertEqual(restored.fitness_tie_tolerance, 1.0)
        self.assertTrue(restored.semantic_probes_enabled)
        self.assertEqual(restored.to_mapping()["objectives"], {"game_performance": "maximize"})
        with self.assertRaisesRegex(ValueError, "reflection_operator_mode=static"):
            replace(
                config,
                reflection_operator_mode=ReflectionOperatorMode.AOS_HEAD2HEAD,
            ).validate()
        with self.assertRaisesRegex(ValueError, "opponent_library_capacity"):
            replace(config, self_play_opponent_library_capacity=0).validate()

    def test_opponent_library_persists_order_and_refresh_snapshot_uses_it(self) -> None:
        candidates = [
            Candidate(
                id=f"candidate-{index}",
                generation=4,
                generated_java=f"complete Java {index}",
                compile_status="success",
            )
            for index in range(12)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for candidate in candidates:
                write_candidate_inputs(root / "candidates", candidate)
                phenotype = root / "candidates" / candidate.id / "phenotype"
                phenotype.mkdir(parents=True)
                (phenotype / "CandidateAgent.java").write_text(
                    candidate.generated_java,
                    encoding="utf-8",
                )
                write_candidate_snapshot(root / "candidates", candidate)

            update_self_play_opponent_library(root, candidates, capacity=10)
            # Repeat additions must keep the original append order and never
            # duplicate a runnable phenotype in the managed library.
            update_self_play_opponent_library(root, candidates[5:], capacity=10)
            library = json.loads((root / "archives" / "self_play_opponents.json").read_text())
            self.assertEqual(
                [entry["candidate_id"] for entry in library["opponents"]],
                [candidate.id for candidate in candidates[2:]],
            )

            selected = select_self_play_library_candidates(
                root,
                generation=5,
                refresh_interval=5,
            )
            # At the first five-generation refresh, round-robin selects from
            # the persisted library rather than replacing the context from a
            # current parent population.
            self.assertEqual(
                [candidate.id for candidate in selected],
                [f"candidate-{index}" for index in range(2, 12)],
            )
            write_self_play_snapshot(
                root,
                generation=5,
                candidates=selected,
                refresh_interval=5,
            )
            payload = json.loads(
                (root / "generations" / "generation_0005_self_play_snapshot.json").read_text()
            )
        self.assertEqual([slot["slot_id"] for slot in payload["slots"]], list(SELF_PLAY_CASES))
        self.assertEqual(len(payload["slots"]), 10)
        self.assertEqual(
            payload["source_candidate_ids"],
            [candidate.id for candidate in selected],
        )
        self.assertEqual(payload["opponent_library"]["path"], "archives/self_play_opponents.json")
        self.assertEqual(
            [slot["source_candidate_id"] for slot in payload["slots"]],
            [candidate.id for candidate in selected],
        )

    def test_opponent_library_deduplicates_equal_behavior_vectors(self) -> None:
        candidates = [
            Candidate(
                id="first",
                generation=0,
                generated_java="first Java",
                compile_status="success",
                semantic_signature={
                    "status": "complete", "dataset_id": "d1",
                    "dataset_sha256": "state-set", "normalization_version": "v1",
                    "probe_ids": ["p1", "p2"], "action_hashes": ["a1", "a2"],
                    "global_hash": "g1",
                },
            ),
            Candidate(
                id="equivalent",
                generation=0,
                generated_java="equivalent Java",
                compile_status="success",
                semantic_signature={
                    "status": "complete", "dataset_id": "d1",
                    "dataset_sha256": "state-set", "normalization_version": "v1",
                    "probe_ids": ["p1", "p2"], "action_hashes": ["a1", "a2"],
                    "global_hash": "g1",
                },
            ),
            Candidate(
                id="different",
                generation=0,
                generated_java="different Java",
                compile_status="success",
                semantic_signature={
                    "status": "complete", "dataset_id": "d1",
                    "dataset_sha256": "state-set", "normalization_version": "v1",
                    "probe_ids": ["p1", "p2"], "action_hashes": ["a1", "a3"],
                    "global_hash": "g2",
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for candidate in candidates:
                write_candidate_inputs(root / "candidates", candidate)
                phenotype = root / "candidates" / candidate.id / "phenotype"
                phenotype.mkdir(parents=True)
                (phenotype / "CandidateAgent.java").write_text(
                    candidate.generated_java, encoding="utf-8"
                )
                write_candidate_snapshot(root / "candidates", candidate)
            update_self_play_opponent_library(root, candidates, capacity=10)
            payload = json.loads(
                (root / "archives" / "self_play_opponents.json").read_text()
            )

        self.assertEqual(payload["schema_version"], "eagle-self-play-opponent-library-v2")
        self.assertEqual(
            [entry["candidate_id"] for entry in payload["opponents"]],
            ["first", "different"],
        )
        self.assertEqual(payload["opponents"][0]["semantic_signature"]["action_hashes"], ["a1", "a2"])

    def test_evicted_pool_entries_can_reenter(self) -> None:
        def persist(root: Path, candidate: Candidate) -> None:
            write_candidate_inputs(root / "candidates", candidate)
            phenotype = root / "candidates" / candidate.id / "phenotype"
            phenotype.mkdir(parents=True)
            (phenotype / "CandidateAgent.java").write_text(
                candidate.generated_java,
                encoding="utf-8",
            )
            write_candidate_snapshot(root / "candidates", candidate)

        first = Candidate(id="first", generated_java="same Java", compile_status="success")
        second = Candidate(id="second", generated_java="second Java", compile_status="success")
        replacement = Candidate(
            id="replacement",
            generated_java="replacement Java",
            compile_status="success",
        )
        reentry = Candidate(id="reentry", generated_java="same Java", compile_status="success")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for item in (first, second, replacement, reentry):
                persist(root, item)
            update_self_play_opponent_library(root, [first, second], capacity=2)
            update_self_play_opponent_library(root, [replacement], capacity=2)
            update_self_play_opponent_library(root, [reentry], capacity=2)
            payload = json.loads(
                (root / "archives" / "self_play_opponents.json").read_text()
            )

        self.assertEqual(
            [entry["candidate_id"] for entry in payload["opponents"]],
            ["replacement", "reentry"],
        )

    def test_context_guard_rejects_stale_parent_fitness(self) -> None:
        parent = Candidate(
            id="parent",
            game_eval_result={"evaluation_context_id": "old"},
        )
        offspring = Candidate(
            id="offspring",
            game_eval_result={"evaluation_context_id": "new"},
        )
        with self.assertRaisesRegex(ValueError, "same immutable opponent snapshot"):
            assert_shared_self_play_context([parent, offspring])

    def test_refresh_replica_preserves_java_but_clears_fitness(self) -> None:
        source = Candidate(
            id="source",
            generation=4,
            strategy_prompt="policy",
            generation_prompt="generator",
            inherited_java="inherited",
            generated_java="complete Java",
            compile_status="success",
            fitness_objectives={"passive": 1.0},
            status="evaluated",
        )
        replica = build_self_play_fitness_refresh_replicas([source], generation=5)[0]
        self.assertNotEqual(replica.id, source.id)
        self.assertEqual(replica.generated_java, source.generated_java)
        self.assertEqual(replica.operator, "self_play_fitness_refresh")
        self.assertEqual(replica.fitness_objectives, {})
        self.assertEqual(replica.metadata["self_play_fitness_refresh"]["source_parent_id"], source.id)

    def test_mock_refresh_uses_one_context_and_zero_llm_parent_java(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                ExperimentConfig.from_mapping({
                    "generations": 1,
                    "population_size": 2,
                    "execution_mode": "mock",
                    "mutation_rate": 0.0,
                    "crossover_rate": 0.0,
                    "reflection_operator_mode": "static",
                    "evaluation": {
                        "mode": "self_play",
                        "self_play_refresh_interval": 1,
                    },
                }),
                runs_dir=Path(directory) / "runs",
            )
            result = run_search(config, mock=True, run_id="self-play-refresh")
            sidecar = json.loads(
                (result.run_dir / "generations" / "generation_0001_self_play_parent_refresh.json").read_text()
            )
            contexts = {
                candidate.game_eval_result["evaluation_context_id"]
                for candidate in result.final_population
            }
            refresh_result_paths = list(
                (result.run_dir / "candidates").glob(
                    "gen_0001_*/generation/result.json"
                )
            )
            refresh_results = [json.loads(path.read_text()) for path in refresh_result_paths]

        self.assertEqual(len(contexts), 1)
        self.assertTrue(sidecar["records"])
        self.assertTrue(all(record["generated_java_preserved"] for record in sidecar["records"]))
        self.assertTrue(
            any(item["operation"] == "self_play_fitness_refresh" for item in refresh_results)
        )
        fixed_sources = [
            item for item in refresh_results
            if item["operation"] == "self_play_fitness_refresh"
        ]
        self.assertTrue(all(item["attempts"] == [] for item in fixed_sources))

    def test_five_generation_refresh_selects_persisted_library_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                ExperimentConfig.from_mapping({
                    "generations": 5,
                    "population_size": 1,
                    "execution_mode": "mock",
                    "mutation_rate": 0.0,
                    "crossover_rate": 0.0,
                    "reflection_operator_mode": "static",
                    "evaluation": {
                        "mode": "self_play",
                        "self_play_refresh_interval": 5,
                    },
                }),
                runs_dir=Path(directory) / "runs",
            )
            result = run_search(config, mock=True, run_id="self-play-library-refresh")
            library = json.loads(
                (result.run_dir / "archives" / "self_play_opponents.json").read_text()
            )
            snapshot = json.loads(
                (result.run_dir / "generations" / "generation_0005_self_play_snapshot.json").read_text()
            )
            previous_population = json.loads(
                (result.run_dir / "generations" / "generation_0004.json").read_text()
            )
            expected = select_self_play_library_candidates(
                result.run_dir,
                generation=5,
                refresh_interval=5,
            )

        library_ids = {entry["candidate_id"] for entry in library["opponents"]}
        active_ids = snapshot["source_candidate_ids"]
        self.assertTrue(set(active_ids).issubset(library_ids))
        self.assertEqual(active_ids, [candidate.id for candidate in expected])
        self.assertEqual(snapshot["schema_version"], "eagle-self-play-snapshot-v2")
        self.assertTrue(previous_population["population"])

    def test_resume_migrates_legacy_parent_fitness_to_active_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                ExperimentConfig.from_mapping({
                    "generations": 1,
                    "population_size": 1,
                    "execution_mode": "mock",
                    "mutation_rate": 0.0,
                    "crossover_rate": 0.0,
                    "reflection_operator_mode": "static",
                    "evaluation": {
                        "mode": "self_play",
                        "self_play_refresh_interval": 5,
                    },
                }),
                runs_dir=Path(directory) / "runs",
            )
            initial = run_search(config, mock=True, run_id="self-play-resume")
            persisted_path = initial.run_dir / "config.yaml"
            persisted = yaml.safe_load(persisted_path.read_text())
            persisted["generations"] = 2
            persisted_path.write_text(yaml.safe_dump(persisted, sort_keys=False))
            generation_one = json.loads(
                (initial.run_dir / "generations" / "generation_0001.json").read_text()
            )
            for record in generation_one["population"]:
                game_path = (
                    initial.run_dir
                    / "candidates"
                    / record["candidate_id"]
                    / "evaluation"
                    / "game_performance.json"
                )
                game = json.loads(game_path.read_text())
                game.pop("evaluation_context_id", None)
                game.pop("fitness_case_ids", None)
                game_path.write_text(json.dumps(game))

            resumed = resume_search(run_dir=initial.run_dir, mock=True)

            self.assertEqual(resumed.completed_generation, 2)
            self.assertTrue(
                (resumed.run_dir / "generations" / "generation_0002_self_play_parent_refresh.json").is_file()
            )
            self.assertEqual(
                len({
                    candidate.game_eval_result["evaluation_context_id"]
                    for candidate in resumed.final_population
                }),
                1,
            )


if __name__ == "__main__":
    unittest.main()
