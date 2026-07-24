from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig, MATCHES_PER_CANDIDATE, TRAINING_OPPONENT
from eagle.evaluation import preflight_evaluation_opponents, evaluate_matches
from eagle.final_test.opponents import OpponentSetupError
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
        self.assertEqual(len(config.resolved_match_seeds), MATCHES_PER_CANDIDATE)
        self.assertEqual(len(set(config.resolved_match_seeds)), MATCHES_PER_CANDIDATE)

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
        self.assertEqual(len(results), 10)
        self.assertEqual([item["match_index"] for item in observed], list(range(10)))
        self.assertEqual([item["opponent"] for item in observed], [item.class_name for item in EVALUATION_ROSTER])
        self.assertEqual([item.opponent_id for item in results], [item.opponent_id for item in EVALUATION_ROSTER])
        self.assertTrue(str(observed[0]["extra_classpath_entries"][0]).endswith("tma.jar"))
        self.assertTrue(str(observed[1]["extra_classpath_entries"][0]).endswith("mayari.jar"))
        self.assertTrue(str(observed[2]["extra_classpath_entries"][0]).endswith("coac.jar"))
        self.assertTrue(all(item.get("extra_classpath_entries", ()) == () for item in observed[3:8]))
        self.assertTrue(all(str(item.get("extra_classpath_entries", ())[0]).endswith("_classes") for item in observed[8:]))
        self.assertEqual([item["seed"] for item in observed], list(config.resolved_match_seeds))
        self.assertEqual(len({item["source_hash"] for item in observed}), 1)
        self.assertEqual(len({item["class_hash"] for item in observed}), 1)
        self.assertEqual(len({str(item["classes_dir"]) for item in observed}), 1)

    def test_real_mode_preflight_requires_resolved_external_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = ExperimentConfig.from_mapping({"seed_prompts": ["seed"]})
            with self.assertRaisesRegex(OpponentSetupError, "setup_final_test_opponents"):
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

        self.assertEqual(len(results), 3)
        self.assertEqual(error, "boom")
        self.assertEqual(sum(item.ok for item in results), 2)

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


if __name__ == "__main__":
    unittest.main()
