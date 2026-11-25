from __future__ import annotations

import json
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock, patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.generation import run_generation_step
from eagle.evolution.resume import load_resume_config, resume_search
from eagle.evolution.search import _new_run_directory, _result_version_folder, run_search
from eagle.evolution.weakest_matchup_repair import (
    SCHEMA_VERSION,
    build_matchup_evidence,
    propose_matchup_repair,
)
from eagle.generation.framework_slots import load_framework_bundle
from eagle.llm import LLMClient
from eagle.operators.selection import select_next_generation
from eagle.opponent_pool import initial_pool
from eagle.run_artifacts import load_resume_population
from eagle.self_play import self_play_context_id, self_play_context_rows


EXPERIMENTS = Path(__file__).resolve().parents[1] / "configs" / "experiments"
BASELINE_CONFIG = EXPERIMENTS / "1122_1gpt_9qwen_gen0_local_evolution_50x10_seed8_12.yaml"
WMR_CONFIG = EXPERIMENTS / "1122_wmr_1gpt_9qwen_50x10_seed8_12.yaml"


class WeakestMatchupEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.opponent = Candidate(id="past-survivor", generation=3)
        self.snapshot = [member for member in initial_pool() if member.opponent_id != "passive"] + [self.opponent]
        self.context = self_play_context_rows(self.snapshot)
        self.target = next(
            row["slot_id"] for row in self.context
            if row["source_candidate_id"] == self.opponent.id
        )

    def survivor(self, index, outcomes):
        rows = []
        for row in self.context:
            slot = row["slot_id"]
            wins, draws, losses = outcomes.get(slot, (4, 0, 0))
            complete = wins + draws + losses
            rows.append({
                "opponent_id": slot,
                "opponent_name": slot,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "completed_match_count": complete,
                "expected_match_count": complete,
                "missing_match_count": 0,
                "match_count": complete,
                "status": "completed",
                "score": 100 if slot == self.target else 0,
            })
        return Candidate(
            id=f"survivor-{index}",
            status="evaluated",
            strategy_description=f"Strategy {index}",
            java_materialization_mode="framework_slots",
            framework_bundle_sha256="0" * 64,
            control_genome={"horizon": index + 1},
            fitness_objectives={"game_performance": 1},
            game_eval_result={
                "evaluation_context_id": self_play_context_id(self.snapshot),
                "evaluation_configuration": {"opponents": self.context},
                "fitness_case_ids": ["game_performance"],
                "opponent_results": rows,
            },
        )

    def test_selects_lowest_pooled_win_rate_and_resolves_evolved_opponent(self):
        population = [
            self.survivor(0, {self.target: (0, 4, 0), "allinbot": (2, 0, 2)}),
            self.survivor(1, {self.target: (2, 2, 0), "allinbot": (2, 0, 2)}),
        ]
        evidence = build_matchup_evidence(population, self.snapshot, seed=11)

        target = evidence["target_opponent"]
        self.assertEqual(target["slot_id"], self.target)
        self.assertEqual(target["source_candidate_id"], self.opponent.id)
        self.assertEqual(target["source_generation"], self.opponent.generation)
        rates = {row["slot_id"]: row for row in evidence["opponent_rates"]}
        self.assertEqual(len(rates), 10)
        self.assertEqual(rates[self.target]["wins"], 2)
        self.assertEqual(rates[self.target]["completed_match_count"], 8)
        self.assertEqual(rates[self.target]["win_rate"], 0.25)
        self.assertEqual(rates["allinbot"]["win_rate"], 0.5)
        self.assertEqual(
            {row["strategy_description"] for row in evidence["survivors"]},
            {candidate.strategy_description for candidate in population},
        )

    def test_ties_use_seeded_choice_over_sorted_lowest_opponent_slots(self):
        population = [
            self.survivor(index, {self.target: (1, 0, 3), "allinbot": (1, 0, 3)})
            for index in range(2)
        ]
        tied = sorted((self.target, "allinbot"))
        selected = set()
        for seed in (1, 5):
            with self.subTest(seed=seed):
                evidence = build_matchup_evidence(population, self.snapshot, seed=seed)
                chosen = evidence["target_opponent"]["slot_id"]
                self.assertEqual(chosen, random.Random(seed).choice(tied))
                selected.add(chosen)
        self.assertEqual(selected, set(tied))

    def test_rejects_evidence_missing_an_opponent(self):
        candidate = self.survivor(0, {})
        candidate.game_eval_result["opponent_results"].pop()
        with self.assertRaises(ValueError):
            build_matchup_evidence([candidate], self.snapshot, seed=1)

    def test_model_proposal_requires_complete_slots_and_preserves_attempt_evidence(self):
        config = replace(ExperimentConfig.from_file(WMR_CONFIG), mutation_max_attempts=2)
        bundle = load_framework_bundle(config.framework_bundle_path)
        genome = {slot.slot_id: slot.default for slot in bundle.slots}
        response = {
            "schema_version": SCHEMA_VERSION,
            "framework_bundle_sha256": config.framework_bundle_sha256,
            "matchup_reflection": "This opponent disrupts resource collection early.",
            "strategy_description": "Defend workers until the first attack is contained.",
            "control_genome": genome,
        }
        invalid = json.dumps({**response, "control_genome": {}})
        valid = json.dumps(response)
        backend = SimpleNamespace(model="local-qwen", generate=Mock(side_effect=[invalid, valid]))
        client = LLMClient("http://localhost:18080", "local-qwen")
        population = [self.survivor(0, {self.target: (0, 0, 4)})]

        with tempfile.TemporaryDirectory() as directory, patch.object(
            LLMClient, "prompt_backend", return_value=backend,
        ) as prompt_backend:
            run_dir = Path(directory)
            artifact_dir = run_dir / "repair"
            proposal = propose_matchup_repair(
                population=population, snapshot=self.snapshot, config=config, generation=5,
                run_dir=run_dir, artifact_dir=artifact_dir, client=client, mock=False,
            )
            self.assertIsNotNone(proposal)
            self.assertEqual(proposal.framework_bundle_sha256, config.framework_bundle_sha256)
            self.assertEqual(proposal.control_genome, genome)
            self.assertEqual(proposal.strategy_description, response["strategy_description"])
            self.assertEqual(backend.generate.call_count, 2)
            first = artifact_dir / "attempts" / "attempt_001"
            second = artifact_dir / "attempts" / "attempt_002"
            self.assertIn(self.opponent.id, (first / "request.txt").read_text(encoding="utf-8"))
            self.assertEqual((first / "response_raw.txt").read_text(encoding="utf-8"), invalid)
            self.assertEqual((second / "response_raw.txt").read_text(encoding="utf-8"), valid)
            self.assertEqual(
                [json.loads(line)["status"] for line in (run_dir / "timing.jsonl").read_text().splitlines()],
                ["failed", "success"],
            )
            self.assertEqual(
                prompt_backend.call_args.kwargs["response_schema"]["properties"]
                ["framework_bundle_sha256"]["enum"],
                [config.framework_bundle_sha256],
            )


