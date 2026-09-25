"""Contracts for config-gated immutable-snapshot self-play."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from eagle.aos import ReflectionOperatorMode
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
    expand_self_play_slots,
    write_self_play_snapshot,
)


class SelfPlayTests(unittest.TestCase):
    def test_default_is_fixed_roster_and_self_play_round_trips(self) -> None:
        self.assertEqual(ExperimentConfig.from_mapping({}).evaluation_mode, "fixed_roster")
        config = ExperimentConfig.from_mapping({
            "reflection_operator_mode": "static",
            "evaluation": {"mode": "self_play", "self_play_refresh_interval": 3},
        })
        config.validate()
        restored = ExperimentConfig.from_mapping(config.to_mapping())
        self.assertEqual(restored.evaluation_mode, "self_play")
        self.assertEqual(restored.self_play_refresh_interval, 3)
        with self.assertRaisesRegex(ValueError, "reflection_operator_mode=static"):
            replace(
                config,
                reflection_operator_mode=ReflectionOperatorMode.AOS_HEAD2HEAD,
            ).validate()

    def test_five_candidate_snapshot_cycles_into_ten_explicit_slots(self) -> None:
        candidates = [
            Candidate(
                id=f"candidate-{index}",
                generation=4,
                generated_java="complete Java",
                compile_status="success",
            )
            for index in range(5)
        ]
        slots = expand_self_play_slots(candidates)
        self.assertEqual([candidate.id for candidate in slots[:5]], [candidate.id for candidate in candidates])
        self.assertEqual([candidate.id for candidate in slots[5:]], [candidate.id for candidate in candidates])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_self_play_snapshot(
                root,
                generation=5,
                candidates=candidates,
                refresh_interval=5,
            )
            payload = json.loads(
                (root / "generations" / "generation_0005_self_play_snapshot.json").read_text()
            )
        self.assertEqual([slot["slot_id"] for slot in payload["slots"]], list(SELF_PLAY_CASES))
        self.assertEqual(len(payload["slots"]), 10)
        self.assertEqual(
            [slot["source_candidate_id"] for slot in payload["slots"][:5]],
            [candidate.id for candidate in candidates],
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
