from __future__ import annotations

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
    _prepare_worker_rush_opponent,
    evaluate_matches,
    preflight_evaluation_opponents,
)
from eagle.opponents import EVALUATION_ROSTER
from evaluation.runtime_evaluation import MatchResult, run_microrts_match
from generation.java_agent_generator import GeneratedJavaAgent


class Phase4RuntimeEvaluationTests(unittest.TestCase):
    def test_config_resolves_exact_search_roster_and_match_count(self):
        config = ExperimentConfig.from_mapping({})

        self.assertEqual(config.expected_match_count, 126)
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

    def test_real_mode_preflight_reports_missing_search_opponent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ExperimentConfig.from_mapping({})
            with self.assertRaisesRegex(Exception, "allibot"):
                preflight_evaluation_opponents(config, mock=False, repository_root=Path(temp_dir))

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
