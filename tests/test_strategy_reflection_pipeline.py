from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.mutation import ReflectionContext
from eagle.reflection_context import EvolutionContext
from eagle.strategy_reflection import (
    MockRoleBackend,
    StrategyReflectionMutation,
    build_global_evaluation_summary,
    select_reflection_matches,
)
from evaluation.match_logs import iter_match_log, write_match_log
from evaluation.microrts_runner import write_mock_round_state


class StrategyReflectionPipelineTests(unittest.TestCase):
    @staticmethod
    def _result(
        match_id: str,
        outcome: str,
        *,
        opponent: str = "lightrush",
        map_id: str = "map_1",
        candidate_player: int = 0,
    ) -> dict[str, object]:
        winner = (
            candidate_player
            if outcome == "win"
            else 1 - candidate_player
            if outcome == "loss"
            else -1
        )
        return {
            "match_id": match_id,
            "match_index": int(match_id.rsplit("-", 1)[-1]),
            "opponent_id": opponent,
            "opponent_name": opponent,
            "map_id": map_id,
            "candidate_player": candidate_player,
            "candidate_side": f"p{candidate_player}",
            "winner": winner,
            "result": "timeout_draw" if outcome == "draw" else f"p{winner}_win",
        }

    def test_selection_budget_and_no_duplicates(self) -> None:
        rows = [self._result(f"loss-{index}", "loss") for index in range(20)]
        selection = select_reflection_matches(
            rows,
            run_seed=7,
            generation_index=4,
            candidate_id="candidate",
            reflection_invocation=2,
        )
        self.assertEqual(selection["sample_count"], 10)
        self.assertEqual(selection["requested_sample_size"], 10)
        self.assertEqual(len(selection["selected_match_ids"]), len(set(selection["selected_match_ids"])))

    def test_selection_uses_all_available_matches_below_budget(self) -> None:
        rows = [self._result(f"match-{index}", "draw") for index in range(6)]
        selection = select_reflection_matches(
            rows,
            run_seed=7,
            generation_index=4,
            candidate_id="candidate",
            reflection_invocation=2,
        )
        self.assertEqual(selection["actual_sample_size"], 6)
        self.assertEqual(selection["sample_count"], 6)

    def test_selection_covers_losing_opponents_before_repeating_one(self) -> None:
        opponents = ("lightrush", "heavyrush", "workerrush", "allinbot", "mayari")
        rows = [
            self._result(f"{opponent}-0", "loss", opponent=opponent)
            for opponent in opponents
        ]
        rows.extend(self._result(f"heavy-extra-{index}", "loss", opponent="heavyrush") for index in range(4))
        selection = select_reflection_matches(rows, run_seed=7, generation_index=4, candidate_id="candidate", sample_budget=5)
        self.assertEqual(set(selection["sampled_opponents"]), set(opponents))
        self.assertEqual(selection["sample_count"], 5)

    def test_selection_prefers_unseen_maps_then_loss_draw_win(self) -> None:
        rows = [
            self._result("map-loss-0", "loss", map_id="map_1"),
            self._result("map-loss-1", "loss", map_id="map_2"),
            self._result("map-loss-2", "loss", map_id="map_3"),
            self._result("same-map-draw-3", "draw", map_id="map_1"),
            self._result("same-map-win-4", "win", map_id="map_1"),
        ]
        selection = select_reflection_matches(rows, run_seed=7, generation_index=4, candidate_id="candidate", sample_budget=3)
        self.assertEqual(set(selection["sampled_maps"]), {"map_1", "map_2", "map_3"})
        self.assertEqual(selection["losses_sampled"], 3)

    def test_selection_is_reproducible(self) -> None:
        rows = [self._result(f"loss-{index}", "loss", map_id=f"map_{index % 3 + 1}") for index in range(12)]
        first = select_reflection_matches(rows, run_seed=7, generation_index=4, candidate_id="candidate", reflection_invocation=2)
        second = select_reflection_matches(rows, run_seed=7, generation_index=4, candidate_id="candidate", reflection_invocation=2)
        self.assertEqual(first, second)

    def test_strategy_pipeline_commentates_only_selected_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rows = []
            for index, outcome in enumerate(("loss", "loss", "draw", "win", "win")):
                states = root / f"states-{index}"
                write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
                log_path = root / f"match-{index}.jsonl.gz"
                write_match_log(
                    log_path,
                    metadata={"match_id": f"match-{index}", "candidate_side": "p0", "opponent_name": "LightRush"},
                    round_state_dir=states,
                    raw_result={"final_tick": 0, "players": {"p0": {"resource_total": 10}, "p1": {"resource_total": 10}}},
                    tick_limit=0,
                )
                row = self._result(f"match-{index}", outcome)
                row["match_log_path"] = str(log_path)
                row["opponent_name"] = "LightRush"
                row["map_name"] = "map_1"
                row["candidate_side"] = "p0"
                rows.append(row)

            candidate = Candidate(id="candidate-selection", generation=4, strategy_prompt="Preserve the opening.")
            context = ReflectionContext(
                evolution=EvolutionContext(generation_index=4),
                game_evidence={"wins": 2, "draws": 1, "losses": 2, "completed_match_count": 5},
                per_match_results=tuple(rows),
            )
            backend = MockRoleBackend()
            result = StrategyReflectionMutation(backend, max_attempts=1, selection_seed=7).run(
                candidate, context, artifact_dir=root / "child"
            )

            self.assertEqual(result.status, "success")
            selection = json.loads((root / "child" / "reflection" / "match_selection.json").read_text(encoding="utf-8"))
            self.assertEqual(selection["selected_outcome_class"], "mixed")
            self.assertEqual(selection["actual_sample_size"], 5)
            commentator_prompts = [prompt for prompt in backend.prompts if "ROLE: match_commentator" in prompt]
            self.assertEqual(len(commentator_prompts), 5)
            self.assertEqual(len(selection["selected_match_ids"]), 5)
            self.assertEqual(len({item for item in selection["selected_match_ids"]}), 5)
            self.assertTrue(all(not Path(row["match_log_path"]).exists() for row in rows))
            coach_prompt = next(prompt for prompt in backend.prompts if "ROLE: coach" in prompt)
            self.assertIn('"global_evaluation_summary"', coach_prompt)
            self.assertIn('"total_matches": 5', coach_prompt)
            self.assertNotIn("raw_game_log:", coach_prompt)
            self.assertNotIn("ROLE: manager", "\n".join(backend.prompts))

    def test_ten_selected_logs_have_ten_independent_commentator_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rows = []
            for index in range(10):
                states = root / f"states-{index}"
                write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
                log_path = root / f"match-{index}.jsonl.gz"
                write_match_log(
                    log_path,
                    metadata={"match_id": f"match-{index}", "candidate_side": "p0", "opponent_name": "LightRush", "map_name": f"map_{index + 1}"},
                    round_state_dir=states,
                    raw_result={"final_tick": 0, "players": {"p0": {"resource_total": 10}, "p1": {"resource_total": 10}}},
                    tick_limit=0,
                )
                row = self._result(f"match-{index}", "loss", map_id=f"map_{index + 1}")
                row["match_log_path"] = str(log_path)
                rows.append(row)
            candidate = Candidate(id="candidate-ten", generation=4, strategy_prompt="Preserve the opening.")
            context = ReflectionContext(evolution=EvolutionContext(generation_index=4), per_match_results=tuple(rows))
            backend = MockRoleBackend()
            result = StrategyReflectionMutation(backend, max_attempts=1, sample_budget=10).run(candidate, context, artifact_dir=root / "child")

            self.assertEqual(result.status, "success")
            commentator_prompts = [prompt for prompt in backend.prompts if "ROLE: match_commentator" in prompt]
            self.assertEqual(len(commentator_prompts), 10)
            self.assertTrue(all(prompt.count("raw_game_log:") == 1 for prompt in commentator_prompts))
            coach_prompt = next(prompt for prompt in backend.prompts if "ROLE: coach" in prompt)
            self.assertIn('"total_matches": 10', coach_prompt)
            self.assertIn('"commentator_diagnoses"', coach_prompt)
            self.assertNotIn("raw_game_log:", coach_prompt)

    def test_global_summary_uses_all_matches_and_requires_full_canonical_matrix_for_beaten(self) -> None:
        rows = []
        for index in range(18):
            rows.append(self._result(f"lightrush-{index}", "win", opponent="lightrush", map_id=f"map_{index // 6 + 1}", candidate_player=index % 2))
        for index in range(17):
            rows.append(self._result(f"heavyrush-{index}", "win", opponent="heavyrush", map_id=f"map_{index // 6 + 1}", candidate_player=index % 2))
        rows.append(self._result("heavyrush-17", "loss", opponent="heavyrush", map_id="map_3", candidate_player=1))
        summary = build_global_evaluation_summary(
            {
                "evaluation_configuration": {"maps": ["map-a", "map-b", "map-c"], "rounds_per_map": 3, "swap_player_sides": True},
                "opponent_results": [
                    {"opponent_id": "lightrush", "opponent_name": "LightRush", "expected_match_count": 18},
                    {"opponent_id": "heavyrush", "opponent_name": "HeavyRush", "expected_match_count": 18},
                ],
            },
            rows,
        )
        by_id = {item["opponent_id"]: item for item in summary["opponents"]}
        self.assertEqual(summary["total_matches"], 36)
        self.assertEqual(summary["total_wins"], 35)
        self.assertEqual(summary["total_losses"], 1)
        self.assertTrue(by_id["lightrush"]["fully_beaten_opponent"])
        self.assertFalse(by_id["heavyrush"]["fully_beaten_opponent"])
        self.assertEqual(summary["fully_beaten_opponents_count"], 1)

    def test_commentator_direct_coach_delete_trace_and_preserve_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            for tick in range(4):
                write_mock_round_state(states, tick=tick, p0_resource=10 + tick, p1_resource=10)
            log_path = root / "match_log.jsonl.gz"
            write_match_log(
                log_path,
                metadata={
                    "match_id": "match-1",
                    "candidate_id": "candidate-1",
                    "generation_index": 1,
                    "candidate_side": "p0",
                    "opponent_name": "LightRush",
                    "opponent_agent": "ai.abstraction.LightRush",
                    "map_name": "maps/8x8/basesWorkers8x8.xml",
                    "map_width": 8,
                    "map_height": 8,
                    "round_index": 0,
                    "seed": 7,
                },
                round_state_dir=states,
                raw_result={"final_tick": 3, "players": {"p0": {"resource_total": 13}, "p1": {"resource_total": 10}}},
                tick_limit=3,
            )
            self.assertEqual([item["tick"] for item in iter_match_log(log_path)], [0, 1, 2, 3])
            candidate = Candidate(id="candidate-1", generation=1, strategy_prompt="Open with workers and defend the base.")
            context = ReflectionContext(
                generation=1,
                index=0,
                candidate_id=candidate.id,
                aggregate_game_performance=12.0,
                per_match_results=({
                    "match_id": "match-1",
                    "match_index": 0,
                    "match_log_path": str(log_path),
                    "opponent_name": "LightRush",
                    "map_name": "maps/8x8/basesWorkers8x8.xml",
                    "candidate_side": "p0",
                },),
            )
            mutation = StrategyReflectionMutation(MockRoleBackend(), max_attempts=2)
            result = mutation.run(candidate, context, artifact_dir=root / "child")

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.coach)
            self.assertFalse(log_path.exists())
            self.assertTrue((root / "child" / "commentary" / "match-1" / "match_analysis.json").exists())
            self.assertTrue((root / "child" / "commentary" / "match-1" / "commentary_status.json").exists())
            self.assertTrue((root / "child" / "reflection" / "coach_result.json").exists())
            coach_request = json.loads((root / "child" / "reflection" / "coach_request.json").read_text(encoding="utf-8"))["prompt"]
            self.assertIn("commentator_diagnoses_and_evaluation_metadata", coach_request)
            self.assertIn("stable opening", coach_request)
            self.assertNotIn("ROLE: manager", "\n".join(mutation.backend.prompts))
            self.assertIn("If the first combat group is ready", result.candidate.strategy_prompt)

    def test_commentary_failure_deletes_trace_without_changing_candidate(self) -> None:
        class BadBackend:
            def generate(self, prompt: str) -> str:
                return "not json"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
            log_path = root / "match_log.jsonl.gz"
            write_match_log(log_path, metadata={"match_id": "match-2"}, round_state_dir=states, raw_result={}, tick_limit=0)
            candidate = Candidate(id="candidate-2", strategy_prompt="Keep the base safe.")
            context = ReflectionContext(generation=1, index=0, candidate_id=candidate.id, per_match_results=({"match_id": "match-2", "match_log_path": str(log_path)},))
            result = StrategyReflectionMutation(BadBackend(), max_attempts=1).run(candidate, context, artifact_dir=root / "child")

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.candidate.strategy_prompt, candidate.strategy_prompt)
            self.assertFalse(log_path.exists())
            self.assertTrue((root / "child" / "reflection" / "commentary_failure.json").exists())


if __name__ == "__main__":
    unittest.main()
