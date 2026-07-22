import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.analysis.final_tests import FinalTestReadError, load_final_test_summaries
from eagle.analysis.records import discover_runs, load_candidate
from eagle.final_test import FINAL_TEST_SCHEMA_VERSION
from eagle.final_test.aggregation import aggregate_final_test_results
from eagle.final_test.config import FinalTestConfig
from eagle.final_test.opponents import (
    OpponentSetupError,
    ResolvedOpponent,
    load_opponent_manifest,
    load_resolved_opponents,
    verify_resolved_opponent,
)
from eagle.final_test.runner import execute_final_test
from eagle.final_test.schedule import build_schedule, exact_match_count
from eagle.final_test.selection import select_final_test_candidates
from evaluation.compiler import CompileResult
from evaluation.microrts_runner import IntegrationResult, MatchResult, run_microrts_match


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "final_test_champions.yaml"
MANIFEST_PATH = REPOSITORY_ROOT / "third_party" / "final_test_opponents" / "manifest.toml"


class FinalTestOpponentTests(unittest.TestCase):
    def test_manifest_has_exact_pinned_champions_and_expected_classes(self):
        specs = load_opponent_manifest(MANIFEST_PATH)
        self.assertEqual([item.opponent_id for item in specs], ["tma", "mayari", "coac"])
        self.assertEqual(
            [item.expected_class for item in specs],
            ["ai.tma.TMA", "mayariBot.mayari", "ai.coac.CoacAI"],
        )
        self.assertTrue(all(len(item.pinned_commit) == 40 for item in specs))

    def test_manifest_rejects_non_full_pinned_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.toml"
            raw = MANIFEST_PATH.read_text(encoding="utf-8")
            path.write_text(raw.replace("7eee64e20deceaa19a65d06b7935a7c1ec7cffa6", "main"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "full 40-character"):
                load_opponent_manifest(path)

    def test_resolved_manifest_requires_class_load_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolved.json"
            opponent = self._resolved("tma").to_json_dict()
            opponent["class_load_verified"] = False
            path.write_text(json.dumps({
                "schema_version": "eagle-final-test-opponents-resolved-v1",
                "opponents": [opponent],
            }), encoding="utf-8")
            with self.assertRaisesRegex(OpponentSetupError, "class-load proof"):
                load_resolved_opponents(path, expected_ids=("tma",))

    def test_resolved_opponent_rechecks_jar_hash_and_class_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jar = root / "third_party" / "final_test_opponents" / "jars" / "tma.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"pinned champion jar")
            opponent = self._resolved("tma", jar_hash=hashlib.sha256(jar.read_bytes()).hexdigest())
            with patch("eagle.final_test.opponents._probe_classes", return_value=(opponent.class_name,)) as probe:
                verify_resolved_opponent(
                    opponent,
                    repository_root=root,
                    microrts_dir=REPOSITORY_ROOT / "third_party" / "microrts",
                    probe_classes=root / "probe",
                )
            probe.assert_called_once()

    @staticmethod
    def _resolved(opponent_id: str, *, jar_hash: str = "a" * 64) -> ResolvedOpponent:
        classes = {"tma": "ai.tma.TMA", "mayari": "mayariBot.mayari", "coac": "ai.coac.CoacAI"}
        return ResolvedOpponent(
            opponent_id=opponent_id,
            display_name=opponent_id.upper(),
            competition_year=2024,
            upstream_repository=f"https://example.invalid/{opponent_id}",
            pinned_commit="1" * 40,
            class_name=classes[opponent_id],
            build_method="javac",
            jar_path=f"third_party/final_test_opponents/jars/{opponent_id}.jar",
            required_classpath_entries=(),
            jar_sha256=jar_hash,
            source_sha256="b" * 64,
            detected_ai_classes=(classes[opponent_id],),
            class_load_verified=True,
            license_status="No license file detected",
            detected_license_files=(),
        )


class FinalTestSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.run = Path(self.temporary.name) / "completed_run"
        self.run.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_candidates(self, rows, front):
        for candidate_id, game, quality in rows:
            source = "package ai.generated; public class CandidateAgent {}\n"
            candidate = {
                "candidate_id": candidate_id,
                "generation": 2,
                "status": "evaluated",
                "fitness_objectives": {"game_performance": game, "code_quality": quality},
                "generated_java": source,
            }
            candidate_dir = self.run / "candidates" / candidate_id
            (candidate_dir / "generation").mkdir(parents=True)
            (candidate_dir / "individual.json").write_text(json.dumps(candidate), encoding="utf-8")
            (candidate_dir / "generation" / "normalized_candidate.java").write_text(source, encoding="utf-8")
        population = [json.loads((self.run / "candidates" / item[0] / "individual.json").read_text(encoding="utf-8")) for item in rows]
        (self.run / "summary.json").write_text(json.dumps({
            "final_population": population,
            "pareto_fronts": [front],
        }), encoding="utf-8")

    def test_explicit_candidate_loads_exact_canonical_source(self):
        self._write_candidates([("exact", 1, 2)], ["exact"])
        decision = select_final_test_candidates(self.run, candidate_id="exact", git_commit="abc")
        self.assertEqual([item.candidate_id for item in decision.candidates], ["exact"])
        self.assertTrue(decision.to_json_dict(self.run)["no_final_test_result_used"])

    def test_best_game_performance_has_deterministic_tie_breaking(self):
        self._write_candidates([("z", 10, 3), ("b", 10, 4), ("a", 10, 4)], ["z", "b", "a"])
        decision = select_final_test_candidates(self.run, selector="best-game-performance", git_commit="abc")
        self.assertEqual(decision.candidates[0].candidate_id, "a")
        self.assertEqual(decision.tie_breaking["ordered_candidate_ids"], ["a", "b", "z"])

    def test_balanced_uses_unweighted_normalized_ideal_distance(self):
        rows = [("game", 10, 0), ("balanced", 5, 5), ("quality", 0, 10)]
        self._write_candidates(rows, [item[0] for item in rows])
        decision = select_final_test_candidates(self.run, selector="balanced", git_commit="abc")
        self.assertEqual(decision.candidates[0].candidate_id, "balanced")
        self.assertEqual(decision.tie_breaking["weights"], {"game_performance": 1.0, "code_quality": 1.0})

    def test_pareto_selects_entire_front_in_stable_order(self):
        rows = [("c", 10, 0), ("a", 5, 5), ("b", 0, 10)]
        self._write_candidates(rows, ["c", "a", "b"])
        decision = select_final_test_candidates(self.run, selector="pareto", git_commit="abc")
        self.assertEqual([item.candidate_id for item in decision.candidates], ["a", "b", "c"])


class FinalTestScheduleAndRuntimeTests(unittest.TestCase):
    def test_schedule_covers_both_sides_and_exact_cartesian_count(self):
        config = FinalTestConfig.from_file(CONFIG_PATH, repository_root=REPOSITORY_ROOT)
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            source = run / "CandidateAgent.java"
            individual = run / "individual.json"
            source.write_text("class CandidateAgent {}", encoding="utf-8")
            individual.write_text("{}", encoding="utf-8")
            from eagle.final_test.selection import SelectedCandidate
            selected = SelectedCandidate("candidate", 1, 3.0, 4.0, source, individual)
            schedule = build_schedule((selected,), config)
        self.assertEqual(len(schedule), exact_match_count(1, config))
        self.assertEqual(len(schedule), 54)
        self.assertEqual({item.candidate_player for item in schedule}, {0, 1})

    def test_canonical_match_launcher_supports_champion_jar_and_player_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            classes = root / "classes"
            classes.mkdir()
            jar = root / "champion.jar"
            jar.write_bytes(b"jar")
            result = run_microrts_match(
                microrts_dir=REPOSITORY_ROOT / "third_party" / "microrts",
                classes_dir=classes,
                agent_class="ai.generated.CandidateAgent",
                opponent="ai.tma.TMA",
                tick_limit=20,
                match_index=0,
                match_artifacts_dir=root / "matches",
                mock=True,
                mock_score=2.0,
                candidate_player=1,
                extra_classpath_entries=(jar,),
            )
        ai1 = result.command[result.command.index("--ai1") + 1]
        ai2 = result.command[result.command.index("--ai2") + 1]
        classpath = result.command[result.command.index("-cp") + 1]
        self.assertEqual((ai1, ai2), ("ai.tma.TMA", "ai.generated.CandidateAgent"))
        self.assertIn(str(jar.resolve()), classpath)
        self.assertEqual(result.candidate_player, 1)
        self.assertIsNotNone(result.round_state_path)


class FinalTestAggregationTests(unittest.TestCase):
    def test_aggregation_scores_completed_matches_and_excludes_incomplete(self):
        records = [
            self._record("tma", "map8", 0, 0, "success", 10),
            self._record("tma", "map8", 1, -1, "success", 20),
            self._record("coac", "map16", 1, 0, "success", 30),
            self._record("coac", "map16", 0, None, "failed", None),
        ]
        summary = aggregate_final_test_results(records, expected_by_candidate={"candidate": 4})
        metrics = summary["candidates"]["candidate"]["aggregate"]
        self.assertEqual((metrics["wins"], metrics["draws"], metrics["losses"]), (1, 1, 1))
        self.assertEqual((metrics["completed_matches"], metrics["incomplete_matches"]), (3, 1))
        self.assertAlmostEqual(metrics["final_test_competition_score"], 0.5)
        self.assertFalse(summary["formal_test_complete"])
        self.assertEqual(summary["candidates"]["candidate"]["by_opponent"]["tma"]["draws"], 1)
        self.assertEqual(summary["candidates"]["candidate"]["by_map"]["map16"]["losses"], 1)

    @staticmethod
    def _record(opponent, map_id, side, winner, status, tick):
        return {
            "candidate_id": "candidate",
            "candidate_player": side,
            "opponent_id": opponent,
            "map_id": map_id,
            "winner": winner,
            "status": status,
            "final_tick": tick,
            "evolution_game_performance": 12.0,
            "evolution_code_quality": 6.0,
        }


class FinalTestExecutionTests(unittest.TestCase):
    def test_runner_compiles_once_preserves_hashes_and_uses_no_evolutionary_operators(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            self._write_completed_run(run)
            opponents = {
                item: FinalTestOpponentTests._resolved(item) for item in ("tma", "mayari", "coac")
            }
            calls = {"compile": 0, "match": 0}

            def compile_fake(source_path, *, output_dir, **kwargs):
                calls["compile"] += 1
                class_file = output_dir / "ai" / "generated" / "CandidateAgent.class"
                class_file.parent.mkdir(parents=True)
                class_file.write_bytes(b"same compiled class")
                return CompileResult(True, ["javac", str(source_path)])

            def integration_fake(**kwargs):
                return IntegrationResult("success", (), 1.0)

            def match_fake(**kwargs):
                calls["match"] += 1
                side = kwargs["candidate_player"]
                return MatchResult(
                    ok=True,
                    score=0.0,
                    command=["java"],
                    raw_result={"result": "win"},
                    winner=side,
                    final_cycle=10,
                    candidate_id=kwargs["candidate_id"],
                    candidate_player=side,
                    status="success",
                    duration_seconds=0.01,
                    source_hash=kwargs["source_hash"],
                    class_hash=kwargs["class_hash"],
                )

            with patch("eagle.final_test.runner.load_resolved_opponents", return_value=opponents):
                outcome = execute_final_test(
                    run_dir=run,
                    config_path=CONFIG_PATH,
                    repository_root=REPOSITORY_ROOT,
                    selector="best-game-performance",
                    final_test_id="unit",
                    compile_function=compile_fake,
                    integration_function=integration_fake,
                    match_function=match_fake,
                    verify_opponents=False,
                )
            self.assertTrue(outcome.success)
            self.assertEqual(calls, {"compile": 1, "match": 54})
            rows = [json.loads(line) for line in (outcome.final_test_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len({item["candidate_source_sha256"] for item in rows}), 1)
            self.assertEqual(len({item["candidate_class_sha256"] for item in rows}), 1)
            selection = json.loads((outcome.final_test_dir / "selection.json").read_text(encoding="utf-8"))
            resolved = json.loads((outcome.final_test_dir / "resolved_config.json").read_text(encoding="utf-8"))
            self.assertTrue(selection["no_final_test_result_used"])
            self.assertEqual((resolved["llm_calls"], resolved["evolutionary_operator_calls"]), (0, 0))

        tree = ast.parse((REPOSITORY_ROOT / "eagle" / "final_test" / "runner.py").read_text(encoding="utf-8"))
        imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(any(name.startswith(("eagle.mutation", "eagle.crossover", "eagle.search", "eagle.generation")) for name in imported))

    @staticmethod
    def _write_completed_run(run: Path):
        source = "package ai.generated; public class CandidateAgent {}\n"
        candidate = {
            "candidate_id": "chosen",
            "generation": 3,
            "status": "evaluated",
            "fitness_objectives": {"game_performance": 9.0, "code_quality": 8.0},
            "generated_java": source,
        }
        candidate_dir = run / "candidates" / "chosen"
        (candidate_dir / "generation").mkdir(parents=True)
        (candidate_dir / "individual.json").write_text(json.dumps(candidate), encoding="utf-8")
        (candidate_dir / "generation" / "normalized_candidate.java").write_text(source, encoding="utf-8")
        (run / "summary.json").write_text(json.dumps({
            "final_population": [candidate],
            "pareto_fronts": [["chosen"]],
        }), encoding="utf-8")


class FinalTestAnalysisReaderTests(unittest.TestCase):
    def test_versioned_summary_readback_and_gui_models(self):
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            run = runs / "20260722_120000_000001"
            FinalTestExecutionTests._write_completed_run(run)
            summary_dir = run / "final_tests" / "formal_1"
            summary_dir.mkdir(parents=True)
            payload = {
                "final_test_schema_version": FINAL_TEST_SCHEMA_VERSION,
                "final_test_id": "formal_1",
                "formal_final_test": True,
                "status": "complete",
                "selector": "best-game-performance",
                "tested_candidate_ids": ["chosen"],
                "expected_total_matches": 54,
                "completed_total_matches": 54,
                "incomplete_total_matches": 0,
                "candidates": {"chosen": {"aggregate": {"wins": 20, "draws": 10, "losses": 24, "final_test_competition_score": 0.46296}}},
                "artifact_paths": {"results": "results.jsonl"},
            }
            (summary_dir / "summary.json").write_text(json.dumps(payload), encoding="utf-8")
            summaries = load_final_test_summaries(run)
            self.assertEqual(summaries[0].for_candidate("chosen")["aggregate"]["wins"], 20)
            self.assertEqual(summaries[0].artifact_paths["results"], summary_dir / "results.jsonl")
            discovered = discover_runs(runs)[0]
            self.assertEqual((discovered.final_test_count, discovered.final_test_candidate_ids), (1, ("chosen",)))
            candidate = load_candidate(run, "chosen")
            self.assertEqual(candidate.final_tests[0].final_test_id, "formal_1")
            gui_source = (REPOSITORY_ROOT / "eagle_ui" / "views" / "candidate_view.py").read_text(encoding="utf-8")
            self.assertIn('ui.tab("Final Tests")', gui_source)

    def test_reader_rejects_unknown_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "final_tests" / "bad" / "summary.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(json.dumps({
                "final_test_schema_version": "unknown",
                "tested_candidate_ids": [],
                "candidates": {},
            }), encoding="utf-8")
            with self.assertRaises(FinalTestReadError):
                load_final_test_summaries(Path(directory))


if __name__ == "__main__":
    unittest.main()
