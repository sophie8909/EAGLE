from __future__ import annotations

import gzip
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig, MATCHES_PER_CANDIDATE, FIXED_MATCHES_PER_OPPONENT, TRAINING_OPPONENT
from eagle.evaluation import preflight_evaluation_opponents, evaluate_matches
from eagle.opponents import EVALUATION_ROSTER
from evaluation.microrts_runner import MatchResult, run_microrts_match
from generation.java_agent_generator import GeneratedJavaAgent


class Phase4RuntimeEvaluationTests(unittest.TestCase):
    def test_config_resolves_exact_ten_roster_matches_and_distinct_seeds(self):
        config = ExperimentConfig.from_mapping(
            {
                "seed_prompts": ["seed"],
                "matches_per_candidate": 1,
                "opponent": "ai.RandomAI",
            }
        )

        self.assertEqual(config.matches_per_candidate, MATCHES_PER_CANDIDATE)
        self.assertEqual(config.opponent, TRAINING_OPPONENT)
        self.assertEqual(len(config.resolved_match_seeds), FIXED_MATCHES_PER_OPPONENT // 6)
        self.assertEqual(len(set(config.resolved_match_seeds)), 3)

    def test_one_source_and_class_set_serves_ten_seeded_matches(self):
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
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            observed: list[dict] = []

            def fake_match(**kwargs):
                observed.append(kwargs)
                index = kwargs["match_index"]
                return MatchResult(
                    ok=True,
                    score=100.0,
                    command=["java"],
                    match_index=index,
                    seed=kwargs["seed"],
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
        self.assertEqual(len(results), MATCHES_PER_CANDIDATE)
        self.assertEqual([item["match_index"] for item in observed], list(range(MATCHES_PER_CANDIDATE)))
        self.assertEqual([item["opponent"] for item in observed[::18]], [item.class_name for item in EVALUATION_ROSTER])
        self.assertEqual([item.opponent_id for item in results[::18]], [item.opponent_id for item in EVALUATION_ROSTER])
        self.assertTrue(all(item.get("extra_classpath_entries", ()) == () for item in observed))
        self.assertEqual([item["seed"] for item in observed[:18]], [0, 0, 1, 1, 2, 2] * 3)
        self.assertEqual(len({item["source_hash"] for item in observed}), 1)
        self.assertEqual(len({item["class_hash"] for item in observed}), 1)
        self.assertEqual(len({str(item["classes_dir"]) for item in observed}), 1)

    def test_real_mode_preflight_reports_missing_search_opponent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            with self.assertRaisesRegex(Exception, "allibot"):
                preflight_evaluation_opponents(config, mock=False, repository_root=Path(temp_dir))

    def test_partial_runtime_failure_retains_completed_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "CandidateAgent.java"
            source.write_text("source", encoding="utf-8")
            classes = root / "classes" / "candidate"
            classes.mkdir(parents=True)
            agent = GeneratedJavaAgent("CandidateAgent", "ai.generated", "source", source)
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
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

        self.assertEqual(len(results), MATCHES_PER_CANDIDATE)
        self.assertFalse(results[2].ok)
        self.assertEqual(results[2].opponent_id, EVALUATION_ROSTER[0].opponent_id)
        self.assertEqual(error, "boom")
        self.assertEqual(sum(item.ok for item in results), MATCHES_PER_CANDIDATE - 1)

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
                    opponent=TRAINING_OPPONENT,
                    tick_limit=100,
                    match_index=0,
                    match_artifacts_dir=root / "matches",
                    seed=7,
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
                    opponent=TRAINING_OPPONENT,
                    tick_limit=100,
                    match_index=0,
                    match_artifacts_dir=root / "matches",
                    seed=7,
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
                    seed=7,
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
                opponent=TRAINING_OPPONENT,
                tick_limit=100,
                match_index=0,
                match_artifacts_dir=root / "matches",
                seed=7,
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
                opponent=TRAINING_OPPONENT,
                tick_limit=100,
                match_index=0,
                match_artifacts_dir=root / "matches",
                seed=7,
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
