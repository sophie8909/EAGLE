"""Configuration and resume fences for the tournament self-play pool."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from eagle.config import ExperimentConfig
from eagle.evolution.resume import load_resume_config, resume_search
from eagle.opponent_cases import LEXICASE_CASES, SELF_PLAY_CASES


class OpponentPoolConfigTests(unittest.TestCase):
    @staticmethod
    def self_play_config(**evaluation_overrides: object) -> ExperimentConfig:
        evaluation = {
            "mode": "self_play",
            "self_play_opponent_library_capacity": 10,
            **evaluation_overrides,
        }
        return ExperimentConfig.from_mapping({
            "reflection_operator_mode": "static",
            "evaluation": evaluation,
        })

    def test_policy_defaults_and_round_trips(self) -> None:
        default = ExperimentConfig.from_mapping({})
        self.assertEqual(default.self_play_pool_policy, "tournament-v1")
        self.assertEqual(
            default.to_mapping()["evaluation"]["self_play_pool_policy"],
            "tournament-v1",
        )

        config = self.self_play_config()
        config.validate()
        restored = ExperimentConfig.from_mapping(config.to_mapping())
        self.assertEqual(restored.self_play_pool_policy, "tournament-v1")

    def test_self_play_requires_ten_library_slots(self) -> None:
        self.self_play_config(self_play_opponent_library_capacity=10).validate()
        with self.assertRaisesRegex(ValueError, "at least 10"):
            self.self_play_config(self_play_opponent_library_capacity=9).validate()

        legacy_fixed = ExperimentConfig.from_mapping({
            "evaluation": {"self_play_opponent_library_capacity": 1},
        })
        legacy_fixed.validate()

    def test_unknown_pool_policy_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be tournament-v1"):
            self.self_play_config(self_play_pool_policy="fifo-v0").validate()

    def test_self_play_cases_keep_four_protected_and_six_tournament_slots(self) -> None:
        self.assertEqual(
            self.self_play_config().lexicase_case_ids,
            ("allinbot", "mayari", "coac", "tma", *SELF_PLAY_CASES[:6]),
        )
        self.assertEqual(
            ExperimentConfig.from_mapping({}).lexicase_case_ids,
            LEXICASE_CASES,
        )

    def test_legacy_self_play_resume_is_rejected_before_artifacts_change(self) -> None:
        config = self.self_play_config()
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            raw_config = config.to_mapping()
            raw_config["evaluation"].pop("self_play_pool_policy")
            (run_dir / "config.yaml").write_text(
                yaml.safe_dump(raw_config, sort_keys=False), encoding="utf-8"
            )
            manifest = run_dir / "manifest.json"
            manifest.write_text('{"status":"completed"}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Start a new run"):
                resume_search(run_dir=run_dir, mock=True)

            self.assertEqual(manifest.read_text(encoding="utf-8"), '{"status":"completed"}')

    def test_fixed_roster_resume_accepts_legacy_missing_policy(self) -> None:
        config = ExperimentConfig.from_mapping({})
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            raw_config = config.to_mapping()
            raw_config["evaluation"].pop("self_play_pool_policy")
            (run_dir / "config.yaml").write_text(
                yaml.safe_dump(raw_config, sort_keys=False), encoding="utf-8"
            )

            restored = load_resume_config(run_dir)

        self.assertEqual(restored.evaluation_mode, "fixed_roster")
        self.assertEqual(restored.self_play_pool_policy, "tournament-v1")

    def test_resume_config_equality_includes_pool_policy(self) -> None:
        from eagle.evolution.resume import validate_resume_config

        config = self.self_play_config()
        changed = replace(config, self_play_pool_policy="other-policy")
        with self.assertRaisesRegex(ValueError, "self_play_pool_policy"):
            validate_resume_config(changed, config, mock=True)


if __name__ == "__main__":
    unittest.main()