class WeakestMatchupRepairWorkflowTests(unittest.TestCase):
    def test_windows_version_folder_keeps_generation_zero_artifacts_below_max_path(self):
        config = replace(ExperimentConfig.from_file(WMR_CONFIG), runs_dir=Path("runs"), random_seed=8)
        attempt = "20261123_144955_247685"
        checkout = PureWindowsPath("C:/Users/local/Documents/GitHub/EAGLE")
        coach_dir = PureWindowsPath("candidates/gen_0000_d1bf70074e31/initialization/framework_coach")
        evidence = coach_dir / "coach_response_attempt_001.json"

        with patch("eagle.evolution.search._WINDOWS", False), patch("eagle.evolution.search._WSL", False):
            original = _new_run_directory(config, attempt, None)
        with patch("eagle.evolution.search._WINDOWS", True):
            compact = _new_run_directory(config, attempt, None)
            next_seed = _new_run_directory(replace(config, random_seed=12), attempt, None)
            baseline = _new_run_directory(replace(config, framework_weakest_matchup_repair_interval=0), attempt, None)
            explicit = _new_run_directory(config, "given-id", "given-id")

        self.assertGreater(len(str(checkout / original / coach_dir)), 248)
        self.assertGreaterEqual(len(str(checkout / original / evidence)), 260)
        self.assertLess(len(str(checkout / compact / evidence)), 248)
        self.assertEqual(compact.parent.parent, next_seed.parent.parent)
        self.assertNotEqual(compact.parent.parent, baseline.parent.parent)
        self.assertEqual(explicit, config.runs_dir / "given-id")

    def test_wsl_shortens_version_folder_only_on_a_windows_drive(self):
        config = replace(ExperimentConfig.from_file(WMR_CONFIG), runs_dir=Path("runs"), random_seed=10)
        attempt = "20261125_191102_563480"
        with patch("eagle.evolution.search._WINDOWS", True):
            compact = _new_run_directory(config, attempt, None)

        with patch("eagle.evolution.search._WINDOWS", False), patch("eagle.evolution.search._WSL", True):
            with patch.object(type(config.runs_dir), "resolve", return_value=PurePosixPath(
                "/mnt/c/Users/mhlab/Documents/GitHub/EAGLE/runs"
            )):
                mounted = _new_run_directory(config, attempt, None)
            with patch.object(type(config.runs_dir), "resolve", return_value=PurePosixPath("/home/lab/EAGLE/runs")):
                native = _new_run_directory(config, attempt, None)

        self.assertEqual(mounted, compact)
        self.assertEqual(native, config.runs_dir / _result_version_folder(config) / "seed_10" / attempt)

    def test_config_only_opts_in_to_wmr_and_labels_the_treatment(self):
        baseline = ExperimentConfig.from_file(BASELINE_CONFIG)
        treatment = ExperimentConfig.from_file(WMR_CONFIG)

        self.assertEqual(baseline.framework_weakest_matchup_repair_interval, 0)
        self.assertEqual(treatment.framework_weakest_matchup_repair_interval, 5)
        self.assertEqual(treatment.experiment_name, "1122-wmr")
        self.assertEqual(
            replace(treatment, experiment_name=baseline.experiment_name,
                    framework_weakest_matchup_repair_interval=0),
            baseline,
        )
        self.assertIn("weakest_matchup_repair_every_5_generations", _result_version_folder(treatment))
        self.assertIn("no_reflection", _result_version_folder(baseline))
        self.assertEqual(
            ExperimentConfig.from_mapping(treatment.to_mapping())
            .framework_weakest_matchup_repair_interval,
            5,
        )

    def test_g5_replaces_lowest_score_seat_and_checkpoints_before_g6_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                ExperimentConfig.from_file(WMR_CONFIG), runs_dir=Path(directory),
                generations=6,
            )
            pre_repair = []

            def select(parents, offspring, **kwargs):
                survivors = select_next_generation(parents, offspring, **kwargs)
                self.assertEqual(len({candidate.id for candidate in [*parents, *offspring]}), 20)
                pre_repair.append([candidate.id for candidate in survivors])
                return survivors

            def interrupt_at_g6(**kwargs):
                if kwargs["generation"] == 6:
                    raise KeyboardInterrupt
                return run_generation_step(**kwargs)

            run_dir = config.runs_dir / "weakest-matchup-repair"
            with (
                redirect_stdout(StringIO()),
                patch.object(LLMClient, "prompt_backend") as backend,
                patch("eagle.evaluation.pipeline._append_match_timing_events"),
            ):
                with (
                    patch("eagle.evolution.generation.select_next_generation", side_effect=select),
                    patch("eagle.evolution.loop.run_generation_step", side_effect=interrupt_at_g6),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    run_search(config, run_id=run_dir.name, mock=True)

                generation, survivors = load_resume_population(run_dir)
                self.assertEqual(generation, 5)
                self.assertEqual(len(pre_repair), 5)
                repair = [candidate for candidate in survivors if candidate.operator == "weakest_matchup_repair"]
                self.assertEqual(len(repair), 1)
                self.assertEqual(repair[0].generation, 5)
                self.assertEqual(repair[0].game_eval_result["completed_match_count"], 180)
                self.assertTrue(repair[0].strategy_description)
                self.assertTrue(repair[0].control_genome)
                before = pre_repair[-1]
                self.assertEqual(repair[0].parent_ids, ())
                self.assertEqual(repair[0].source_candidate_ids, ())
                self.assertEqual(repair[0].slot_parent_ids, {})
                self.assertEqual(repair[0].metadata["weakest_matchup_repair"]["evidence_candidate_ids"], before)
                self.assertEqual(
                    [candidate.id for candidate in survivors],
                    [*before[:7], repair[0].id, *before[8:]],
                )
                self.assertEqual(load_resume_config(run_dir).framework_weakest_matchup_repair_interval, 5)
                resumed = resume_search(run_dir=run_dir, mock=True)
                backend.assert_not_called()

            self.assertEqual(resumed.completed_generation, 6)
            records = list((run_dir / "generations").glob("generation_*_weakest_matchup_repair/result.json"))
            self.assertEqual([record.parent.name for record in records], ["generation_0005_weakest_matchup_repair"])
            result = json.loads(records[0].read_text(encoding="utf-8"))
            self.assertEqual(result["generation"], 5)
            self.assertEqual(result["status"], "replaced")
            self.assertEqual(result["game_performance_seat_index"], 7)
            self.assertEqual(result["replaced_candidate_id"], before[7])

    def test_exhausted_invalid_model_proposals_leave_all_selected_survivors(self):
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                ExperimentConfig.from_file(WMR_CONFIG), runs_dir=Path(directory),
                generations=1, population_size=4, mutation_max_attempts=2,
                framework_gpt_initial_candidates=0, framework_qwen_initial_candidates=0,
                framework_weakest_matchup_repair_interval=1,
            )
            backend = SimpleNamespace(model="local-qwen", generate=Mock(return_value="{}"))
            selected = []

            def select(parents, offspring, **kwargs):
                survivors = select_next_generation(parents, offspring, **kwargs)
                selected.extend(candidate.id for candidate in survivors)
                return survivors

            def propose_with_bad_responses(**kwargs):
                return propose_matchup_repair(**{**kwargs, "mock": False})

            with (
                redirect_stdout(StringIO()),
                patch.object(LLMClient, "prompt_backend", return_value=backend),
                patch("eagle.evaluation.pipeline._append_match_timing_events"),
                patch("eagle.evolution.generation.select_next_generation", side_effect=select),
                patch("eagle.evolution.generation.propose_matchup_repair", side_effect=propose_with_bad_responses),
            ):
                result = run_search(config, run_id="failed-repair", mock=True)

            self.assertEqual(backend.generate.call_count, 2)
            self.assertEqual([candidate.id for candidate in result.final_population], selected)
            result_path = result.run_dir / "generations/generation_0001_weakest_matchup_repair/result.json"
            record = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "proposal_failed")
            self.assertIsNone(record["replaced_candidate_id"])
