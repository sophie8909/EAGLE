from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from eagle import final_test, fixed_evaluation
from eagle.config import ExperimentConfig
from eagle.evaluation.compiler import CompileResult
from eagle.evaluation.runtime_evaluation import MatchResult
from eagle.run_artifacts import GENERATION_SCHEMA_VERSION, RUN_SCHEMA_VERSION


class FixedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.output = self.run / "fixed_evaluation"
        self.config = replace(ExperimentConfig.from_mapping({}), microrts_dir=self.root / "microrts")
        for name in ("src", "bin", "lib"):
            (self.config.microrts_dir / name).mkdir(parents=True)
        for path in self.config.evaluation_maps:
            source = self.config.microrts_dir / path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("<map />", encoding="utf-8")
        self.write_json(self.run / "manifest.json", {
            "schema_version": RUN_SCHEMA_VERSION, "status": "complete",
            "latest_generation": 5, "completed_generations": [0, 5],
        })
        (self.run / "config.yaml").write_text("random_seed: 7\n", encoding="utf-8")
        self.add_candidate("initial", generation=0, score=999)
        self.add_candidate("later", generation=5, score=-999)
        self.snapshot(0, [("initial", 1.0)])
        self.snapshot(5, [("initial", 0.5), ("later", 2.0)])

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def add_candidate(self, identity, *, generation=0, score=0, status="evaluated"):
        self.write_json(self.run / "candidates" / identity / "candidate.json", {
            "candidate_id": identity, "generation": generation, "status": status,
            "fitness_objectives": {"game_performance": score},
        })
        source = self.run / "candidates" / identity / "phenotype" / "CandidateAgent.java"
        source.parent.mkdir(parents=True)
        source.write_text("class CandidateAgent {}", encoding="utf-8")
        old_class = self.run / "classes" / identity / "ai" / "generated" / "CandidateAgent.class"
        old_class.parent.mkdir(parents=True)
        old_class.write_bytes(b"original")

    def snapshot(self, generation, items):
        self.write_json(self.run / "generations" / f"generation_{generation:04d}.json", {
            "schema_version": GENERATION_SCHEMA_VERSION, "generation": generation,
            "population": [
                {"candidate_id": identity, "status": "evaluated",
                 "fitness_objectives": {"game_performance": score}} for identity, score in items
            ],
        })

    @staticmethod
    def match(**kwargs):
        return MatchResult(
            ok=True, score=4.0, command=[], winner=kwargs["candidate_player"],
            candidate_id=kwargs["candidate_id"], generation=kwargs["generation"],
            candidate_player=kwargs["candidate_player"], match_seed=kwargs["match_seed"],
            match_index=kwargs["match_index"], map_id=kwargs["map_id"],
        )

    @staticmethod
    def compile(source_path, *, output_dir, **kwargs):
        target = output_dir / "ai/generated/CandidateAgent.class"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"fresh")
        return CompileResult(ok=True, command=["javac", str(source_path)])

    def runtime(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("eagle.fixed_evaluation.final_test._load_config", return_value=self.config))
        stack.enter_context(patch("eagle.final_test.preflight_evaluation_opponents"))
        stack.enter_context(patch("eagle.final_test.FINAL_TEST_OPPONENTS", final_test.FINAL_TEST_OPPONENTS[:1]))
        stack.enter_context(patch("eagle.final_test.FINAL_TEST_GAMES_PER_SIDE", 2))
        stack.enter_context(patch("eagle.final_test._prepare_worker_rush_opponent", return_value=self.root))
        stack.enter_context(patch("eagle.final_test._prepare_safe_allinbot_opponent", return_value=self.root))
        stack.enter_context(patch("eagle.final_test._opponent_classpath", return_value=()))
        compile_agent = stack.enter_context(patch("eagle.final_test.compile_generated_agent", side_effect=self.compile))
        integrate = stack.enter_context(patch("eagle.final_test.integrate_microrts_agent", return_value=Mock(ok=True, to_json_dict=lambda: {"status": "success"})))
        matches = stack.enter_context(patch("eagle.final_test.run_microrts_match", side_effect=self.match))
        return compile_agent, integrate, matches

    def invoke(self, *extra):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return fixed_evaluation.main(["--run-dir", str(self.run), "--generations", "0", "5", *extra])

    def test_selects_generation_local_scalar_with_stable_ties_and_no_summary_override(self):
        self.write_json(self.run / "summary.json", {"best_candidate": {"candidate_id": "initial"}})
        selected = fixed_evaluation._select_representative(self.run, 5)
        self.assertEqual(selected["candidate_id"], "later")
        self.assertEqual(selected["_selection"]["search_game_performance"], 2)
        self.snapshot(5, [("later", 2), ("initial", 2)])
        self.assertEqual(fixed_evaluation._select_representative(self.run, 5)["candidate_id"], "initial")

    def test_selection_excludes_failed_nonfinite_sentinel_and_missing_classes(self):
        self.snapshot(5, [("initial", 1), ("later", float("nan"))])
        self.assertEqual(fixed_evaluation._select_representative(self.run, 5)["candidate_id"], "initial")
        for score in (float("inf"), -1000):
            self.snapshot(5, [("later", score)])
            with self.assertRaisesRegex(ValueError, "no runnable"):
                fixed_evaluation._select_representative(self.run, 5)
        self.snapshot(5, [("initial", 1)])
        class_path = self.run / "classes/initial/ai/generated/CandidateAgent.class"
        class_path.unlink()
        with self.assertRaisesRegex(ValueError, "no runnable"):
            fixed_evaluation._select_representative(self.run, 5)
        class_path.write_bytes(b"original")
        path = self.run / "generations/generation_0005.json"
        snapshot = json.loads(path.read_text())
        snapshot["population"][0]["status"] = "failed"
        self.write_json(path, snapshot)
        with self.assertRaisesRegex(ValueError, "no runnable"):
            fixed_evaluation._select_representative(self.run, 5)

    def test_fixed_roster_selection_reads_canonical_game_performance(self):
        self.write_json(self.run / "generations/generation_0005.json", {
            "schema_version": GENERATION_SCHEMA_VERSION, "generation": 5,
            "population": [{"candidate_id": "initial", "status": "evaluated", "fitness_objectives": {"lightrush": 10}}],
        })
        self.write_json(self.run / "candidates/initial/evaluation/game_performance.json", {"game_performance": 3.5})
        candidate = fixed_evaluation._select_representative(self.run, 5)
        self.assertEqual(candidate["_selection"]["search_game_performance"], 3.5)

    def test_end_to_end_outputs_pair_seeds_and_preserve_saved_artifacts(self):
        compile_agent, integrate, matches = self.runtime()
        original = {p: p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        self.assertEqual(self.invoke("--seed", "42"), 0)
        summary = json.loads((self.output / "fixed_evaluation_summary.json").read_text())
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["protocol"]["random_seed"], 42)
        self.assertEqual(summary["protocol"], json.loads((self.output / "protocol.json").read_text()))
        self.assertEqual([r["candidate_id"] for r in summary["rows"]], ["initial", "later"])
        self.assertTrue(all(r["wins"] == 12 and r["mean_match_score"] == 4 for r in summary["rows"]))
        calls = [call.kwargs for call in matches.call_args_list]
        self.assertEqual([c["match_seed"] for c in calls[:12]], [c["match_seed"] for c in calls[12:]])
        self.assertEqual(len(set(c["match_seed"] for c in calls[:12])), 12)
        self.assertEqual([c["candidate_id"] for c in calls[:12]], ["initial"] * 12)
        self.assertEqual([c["generation"] for c in calls[12:]], [5] * 12)
        self.assertEqual(integrate.call_args_list[0].kwargs["seed"], integrate.call_args_list[1].kwargs["seed"])
        self.assertEqual(compile_agent.call_count, 2)
        for path, contents in original.items():
            self.assertEqual(path.read_bytes(), contents, path)
        with (self.output / "fixed_evaluation_results.csv").open() as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 2)
        self.assertIn("| 5 | later |", (self.output / "fixed_evaluation_results.md").read_text())
        self.assertTrue((self.output / "generation_0000/final_test_results.csv").is_file())
        self.assertEqual(self.invoke(), 2)
        self.assertEqual(compile_agent.call_count, 2)

    def test_missing_or_uncommitted_generation_fails_before_evaluation(self):
        compile_agent, _, _ = self.runtime()
        (self.run / "generations/generation_0005.json").unlink()
        self.assertEqual(self.invoke(), 2)
        compile_agent.assert_not_called()
        self.assertFalse(self.output.exists())
        self.snapshot(5, [("later", 2)])
        manifest_path = self.run / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["completed_generations"] = [0]
        self.write_json(manifest_path, manifest)
        self.assertEqual(self.invoke(), 2)
        compile_agent.assert_not_called()

    def test_defaults_select_five_snapshots_and_use_run_config_seed(self):
        self.runtime()
        generations = [0, 5, 10, 15, 20]
        for generation in generations[2:]:
            self.snapshot(generation, [("initial", 1)])
        manifest_path = self.run / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        self.write_json(manifest_path, {**manifest, "latest_generation": 20, "completed_generations": generations})
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(fixed_evaluation.main(["--run-dir", str(self.run)]), 0)
        summary = json.loads((self.output / "fixed_evaluation_summary.json").read_text())
        self.assertEqual([row["generation"] for row in summary["rows"]], generations)
        self.assertEqual(summary["protocol"]["random_seed"], self.config.random_seed)
        self.assertEqual(summary["rows"][-1]["birth_generation"], 0)

    def test_invalid_request_and_manifest_fail_without_creating_output(self):
        compile_agent, _, _ = self.runtime()
        for generations in (("-1",), ("0", "0")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(fixed_evaluation.main([
                    "--run-dir", str(self.run), "--generations", *generations,
                ]), 2)
        path = self.run / "manifest.json"
        manifest = json.loads(path.read_text())
        for update in ({"status": "interrupted"}, {"schema_version": "unknown"}):
            self.write_json(path, {**manifest, **update})
            self.assertEqual(self.invoke(), 2)
        compile_agent.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failed_matches_are_explicit_without_partial_aggregate(self):
        _, _, matches = self.runtime()
        matches.side_effect = lambda **kwargs: replace(self.match(**kwargs), ok=False, failure_category="timeout") if kwargs["match_index"] == 0 else self.match(**kwargs)
        self.assertEqual(self.invoke(), 2)
        summary = json.loads((self.output / "fixed_evaluation_summary.json").read_text())
        self.assertEqual(summary["status"], "failed")
        for row in summary["rows"]:
            self.assertEqual(row["errors"], 1)
            self.assertEqual(row["completed_matches"], 11)
            self.assertIsNone(row["win_rate"])
            self.assertIsNone(row["mean_match_score"])

    def test_partial_results_survive_compile_failure_and_interrupt(self):
        compile_agent, _, _ = self.runtime()
        compile_agent.side_effect = [CompileResult(ok=True, command=[]), CompileResult(ok=False, command=[], stderr="bad source")]
        self.assertEqual(self.invoke(), 2)
        summary = json.loads((self.output / "fixed_evaluation_summary.json").read_text())
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(len(summary["rows"]), 1)
        self.assertEqual(summary["active_generation"], 5)
        self.assertIn("bad source", summary["error"])
        compilation = json.loads((self.output / "generation_0005/compilation.json").read_text())
        self.assertEqual(compilation["stderr"], "bad source")
        compile_agent.side_effect = KeyboardInterrupt
        interrupted = self.root / "interrupted"
        self.assertEqual(self.invoke("--output-dir", str(interrupted)), 130)
        self.assertEqual(json.loads((interrupted / "fixed_evaluation_summary.json").read_text())["status"], "interrupted")

    def test_protocol_drift_keeps_raw_evidence_without_publishing_a_comparable_score(self):
        _, _, matches = self.runtime()
        def mutate_map(**kwargs):
            (self.config.microrts_dir / self.config.evaluation_maps[0]).write_text("changed", encoding="utf-8")
            return self.match(**kwargs)
        matches.side_effect = mutate_map
        self.assertEqual(self.invoke(), 2)
        summary = json.loads((self.output / "fixed_evaluation_summary.json").read_text())
        self.assertEqual(len(summary["rows"]), 0)
        self.assertIn("assets changed", summary["error"])
        result = json.loads((self.output / "generation_0000/final_test_summary.json").read_text())
        self.assertFalse(result["fixed_evaluation_valid"])

    def test_fixed_matrix_seed_stream_ignores_candidate_and_workers_but_legacy_does_not(self):
        self.runtime()
        seed_sets = []
        for identity, generation, workers, root_seed, fixed in (
            ("initial", 0, 1, 7, True), ("later", 5, 4, 7, True),
            ("later", 5, 4, 8, True), ("initial", 0, 1, 7, False), ("later", 5, 1, 7, False),
        ):
            with patch("eagle.config.MATCH_WORKERS", workers):
                results = final_test._run_final_matrix(
                    config=replace(self.config, random_seed=root_seed), repository_root=self.root,
                    candidate={"candidate_id": identity, "generation": generation},
                    classes_dir=self.run / "classes" / identity, output_dir=self.root / identity,
                    source_path=self.run / "candidates" / identity / "phenotype/CandidateAgent.java",
                    seed_identity=fixed_evaluation.SCHEMA_VERSION if fixed else None,
                )
            seed_sets.append([item["match"]["match_seed"] for item in results])
        self.assertEqual(seed_sets[0], seed_sets[1])
        self.assertNotEqual(seed_sets[1], seed_sets[2])
        self.assertNotEqual(seed_sets[3], seed_sets[4])

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "Java required")
    def test_real_paired_benchmark_compiles_integrates_and_runs_saved_java(self):
        repository = Path(__file__).resolve().parents[1]
        config = replace(
            self.config, microrts_dir=repository / "third_party/microrts",
            evaluation_map_tick_limits=(2, 2, 2),
        )
        source = (repository / "eagle/java_seeds/worker_rush/CandidateAgent.java").read_text()
        for identity in ("initial", "later"):
            (self.run / "candidates" / identity / "phenotype/CandidateAgent.java").write_text(source, encoding="utf-8")
        # Only unused external-opponent setup is stubbed in this six-match smoke.
        with patch("eagle.final_test._load_config", return_value=config), \
             patch("eagle.final_test.preflight_evaluation_opponents"), \
             patch("eagle.final_test.FINAL_TEST_OPPONENTS", final_test.FINAL_TEST_OPPONENTS[:1]), \
             patch("eagle.final_test.FINAL_TEST_GAMES_PER_SIDE", 1), \
             patch("eagle.final_test._prepare_worker_rush_opponent", return_value=self.root), \
             patch("eagle.final_test._prepare_safe_allinbot_opponent", return_value=self.root):
            self.assertEqual(self.invoke(), 0)
        matrices = []
        for generation in (0, 5):
            directory = self.output / f"generation_{generation:04d}"
            result = json.loads((directory / "final_test_summary.json").read_text())
            self.assertEqual(result["integration"]["status"], "success")
            self.assertEqual(len(result["integration"]["ordered_checks"]), 7)
            self.assertTrue(result["fixed_evaluation_valid"])
            self.assertEqual(result["total_matches"], 6)
            self.assertTrue(all(item["ok"] for item in result["matches"]))
            matrices.append([(item["match"]["match_seed"], item["match"]["score"]) for item in result["matches"]])
            self.assertTrue((directory / "compilation.json").is_file())
        self.assertEqual(matrices[0], matrices[1])


if __name__ == "__main__":
    unittest.main()
