"""Root-seeded evaluation stays stable despite thread completion order."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import base64
import io
import json
import random
from contextlib import redirect_stdout
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.compiler import SEEDED_RUNTIME_SOURCES, compile_generated_agent
from eagle.evaluation.determinism import derive_seed
from eagle.evaluation.game_metrics import compute_game_metrics
from eagle.evaluation.matches import evaluate_matches
from eagle.evaluation.parent_offspring import evaluate_parent_vs_offspring
from eagle.evaluation.records import EvaluationOpponent
from eagle.evaluation.runtime_evaluation import MatchResult, run_microrts_match
from eagle.evaluation.semantic_signature import SemanticDataset, evaluate_semantic_signature
from eagle.final_test import FINAL_TEST_OPPONENTS, _run_final_matrix, main as final_test_main
from eagle.generation.java_agent_generator import GeneratedJavaAgent


class EvaluationReproducibilityTests(unittest.TestCase):
    @staticmethod
    def _stochastic_match(**kwargs):
        # Finish in a different order from the matrix without sharing any RNG.
        time.sleep((3 - kwargs["match_index"] % 4) * 0.001)
        rng = random.Random(kwargs["match_seed"])
        winner = rng.choice((-1, 0, 1))
        return MatchResult(
            ok=True, score=rng.uniform(-100, 100), command=[], winner=winner,
            candidate_player=kwargs["candidate_player"],
            match_index=kwargs["match_index"], match_seed=kwargs["match_seed"],
            map_id=kwargs["map_id"], map_path=kwargs["map_path"],
            round_index=kwargs["round_index"], raw_result={"winner": winner},
        )

    def test_matrix_seed_order_and_aggregation_repeat_across_worker_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "CandidateAgent.java"
            source.write_text("class CandidateAgent {}", encoding="utf-8")
            agent = GeneratedJavaAgent("CandidateAgent", "ai.generated", source.read_text(), source)
            candidate = Candidate(id="candidate-a", generation=2)
            opponents = (EvaluationOpponent("random", "ai.RandomAI"), EvaluationOpponent("passive", "ai.PassiveAI"))
            snapshots = []
            seeds = []
            with patch("eagle.evaluation.matches.run_microrts_match", side_effect=self._stochastic_match):
                for workers, seed in ((1, 7), (4, 7), (4, 7), (4, 8)):
                    config = replace(ExperimentConfig.from_mapping({}), match_workers=workers, random_seed=seed)
                    results, error = evaluate_matches(
                        candidate=candidate, agent=agent, config=config, classes_dir=root,
                        match_artifacts_dir=None, mock=True, ordinal=0, opponent_pool=opponents,
                    )
                    self.assertIsNone(error)
                    self.assertEqual([item.match_index for item in results], list(range(36)))
                    seeds.append([item.match_seed for item in results])
                    metrics = compute_game_metrics(results, fixed_opponent_weights={"random": 1, "passive": 1}, expected_match_count=36, expected_matches_per_opponent=18)
                    snapshots.append(([item.to_json_dict() for item in results], metrics.to_json_dict()))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(snapshots[1], snapshots[2])
            self.assertNotEqual(seeds[0], seeds[3])
            self.assertEqual(len(set(seeds[0])), 36)

    def test_head_to_head_rewards_repeat_across_worker_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots = []
            with patch("eagle.evaluation.parent_offspring.run_microrts_match", side_effect=self._stochastic_match):
                for workers in (1, 4, 4):
                    config = replace(ExperimentConfig.from_mapping({}), match_workers=workers, random_seed=37)
                    result = evaluate_parent_vs_offspring(Candidate(id="offspring"), Candidate(id="parent"), config=config, classes_dir=root, match_artifacts_dir=root, mock=True)
                    snapshots.append((result.to_dict(), result.reward))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(snapshots[1], snapshots[2])

    def test_final_benchmark_repeats_across_worker_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("eagle.final_test.FINAL_TEST_OPPONENTS", FINAL_TEST_OPPONENTS[:1]), patch("eagle.final_test.FINAL_TEST_GAMES_PER_SIDE", 2), patch("eagle.final_test._prepare_worker_rush_opponent", return_value=root), patch("eagle.final_test._prepare_safe_allinbot_opponent", return_value=root), patch("eagle.final_test._opponent_classpath", return_value=()), patch("eagle.final_test.hash_file", return_value="source"), patch("eagle.final_test.run_microrts_match", side_effect=self._stochastic_match):
                snapshots = [
                    _run_final_matrix(config=replace(ExperimentConfig.from_mapping({}), match_workers=workers, random_seed=37), repository_root=root, candidate={"candidate_id": "a"}, classes_dir=root, output_dir=root)
                    for workers in (1, 4, 4)
                ]
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(snapshots[1], snapshots[2])
            self.assertTrue(all(item["match"]["match_seed"] is not None for item in snapshots[0]))

    def test_final_benchmark_recompiles_historical_classes_before_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
            source_path = root / "candidates/a/phenotype/CandidateAgent.java"
            source_path.parent.mkdir(parents=True)
            source_path.write_text("class CandidateAgent {}", encoding="utf-8")
            old_class = root / "classes/a/ai/generated/CandidateAgent.class"
            old_class.parent.mkdir(parents=True)
            old_class.write_bytes(b"old")
            config = replace(ExperimentConfig.from_mapping({}), random_seed=37)
            with patch("eagle.final_test._load_config", return_value=config), \
                 patch("eagle.final_test._select_candidate", return_value={"candidate_id": "a"}), \
                 patch("eagle.final_test.compile_generated_agent", return_value=Mock(ok=True)) as compile_agent, \
                 patch("eagle.final_test.preflight_evaluation_opponents"), \
                 patch("eagle.final_test.integrate_microrts_agent", return_value=Mock(ok=True)) as integrate, \
                 patch("eagle.final_test._run_final_matrix", return_value=[]) as run_matrix, \
                 patch("eagle.final_test._build_summary", return_value={}), \
                 patch("eagle.final_test._write_outputs"), \
                 patch("eagle.final_test._markdown_table", return_value="ok"), redirect_stdout(io.StringIO()):
                self.assertEqual(final_test_main(["--run-dir", str(root)]), 0)
            fresh_classes = root / "final_test/classes/a"
            self.assertEqual(compile_agent.call_args.args[0], source_path)
            self.assertEqual(compile_agent.call_args.kwargs["output_dir"], fresh_classes)
            self.assertEqual(integrate.call_args.kwargs["classes_dir"], fresh_classes)
            self.assertEqual(integrate.call_args.kwargs["seed"], derive_seed(37, "integration", "a"))
            self.assertEqual(run_matrix.call_args.kwargs["classes_dir"], fresh_classes)
            self.assertEqual(run_matrix.call_args.kwargs["source_path"], source_path)
            self.assertEqual(old_class.read_bytes(), b"old")

    def test_semantic_cache_separates_seed_and_runtime_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = SemanticDataset(root / "dataset", {
                "dataset_id": "d", "dataset_sha256": "hash", "probes": [{
                    "probe_id": "p", "state_path": "state.xml", "player_side": 0,
                    "map_id": "m", "phase": "early",
                }],
            })
            encoded = base64.b64encode(b"[]").decode("ascii")
            arguments = dict(candidate_id="a", agent_class="ai.generated.CandidateAgent", candidate_classes_dir=root, phenotype_sha256="source", dataset=dataset, microrts_dir=root, cache_root=root / "run/archives/cache", timeout_seconds=5)
            with patch("eagle.evaluation.semantic_signature._compile_helper"), \
                 patch("eagle.evaluation.semantic_signature._run", return_value=Mock(stdout=f"EAGLE_ACTION\tp\t{encoded}\n")) as run:
                first = evaluate_semantic_signature(**arguments, random_seed=7)
                repeated = evaluate_semantic_signature(**arguments, random_seed=7)
                changed_seed = evaluate_semantic_signature(**arguments, random_seed=8)
                with patch("eagle.evaluation.semantic_signature._runtime_source_identity", return_value={"rts/RandomSource.java": "changed"}):
                    changed_runtime = evaluate_semantic_signature(**arguments, random_seed=7)
            self.assertEqual(first.status, "complete")
            self.assertTrue(repeated.wrapper["cache_hit"])
            self.assertFalse(changed_seed.wrapper["cache_hit"])
            self.assertFalse(changed_runtime.wrapper["cache_hit"])
            self.assertEqual(run.call_count, 3)
            self.assertNotEqual(run.call_args_list[0].args[0][1], run.call_args_list[1].args[0][1])
            self.assertNotEqual(first.wrapper["cache_key"], changed_runtime.wrapper["cache_key"])

    def test_low_level_match_defaults_to_seed_zero_and_rejects_override(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = dict(microrts_dir=Path(directory), classes_dir=Path(directory), agent_class="ai.generated.CandidateAgent", opponent="ai.RandomAI", tick_limit=2, match_index=0, mock=True, artifact_mode="compact")
            result = run_microrts_match(**arguments)
            self.assertEqual(result.match_seed, 0)
            self.assertIn("-Deagle.match.seed=0", result.command)
            with self.assertRaisesRegex(ValueError, "derived match_seed"):
                run_microrts_match(**arguments, match_seed=7, java_system_properties={"eagle.match.seed": "8"})

    def test_seed_namespace_is_unambiguous(self):
        self.assertEqual(derive_seed(7, "ea", 1, "mutation"), derive_seed(7, "ea", 1, "mutation"))
        self.assertNotEqual(derive_seed(7, "a", "b"), derive_seed(7, "a\x1fb"))
        self.assertNotEqual(derive_seed(7, "mutation"), derive_seed(7, "crossover"))

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "Java required")
    def test_real_microrts_matches_repeat_with_seeded_overlay_across_workers(self):
        repository = Path(__file__).resolve().parents[1]
        microrts = repository / "third_party/microrts"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            classes = root / "classes"
            compilation = compile_generated_agent(repository / "eagle/java_seeds/worker_rush/CandidateAgent.java", microrts_dir=microrts, output_dir=classes)
            self.assertTrue(compilation.ok, compilation.stderr)
            for name in SEEDED_RUNTIME_SOURCES:
                self.assertTrue((classes / Path(name).with_suffix(".class")).is_file(), name)
                self.assertIn(str(microrts / "src" / name), compilation.command)
            def run(item):
                run_index, match_index = item
                result = run_microrts_match(
                    microrts_dir=microrts, classes_dir=classes,
                    agent_class="ai.generated.CandidateAgent", opponent="ai.RandomBiasedAI",
                    tick_limit=30, match_index=match_index,
                    match_artifacts_dir=root / f"run-{run_index}", artifact_mode="compact",
                    match_seed=derive_seed(37, "real-test", match_index), timeout_seconds=30,
                )
                self.assertTrue(result.ok, result.failure_reason or result.stderr)
                return (result.match_seed, result.winner, result.score, result.final_cycle, result.raw_result)
            snapshots = []
            for run_index, workers in enumerate((1, 3, 3)):
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    snapshots.append(list(executor.map(run, ((run_index, index) for index in range(3)))))
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(snapshots[1], snapshots[2])

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "Java required")
    def test_real_java_random_streams_repeat_across_parallel_processes(self):
        source = Path(__file__).resolve().parents[1] / "third_party/microrts/src/rts/RandomSource.java"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "SeedProbe.java"
            probe.write_text("import rts.RandomSource; public class SeedProbe { public static void main(String[] args) { java.util.Random r = RandomSource.create(args[0]); for (int i = 0; i < 5; i++) System.out.println(r.nextLong()); } }", encoding="utf-8")
            subprocess.run(["javac", "-d", str(root), str(source), str(probe)], check=True, capture_output=True, text=True)
            def sample(seed):
                return subprocess.run(["java", f"-Deagle.match.seed={seed}", "-cp", str(root), "SeedProbe", "rts.GameState"], check=True, capture_output=True, text=True).stdout
            serial = [sample(seed) for seed in (7, 8, 9)]
            with ThreadPoolExecutor(max_workers=3) as executor:
                self.assertEqual(serial, list(executor.map(sample, (7, 8, 9))))
            self.assertEqual(serial[0], sample(7))
            self.assertEqual(len(set(serial)), 3)
            invalid = subprocess.run(["java", "-Deagle.match.seed=invalid", "-cp", str(root), "SeedProbe", "test"], capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)


if __name__ == "__main__":
    unittest.main()
