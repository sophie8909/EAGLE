"""Tournament-pool integration, immutable contexts, and resume contracts."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.parent_refresh import build_self_play_fitness_refresh_replicas
from eagle.evolution.search import run_search
from eagle.evolution.resume import resume_search
from eagle.evaluation.compiler import compile_generated_agent
from eagle.evaluation.microrts_runner import integrate_microrts_agent
from eagle.opponent_pool import _run_tournament
from eagle.opponent_pool import PROTECTED_OPPONENT_IDS, initial_pool, load_pool
from eagle.opponents import OpponentSpec
from eagle.run_artifacts import load_candidate
from eagle.self_play import (
    assert_shared_self_play_context, expand_self_play_slots, is_self_play_refresh,
    load_self_play_snapshot, self_play_context_id, self_play_context_rows,
    write_self_play_snapshot,
)


class SelfPlayTests(unittest.TestCase):
    @staticmethod
    def config(directory, *, generations=1, capacity=50):
        return replace(ExperimentConfig.from_mapping({
            "generations": generations, "population_size": 1, "execution_mode": "mock",
            "mutation_rate": 0.0, "crossover_rate": 0.0, "reflection_operator_mode": "static",
            "evaluation": {"mode": "self_play", "self_play_refresh_interval": 5,
                           "self_play_opponent_library_capacity": capacity},
        }), runs_dir=Path(directory) / "runs")

    def test_pool_snapshot_refresh_boundaries(self):
        config = self.config(".")
        self.assertEqual(
            [is_self_play_refresh(config, generation) for generation in (0, 1, 5, 6, 10, 11)],
            [False, True, False, True, False, True],
        )
        self.assertFalse(is_self_play_refresh(ExperimentConfig.from_mapping({}), 1))

    def test_generation_zero_evaluates_all_baselines_and_preserves_champions(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            result = run_search(config, mock=True, run_id="pool-baseline")
            for generation in (0, 1):
                snapshot = json.loads((result.run_dir / "generations" / f"generation_{generation:04d}.json").read_text())
                candidate = load_candidate(result.run_dir, snapshot["population"][0]["candidate_id"])
                context = candidate.game_eval_result["evaluation_configuration"]["opponents"]
                self.assertEqual(set(candidate.game_eval_result["opponent_scores"]), set(config.lexicase_case_ids))
                self.assertEqual(candidate.game_eval_result["completed_match_count"], 180)
                self.assertEqual([item["source_opponent_id"] for item in context[:4]], list(PROTECTED_OPPONENT_IDS))
                self.assertEqual(set(candidate.fitness_objectives), {"game_performance"})
                if generation == 0:
                    self.assertEqual({item["source_opponent_id"] for item in context}, {item.opponent_id for item in initial_pool()})
                    self.assertTrue(all(item["source_candidate_id"] is None for item in context))

    def test_snapshot_roundtrip_and_source_hash_fence(self):
        candidate = Candidate(
            id="saved", generation=0, generated_java="saved Java",
            compile_status="success", status="evaluated",
            game_eval_result={"expected_match_count": 180, "completed_match_count": 180},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_candidate_inputs(root / "candidates", candidate)
            phenotype = root / "candidates/saved/phenotype/CandidateAgent.java"
            phenotype.parent.mkdir(parents=True)
            phenotype.write_text(candidate.generated_java, encoding="utf-8")
            write_candidate_snapshot(root / "candidates", candidate)
            game_path = root / "candidates/saved/evaluation/game_performance.json"
            game_path.parent.mkdir(parents=True)
            game_path.write_text(json.dumps(candidate.game_eval_result), encoding="utf-8")
            members = [item for item in initial_pool() if item.opponent_id != "passive"] + [candidate]
            config = self.config(directory)
            write_self_play_snapshot(root, generation=1, candidates=members, config=config)
            restored = load_self_play_snapshot(root, completed_generation=5, config=config)
            self.assertEqual(self_play_context_id(restored), self_play_context_id(members))
            self.assertEqual(self_play_context_rows(restored)[:4], self_play_context_rows(initial_pool())[:4])
            phenotype.write_text("changed Java", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_self_play_snapshot(root, completed_generation=5, config=config)

    def test_snapshot_rejects_missing_permanent_member_and_context_tampering(self):
        members = initial_pool()
        with self.assertRaisesRegex(ValueError, "permanent"):
            expand_self_play_slots([item for item in members if item.opponent_id != "mayari"] + [
                Candidate(id="replacement", generation=0),
            ])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(directory)
            write_self_play_snapshot(root, generation=0, candidates=members, config=config)
            path = root / "generations/generation_0000_self_play_snapshot.json"
            payload = json.loads(path.read_text())
            payload["slots"][4]["source_opponent_id"] = "workerrush"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "context hash"):
                load_self_play_snapshot(root, completed_generation=0, config=config)

    def test_builtin_identity_is_part_of_the_evaluation_context(self):
        rows = self_play_context_rows(initial_pool())
        changed = [dict(row) for row in rows]
        changed[4]["source_opponent_id"] = "different-built-in"
        encode = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertNotEqual(encode(rows), encode(changed))
        self.assertEqual(encode(rows), self_play_context_id(initial_pool()))

    def test_snapshot_rejects_changed_runtime_map_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(self.config(directory), microrts_dir=root / "microrts")
            map_path = config.microrts_dir / config.evaluation_maps[0]
            map_path.parent.mkdir(parents=True)
            map_path.write_text("original map", encoding="utf-8")
            write_self_play_snapshot(root, generation=0, candidates=initial_pool(), config=config)
            map_path.write_text("changed map", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "assets changed"):
                load_self_play_snapshot(root, completed_generation=0, config=config)

    @unittest.skipUnless(shutil.which("java") and shutil.which("javac"), "Java required")
    def test_real_tournament_reuses_entrant_and_supports_builtin_and_saved_defenders(self):
        repository = Path(__file__).resolve().parents[1]
        source_text = (repository / "eagle/java_seeds/worker_rush/CandidateAgent.java").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(self.config(directory), evaluation_map_tick_limits=(2, 2, 2), match_timeout_seconds=30)
            entrant = Candidate(
                id="entrant", generation=0, generated_java=source_text,
                compile_status="success", status="evaluated",
                game_eval_result={"expected_match_count": 180, "completed_match_count": 180},
            )
            for identity in ("entrant", "defender"):
                source = root / "candidates" / identity / "phenotype/CandidateAgent.java"
                source.parent.mkdir(parents=True)
                source.write_text(source_text, encoding="utf-8")
            source = root / "candidates/entrant/phenotype/CandidateAgent.java"
            classes = root / "classes/entrant"
            compiled = compile_generated_agent(source, microrts_dir=config.microrts_dir, output_dir=classes)
            self.assertTrue(compiled.ok, compiled.stderr)
            integrated = integrate_microrts_agent(
                microrts_dir=config.microrts_dir, classes_dir=classes,
                agent_class="ai.generated.CandidateAgent", integration_artifacts_dir=root / "integration",
            )
            self.assertTrue(integrated.ok, integrated.failure_reason)
            shutil.copytree(classes, root / "classes/defender")
            baseline = next(item for item in initial_pool() if item.opponent_id == "lightrush")
            for generation, defender in enumerate((baseline, replace(entrant, id="defender"))):
                self.assertFalse(_run_tournament(
                    root, entrant=entrant, defender=defender, generation=generation, config=config, mock=False,
                ))
                result = json.loads((root / f"archives/opponent_pool_tournaments/generation_{generation:04d}/entrant/result.json").read_text())
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["draws"], 18)
                self.assertEqual(result["errors"], 0)
                self.assertEqual(len({item["match_seed"] for item in result["matches"]}), 18)
                self.assertTrue(result["defender_classes_sha256"])
            self.assertEqual(entrant.game_eval_result["completed_match_count"], 180)

    def test_refresh_uses_maintained_pool_and_keeps_permanent_opponents(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory, generations=6, capacity=10)
            result = run_search(config, mock=True, run_id="pool-refresh")
            for generation in (0, 1, 6):
                active = load_self_play_snapshot(result.run_dir, completed_generation=generation, config=config)
                self.assertEqual(len(active), 10)
                self.assertEqual(
                    [item.opponent_id for item in active[:4] if isinstance(item, OpponentSpec)],
                    list(PROTECTED_OPPONENT_IDS),
                )
            snapshot = json.loads((result.run_dir / "generations/generation_0006_self_play_snapshot.json").read_text())
            self.assertEqual(snapshot["schema_version"], "eagle-self-play-snapshot-v4")
            self.assertEqual(snapshot["opponent_schedule"], "fixed_champions_and_tournament_pool")
            self.assertFalse((result.run_dir / "archives/self_play_generation_cohorts.json").exists())
            self.assertEqual(len(load_pool(result.run_dir, capacity=10)), 10)
            for candidate in result.final_population:
                self.assertEqual(candidate.game_eval_result["evaluation_context_id"], snapshot["context_id"])

    def test_resume_restores_pool_from_committed_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory, generations=1, capacity=10)
            initial = run_search(config, mock=True, run_id="pool-resume")
            checkpoint_path = initial.run_dir / "generations/generation_0001.json"
            checkpoint = json.loads(checkpoint_path.read_text())
            pool_path = initial.run_dir / "archives/self_play_opponents.json"
            self.assertEqual(json.loads(checkpoint["resume_archives"]["archives/self_play_opponents.json"]),
                             json.loads(pool_path.read_text()))
            pool_path.write_text('{"uncommitted": true}', encoding="utf-8")
            partial = initial.run_dir / "archives/opponent_pool_tournaments/generation_0002/partial/result.json"
            partial.parent.mkdir(parents=True)
            partial.write_text('{"partial": true}', encoding="utf-8")
            config_path = initial.run_dir / "config.yaml"
            persisted = yaml.safe_load(config_path.read_text())
            persisted["generations"] = 2
            config_path.write_text(yaml.safe_dump(persisted, sort_keys=False))
            resumed = resume_search(run_dir=initial.run_dir, mock=True)
            self.assertEqual(resumed.completed_generation, 2)
            self.assertEqual(len(load_pool(resumed.run_dir, capacity=10)), 10)
            self.assertFalse(partial.exists())
            preserved = list((initial.run_dir / "archives/interrupted_work").glob(
                "attempt_*/archives/opponent_pool_tournaments/generation_0002/partial/result.json"
            ))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(json.loads(preserved[0].read_text()), {"partial": True})

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

    def test_resume_repairs_stale_fitness_within_the_same_pool_policy(self) -> None:
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
