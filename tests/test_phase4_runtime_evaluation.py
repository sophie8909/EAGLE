from __future__ import annotations

from collections import Counter
import gzip
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation import (
    _prepare_safe_allinbot_opponent,
    _prepare_worker_rush_opponent,
    _resolved_static_evaluation_opponents,
    evaluate_matches,
    preflight_evaluation_opponents,
)
from eagle.opponents import (
    ALLINBOT_UPSTREAM_CLASS_NAME,
    EVALUATION_ROSTER,
    SAFE_ALLINBOT_CLASS_NAME,
)
from evaluation.runtime_evaluation import MatchResult, run_microrts_match
from generation.java_agent_generator import GeneratedJavaAgent


class Phase4RuntimeEvaluationTests(unittest.TestCase):
    def test_config_resolves_exact_search_roster_and_match_count(self):
        config = ExperimentConfig.from_mapping({})

        self.assertEqual(config.expected_match_count, 180)
        self.assertEqual(config.rounds_per_map, 3)

    def test_one_source_and_class_set_serves_search_roster_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "CandidateAgent.java"
            source.write_text("package ai.generated; public class CandidateAgent {}", encoding="utf-8")
            classes = root / "classes" / "candidate"
            classes.mkdir(parents=True)
            (classes / "CandidateAgent.class").write_bytes(b"compiled")
            agent = GeneratedJavaAgent(
                class_name="CandidateAgent",
                package_name="ai.generated",
                source=source.read_text(encoding="utf-8"),
                source_path=source,
            )
            config = ExperimentConfig.from_mapping({})
            observed: list[dict] = []

            def fake_match(**kwargs):
                observed.append(kwargs)
                index = kwargs["match_index"]
                return MatchResult(
                    ok=True,
                    score=100.0,
                    command=["java"],
                    match_index=index,
                    source_hash=kwargs["source_hash"],
                    class_hash=kwargs["class_hash"],
                )

            with patch("eagle.evaluation.run_microrts_match", side_effect=fake_match):
                results, error = evaluate_matches(
                    candidate=Candidate(id="candidate"),
                    agent=agent,
                    config=config,
                    classes_dir=root / "classes",
                    match_artifacts_dir=root / "matches",
                    mock=True,
                    ordinal=0,
                )

        self.assertIsNone(error)
        self.assertEqual(len(results), config.expected_match_count)
        self.assertEqual([item["match_index"] for item in observed], list(range(config.expected_match_count)))
        self.assertEqual([item["opponent"] for item in observed[::18]], [item.class_name for item in EVALUATION_ROSTER])
        self.assertEqual([item.opponent_id for item in results[::18]], [item.opponent_id for item in EVALUATION_ROSTER])
        self.assertTrue(all(item.get("extra_classpath_entries", ()) == () for item in observed))
        self.assertEqual(
            [(item["round_index"], item["candidate_player"]) for item in observed[:18]],
            [(round_index, side) for _ in range(3) for round_index in range(3) for side in (0, 1)],
        )
        self.assertEqual(len({item["source_hash"] for item in observed}), 1)
        self.assertEqual(len({item["class_hash"] for item in observed}), 1)
        self.assertEqual(len({str(item["classes_dir"]) for item in observed}), 1)

    def test_canonical_match_artifacts_persist_all_ten_case_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "CandidateAgent.java"
            source.write_text("source", encoding="utf-8")
            classes = root / "classes" / "candidate"
            classes.mkdir(parents=True)
            (classes / "CandidateAgent.class").write_bytes(b"compiled")
            agent = GeneratedJavaAgent("CandidateAgent", "ai.generated", "source", source)
            config = ExperimentConfig.from_mapping({})
            results, error = evaluate_matches(
                candidate=Candidate(id="candidate"),
                agent=agent,
                config=config,
                classes_dir=root / "classes",
                match_artifacts_dir=root / "matches",
                mock=True,
                ordinal=0,
            )
            persisted = [
                json.loads(
                    (root / "matches" / f"match_{index:02d}" / "result.json").read_text()
                )
                for index in range(config.expected_match_count)
            ]
            metadata = [
                json.loads(
                    (root / "matches" / f"match_{index:02d}" / "match_metadata.json").read_text()
                )
                for index in range(config.expected_match_count)
            ]

        self.assertIsNone(error)
        self.assertEqual(len(results), 180)
        expected = {item.opponent_id: 18 for item in EVALUATION_ROSTER}
        self.assertEqual(Counter(item["opponent_id"] for item in persisted), expected)
        self.assertEqual(Counter(item["opponent_id"] for item in metadata), expected)
        self.assertTrue(all(item["opponent_id"] for item in persisted))

    def test_real_mode_preflight_reports_missing_search_opponent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ExperimentConfig.from_mapping({})
            with self.assertRaisesRegex(Exception, "allibot"):
                preflight_evaluation_opponents(config, mock=False, repository_root=Path(temp_dir))

    def test_allinbot_uses_reflection_wrapper_while_preflight_pins_upstream(self):
        config = ExperimentConfig.from_mapping({})
        preflight_evaluation_opponents(config, mock=False, repository_root=Path.cwd())
        with tempfile.TemporaryDirectory() as temp_dir:
            classes_dir = Path(temp_dir) / "classes"
            adapter_classes = _prepare_safe_allinbot_opponent(
                config,
                classes_dir=classes_dir,
            )
            manifest = json.loads(
                (adapter_classes.parent / "manifest.json").read_text(encoding="utf-8")
            )
            opponents = _resolved_static_evaluation_opponents(
                config,
                mock=False,
                classes_dir=classes_dir,
            )
            allinbot = next(item for item in opponents if item.opponent_id == "allinbot")
            adapter_class_exists = (
                adapter_classes / "ai" / "eagle" / "SafeAllInBot.class"
            ).is_file()

        self.assertEqual(allinbot.class_name, SAFE_ALLINBOT_CLASS_NAME)
        self.assertEqual(allinbot.classpath_entries[0], adapter_classes)
        self.assertEqual(manifest["delegate_class"], ALLINBOT_UPSTREAM_CLASS_NAME)
        self.assertTrue(adapter_class_exists)
        source = Path("eagle/opponent_adapters/SafeAllInBot.java").read_text(encoding="utf-8")
        self.assertNotIn("import ai.abstraction.submissions.allibot", source)
        self.assertIn("Class.forName(DELEGATE_CLASS)", source)
        self.assertIn("action.integrityCheck()", source)
        self.assertNotIn("catch (Throwable", source)
        self.assertNotIn("catch (LinkageError", source)
        self.assertNotIn("| LinkageError", source)

    @unittest.skipUnless(
        Path("runs/20260824_233743_100100/classes/gen_0001_9215463a6e5d/ai/generated/CandidateAgent.class").is_file(),
        "observed AllInBot regression candidate classes are unavailable",
    )
    def test_observed_allinbot_24x24_crash_is_contained_and_persisted(self):
        repository_root = Path.cwd()
        config = ExperimentConfig.from_mapping({})
        candidate_classes = (
            repository_root
            / "runs/20260824_233743_100100/classes/gen_0001_9215463a6e5d"
        )
        jar = repository_root / "third_party/gui_opponents/jars/allibot.jar"
        libraries = tuple(sorted((repository_root / "third_party/gui_opponents/src/allibot/lib").glob("*.jar")))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            adapter_classes = _prepare_safe_allinbot_opponent(
                config,
                classes_dir=root / "classes",
                repository_root=repository_root,
            )
            normal_original = run_microrts_match(
                microrts_dir=config.microrts_dir,
                classes_dir=candidate_classes,
                agent_class="ai.generated.CandidateAgent",
                opponent=ALLINBOT_UPSTREAM_CLASS_NAME,
                opponent_id="allinbot",
                tick_limit=100,
                match_index=64,
                match_artifacts_dir=root / "normal-original",
                map_path="maps/8x8/basesWorkers8x8.xml",
                candidate_player=0,
                extra_classpath_entries=(jar, *libraries),
                timeout_seconds=30,
            )
            normal_wrapped = run_microrts_match(
                microrts_dir=config.microrts_dir,
                classes_dir=candidate_classes,
                agent_class="ai.generated.CandidateAgent",
                opponent=SAFE_ALLINBOT_CLASS_NAME,
                opponent_id="allinbot",
                tick_limit=100,
                match_index=64,
                match_artifacts_dir=root / "normal-wrapped",
                map_path="maps/8x8/basesWorkers8x8.xml",
                candidate_player=0,
                extra_classpath_entries=(adapter_classes, jar, *libraries),
                timeout_seconds=30,
            )
            original = run_microrts_match(
                microrts_dir=config.microrts_dir,
                classes_dir=candidate_classes,
                agent_class="ai.generated.CandidateAgent",
                opponent=ALLINBOT_UPSTREAM_CLASS_NAME,
                opponent_id="allinbot",
                tick_limit=5000,
                match_index=66,
                match_artifacts_dir=root / "original",
                map_path="maps/24x24/basesWorkers24x24.xml",
                candidate_player=0,
                extra_classpath_entries=(jar, *libraries),
                timeout_seconds=30,
            )
            wrapped = run_microrts_match(
                microrts_dir=config.microrts_dir,
                classes_dir=candidate_classes,
                agent_class="ai.generated.CandidateAgent",
                opponent=SAFE_ALLINBOT_CLASS_NAME,
                opponent_id="allinbot",
                tick_limit=5000,
                match_index=66,
                match_artifacts_dir=root / "wrapped",
                map_path="maps/24x24/basesWorkers24x24.xml",
                candidate_player=0,
                extra_classpath_entries=(adapter_classes, jar, *libraries),
                timeout_seconds=30,
            )
            persisted_stderr = (root / "wrapped/match_66/stderr.txt").read_text(encoding="utf-8")
            persisted_result = json.loads(
                (root / "wrapped/match_66/result.json").read_text(encoding="utf-8")
            )

        self.assertFalse(original.ok)
        self.assertIn("Harvest.execute", original.stderr)
        self.assertTrue(normal_original.ok, normal_original.stderr)
        self.assertTrue(normal_wrapped.ok, normal_wrapped.stderr)
        self.assertFalse(normal_wrapped.opponent_fault_contained)
        normal_original_result = dict(normal_original.raw_result)
        normal_wrapped_result = dict(normal_wrapped.raw_result)
        normal_original_result.pop("ai2", None)
        normal_wrapped_result.pop("ai2", None)
        self.assertEqual(normal_wrapped_result, normal_original_result)
        self.assertTrue(wrapped.ok, wrapped.stderr)
        self.assertIn("EAGLE_SAFE_ALLINBOT_FALLBACK", wrapped.stderr)
        self.assertEqual(wrapped.stderr.count("EAGLE_SAFE_ALLINBOT_FALLBACK"), 1)
        self.assertTrue(wrapped.opponent_fault_contained)
        self.assertEqual(wrapped.fault_scope, "opponent")
        self.assertTrue(wrapped.opponent_fault_recovered)
        self.assertEqual(wrapped.opponent_fault_reason, "delegate_get_action")
        self.assertTrue(wrapped.scoring_neutralized)
        self.assertEqual(wrapped.winner, -1)
        self.assertEqual(wrapped.score, 0.0)
        self.assertIsNotNone(wrapped.performance_breakdown)
        self.assertEqual(wrapped.performance_breakdown.match_score, 0.0)
        self.assertIn("EAGLE_SAFE_ALLINBOT_FALLBACK", persisted_stderr)
        self.assertTrue(persisted_result["opponent_fault_contained"])
        self.assertEqual(persisted_result["fault_scope"], "opponent")
        self.assertTrue(persisted_result["opponent_fault_recovered"])
        self.assertTrue(persisted_result["scoring_neutralized"])
        self.assertEqual(persisted_result["winner"], -1)
        self.assertEqual(persisted_result["result"], "draw")
        self.assertEqual(persisted_result["opponent_fault_reason"], "delegate_get_action")
        self.assertEqual(persisted_result["opponent"], SAFE_ALLINBOT_CLASS_NAME)

    def test_worker_rush_uses_vendored_upstream_implementation(self):
        config = ExperimentConfig.from_mapping({})
        with tempfile.TemporaryDirectory() as temp_dir:
            classes_dir = Path(temp_dir) / "classes"
            stale_root = classes_dir / "_opponent_adapters" / "worker_rush"
            stale_class = stale_root / "classes" / "ai" / "abstraction" / "WorkerRush.class"
            stale_class.parent.mkdir(parents=True)
            stale_class.write_bytes(b"old-light-rush-adapter")
            (stale_root / "manifest.json").write_text(
                json.dumps({"source_sha256": "stale"}),
                encoding="utf-8",
            )
            output = _prepare_worker_rush_opponent(
                config,
                classes_dir=classes_dir,
            )
            class_file = output / "ai" / "abstraction" / "WorkerRush.class"
            manifest = json.loads(
                (output.parent / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(class_file.is_file())
            self.assertNotEqual(class_file.read_bytes(), b"old-light-rush-adapter")
            class_mtime = class_file.stat().st_mtime_ns
            self.assertEqual(
                _prepare_worker_rush_opponent(
                    config,
                    classes_dir=classes_dir,
                ),
                output,
            )
            self.assertEqual(class_file.stat().st_mtime_ns, class_mtime)

        source = Path("third_party/microrts/src/ai/abstraction/WorkerRush.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("extends AbstractionLayerAI", source)
        self.assertIn("workersBehavior", source)
        self.assertNotIn("extends LightRush", source)
        self.assertEqual(manifest["implementation"], "vendored drchangliu/MicroRTS WorkerRush")
        self.assertEqual(len(manifest["source_sha256"]), 64)

    def test_partial_runtime_failure_retains_completed_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "CandidateAgent.java"
            source.write_text("source", encoding="utf-8")
            classes = root / "classes" / "candidate"
            classes.mkdir(parents=True)
            agent = GeneratedJavaAgent("CandidateAgent", "ai.generated", "source", source)
            config = ExperimentConfig.from_mapping({})
            calls = 0

            def fake_match(**kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    return MatchResult(
                        ok=False,
                        score=0.0,
                        command=["java"],
                        failure_category="runtime_exception",
                        failure_reason="boom",
                        status="failed",
                    )
                return MatchResult(ok=True, score=100.0, command=["java"])

            with patch("eagle.evaluation.run_microrts_match", side_effect=fake_match):
                results, error = evaluate_matches(
                    candidate=Candidate(id="candidate"),
                    agent=agent,
                    config=config,
                    classes_dir=root / "classes",
                    match_artifacts_dir=root / "matches",
                    mock=True,
                    ordinal=0,
                )

        self.assertEqual(len(results), config.expected_match_count)
        self.assertFalse(results[2].ok)
        self.assertEqual(results[2].opponent_id, EVALUATION_ROSTER[0].opponent_id)
        self.assertEqual(error, "boom")
        self.assertEqual(sum(item.ok for item in results), config.expected_match_count - 1)

    def test_runtime_timeout_is_classified_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch(
                "evaluation.runtime_evaluation.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["java"], 0.01, output="out", stderr="err"),
            ):
                result = run_microrts_match(
                    microrts_dir=root,
                    classes_dir=root / "classes",
                    agent_class="ai.generated.CandidateAgent",
                    opponent="ai.abstraction.LightRush",
                    tick_limit=100,
                    match_index=0,
                    match_artifacts_dir=root / "matches",
                    timeout_seconds=0.01,
                )
            payload = json.loads((root / "matches" / "match_00" / "result.json").read_text(encoding="utf-8"))
            timing = json.loads((root / "matches" / "match_00" / "timing.json").read_text(encoding="utf-8"))

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_category, "timeout")
        self.assertEqual(payload["failure_category"], "timeout")
        self.assertEqual(timing["status"], "failed")
        self.assertEqual(timing["timeout_seconds"], 0.01)

    def test_invalid_result_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def fake_run(command, **kwargs):
                Path(command[-1]).write_text('{"winner": 0}', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("evaluation.runtime_evaluation.subprocess.run", side_effect=fake_run):
                result = run_microrts_match(
                    microrts_dir=root,
                    classes_dir=root / "classes",
                    agent_class="ai.generated.CandidateAgent",
                    opponent="ai.abstraction.LightRush",
                    tick_limit=100,
                    match_index=0,
                    match_artifacts_dir=root / "matches",
                )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_category, "invalid_match_result")
        self.assertIn("missing required fields", result.failure_reason or "")

    def test_stdout_result_fallback_accepts_allibot_style_completed_game(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def fake_run(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="FINAL_TICK: 215\nWINNER: 1\nPlayer 1 wins!\n",
                    stderr="",
                )

            with patch("evaluation.runtime_evaluation.subprocess.run", side_effect=fake_run):
                result = run_microrts_match(
                    microrts_dir=root,
                    classes_dir=root / "classes",
                    agent_class="ai.generated.CandidateAgent",
                    opponent="ai.abstraction.submissions.allibot.alli",
                    tick_limit=5000,
                    match_index=6,
                    match_artifacts_dir=root / "matches",
                )

            match_dir = root / "matches" / "match_06"
            raw = json.loads((match_dir / "raw_result.json").read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.raw_result["result_source"], "stdout_fallback")
        self.assertEqual(raw["winner"], 1)
        self.assertEqual(result.failure_category, None)

    def test_compact_artifacts_preserve_gzip_telemetry_without_raw_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_microrts_match(
                microrts_dir=root,
                classes_dir=root / "classes",
                agent_class="ai.generated.CandidateAgent",
                opponent="ai.abstraction.LightRush",
                tick_limit=100,
                match_index=0,
                match_artifacts_dir=root / "matches",
                mock=True,
                artifact_mode="compact",
            )
            match_dir = root / "matches" / "match_00"
            persisted = json.loads((match_dir / "result.json").read_text(encoding="utf-8"))
            with gzip.open(match_dir / "telemetry.json.gz", "rt", encoding="utf-8") as handle:
                telemetry = json.load(handle)
            stdout_text = (match_dir / "stdout.txt").read_text(encoding="utf-8")
            replay_exists = (match_dir / "replay.xml").exists()
            rounds_exist = (match_dir / "round_states").exists()

        self.assertTrue(result.ok)
        self.assertIsNone(result.replay_path)
        self.assertIsNone(result.round_state_path)
        self.assertFalse(replay_exists)
        self.assertFalse(rounds_exist)
        self.assertFalse(any(argument.startswith("-Deagle.match.seed=") for argument in result.command))
        self.assertNotIn("seed", persisted)
        self.assertNotIn("match_seed", result.raw_result)
        self.assertEqual([item["tick"] for item in telemetry["ticks"]], [0, 100])
        self.assertIsNone(persisted["telemetry"])
        self.assertEqual(persisted["unit_material_trace"], [])
        self.assertNotIn("command", persisted)
        self.assertNotIn("stdout", persisted)
        self.assertNotIn("stderr", persisted)
        self.assertEqual(stdout_text, result.stdout)

    def test_full_artifact_mode_keeps_raw_replay_and_round_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_microrts_match(
                microrts_dir=root,
                classes_dir=root / "classes",
                agent_class="ai.generated.CandidateAgent",
                opponent="ai.abstraction.LightRush",
                tick_limit=100,
                match_index=0,
                match_artifacts_dir=root / "matches",
                mock=True,
                artifact_mode="full",
            )
            match_dir = root / "matches" / "match_00"
            replay_exists = (match_dir / "replay.xml").is_file()
            rounds_exist = (match_dir / "round_states").is_dir()
            telemetry_exists = (match_dir / "telemetry.json").is_file()

        self.assertTrue(result.ok)
        self.assertTrue(replay_exists)
        self.assertTrue(rounds_exist)
        self.assertTrue(telemetry_exists)


if __name__ == "__main__":
    unittest.main()
