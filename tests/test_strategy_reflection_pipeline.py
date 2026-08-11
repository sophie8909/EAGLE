from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.mutation import ReflectionContext
from eagle.reflection_context import EvolutionContext
from eagle.strategy_reflection import MockRoleBackend, StrategyReflectionMutation, select_reflection_matches
from evaluation.match_logs import iter_match_log, write_match_log
from evaluation.microrts_runner import write_mock_round_state


class StrategyReflectionPipelineTests(unittest.TestCase):
    @staticmethod
    def _result(match_id: str, outcome: str) -> dict[str, object]:
        winner = {"win": 0, "loss": 1, "draw": -1}[outcome]
        return {
            "match_id": match_id,
            "match_index": int(match_id.rsplit("-", 1)[-1]),
            "candidate_player": 0,
            "winner": winner,
            "result": "timeout_draw" if outcome == "draw" else f"p{winner}_win",
        }

    def test_selection_uses_one_strict_priority_pool_without_backfill(self) -> None:
        rows = [
            self._result("loss-0", "loss"),
            self._result("loss-1", "loss"),
            self._result("draw-0", "draw"),
            self._result("draw-1", "draw"),
            self._result("win-0", "win"),
        ]
        selection = select_reflection_matches(
            rows,
            run_seed=7,
            generation_index=4,
            candidate_id="candidate",
            reflection_invocation=2,
        )
        self.assertEqual(selection["selected_outcome_class"], "loss")
        self.assertEqual(selection["available_results"], {"loss": 2, "draw": 2, "win": 1})
        self.assertEqual(selection["eligible_match_ids"], ["loss-0", "loss-1"])
        self.assertEqual(selection["actual_sample_size"], 2)
        self.assertEqual(set(selection["selected_match_ids"]), {"loss-0", "loss-1"})
        self.assertEqual(len(selection["selected_match_ids"]), len(set(selection["selected_match_ids"])))

    def test_selection_is_reproducible_and_applies_draw_then_win_priority(self) -> None:
        rows = [self._result(f"draw-{index}", "draw") for index in range(5)]
        rows.extend(self._result(f"win-{index}", "win") for index in range(5))
        first = select_reflection_matches(rows, run_seed=7, generation_index=4, candidate_id="candidate", reflection_invocation=2)
        second = select_reflection_matches(rows, run_seed=7, generation_index=4, candidate_id="candidate", reflection_invocation=2)
        self.assertEqual(first, second)
        self.assertEqual(first["selected_outcome_class"], "draw")
        self.assertEqual(first["actual_sample_size"], 3)
        self.assertTrue(all(item.startswith("draw-") for item in first["selected_match_ids"]))

        wins = [self._result(f"win-{index}", "win") for index in range(4)]
        only_wins = select_reflection_matches(wins, run_seed=7, generation_index=4, candidate_id="candidate", reflection_invocation=2)
        self.assertEqual(only_wins["selected_outcome_class"], "win")
        self.assertEqual(only_wins["actual_sample_size"], 3)

        one_loss = select_reflection_matches(
            [self._result("loss-0", "loss"), *[self._result(f"draw-{index}", "draw") for index in range(5)]],
            run_seed=7,
            generation_index=4,
            candidate_id="candidate",
            reflection_invocation=2,
        )
        self.assertEqual(one_loss["selected_outcome_class"], "loss")
        self.assertEqual(one_loss["selected_match_ids"], ["loss-0"])

        one_draw = select_reflection_matches(
            [self._result("draw-0", "draw"), *[self._result(f"win-{index}", "win") for index in range(5)]],
            run_seed=7,
            generation_index=4,
            candidate_id="candidate",
            reflection_invocation=2,
        )
        self.assertEqual(one_draw["selected_outcome_class"], "draw")
        self.assertEqual(one_draw["selected_match_ids"], ["draw-0"])

    def test_selection_prioritizes_high_weight_opponents_within_outcome_pool(self) -> None:
        rows = []
        for index in range(3):
            row = self._result(f"high-{index}", "loss")
            row["opponent_weight"] = 2.0
            rows.append(row)
        for index in range(3):
            row = self._result(f"low-{index}", "loss")
            row["opponent_weight"] = 0.5
            rows.append(row)

        selection = select_reflection_matches(
            rows,
            run_seed=7,
            generation_index=4,
            candidate_id="candidate",
            reflection_invocation=2,
        )

        self.assertEqual(selection["selected_outcome_class"], "loss")
        self.assertEqual(selection["sampling_priority"], "descending_opponent_weight_within_selected_outcome")
        self.assertEqual(selection["actual_sample_size"], 3)
        self.assertTrue(all(item.startswith("high-") for item in selection["selected_match_ids"]))
        self.assertEqual(selection["opponent_weight_tiers"][0]["opponent_weight"], 2.0)

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
            self.assertEqual(selection["selected_outcome_class"], "loss")
            self.assertEqual(selection["actual_sample_size"], 2)
            commentator_prompts = [prompt for prompt in backend.prompts if "ROLE: match_commentator" in prompt]
            self.assertEqual(len(commentator_prompts), 2)
            self.assertEqual(len(selection["selected_match_ids"]), 2)
            self.assertEqual(len({item for item in selection["selected_match_ids"]}), 2)
            self.assertTrue(all(not Path(row["match_log_path"]).exists() for row in rows))
            manager_prompt = next(prompt for prompt in backend.prompts if "ROLE: manager" in prompt)
            self.assertIn('"selected_outcome_class": "loss"', manager_prompt)
            self.assertIn('"total_losses": 2', manager_prompt)

    def test_commentator_manager_coach_delete_trace_and_preserve_artifacts(self) -> None:
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
            self.assertIsNotNone(result.manager)
            self.assertIsNotNone(result.coach)
            self.assertFalse(log_path.exists())
            self.assertTrue((root / "child" / "commentary" / "match-1" / "match_analysis.json").exists())
            self.assertTrue((root / "child" / "commentary" / "match-1" / "commentary_status.json").exists())
            self.assertTrue((root / "child" / "reflection" / "manager_analysis.json").exists())
            self.assertTrue((root / "child" / "reflection" / "coach_result.json").exists())
            self.assertNotIn("match_log", json.loads((root / "child" / "reflection" / "manager_request.json").read_text(encoding="utf-8"))["prompt"])
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
