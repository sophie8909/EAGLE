from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eagle.candidate import Candidate
from eagle.mutation import ReflectionContext
from eagle.reflection_context import CandidateReflectionSummary, EvolutionContext
from eagle.strategy_reflection import (
    MockRoleBackend,
    StrategyReflectionMutation,
    _parse_commentary,
    build_global_evaluation_summary,
    cleanup_retired_match_traces,
    select_reflection_matches,
)
from evaluation.match_trace import iter_match_trace, write_match_trace
from evaluation.runtime_evaluation import write_mock_round_state


def _write_trace(path: Path, *, metadata, round_state_dir, raw_result, tick_limit) -> None:
    artifact = write_match_trace(
        round_state_dir=round_state_dir,
        match_dir=path.parent,
        metadata=metadata,
        result=raw_result,
        expected_last_tick=tick_limit,
    )
    artifact.trace_path.replace(path)


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
                _write_trace(
                    log_path,
                    metadata={"match_id": f"match-{index}", "candidate_side": "p0", "opponent_name": "LightRush"},
                    round_state_dir=states,
                    raw_result={"final_tick": 0, "players": {"p0": {"resource_total": 10}, "p1": {"resource_total": 10}}},
                    tick_limit=0,
                )
                row = self._result(f"match-{index}", outcome)
                row["match_trace_path"] = str(log_path)
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
            selection = json.loads((root / "child" / "mutation" / "strategy_reflection" / "match_selection.json").read_text(encoding="utf-8"))
            self.assertEqual(selection["selected_outcome_class"], "mixed")
            self.assertEqual(selection["actual_sample_size"], 5)
            commentator_prompts = [prompt for prompt in backend.prompts if "ROLE: match_commentator" in prompt]
            self.assertEqual(len(commentator_prompts), 5)
            self.assertEqual(len(selection["selected_match_ids"]), 5)
            self.assertEqual(len({item for item in selection["selected_match_ids"]}), 5)
            self.assertTrue(all(Path(row["match_trace_path"]).exists() for row in rows))
            coach_prompt = next(prompt for prompt in backend.prompts if "ROLE: coach" in prompt)
            self.assertIn('"global_evaluation_summary"', coach_prompt)
            self.assertIn('"total_matches": 5', coach_prompt)
            self.assertNotIn("raw_game_log:", coach_prompt)
            self.assertNotIn("ROLE: manager", "\n".join(backend.prompts))

    def test_strategy_reflection_persists_exact_observation_flow_without_extra_calls(self) -> None:
        parent_strategy = "Parent policy.\nKeep this exact trailing space.  "
        raw_child_strategy = "Revised policy.  \n\n\nAttack conditionally.   "

        class ExactBackend:
            def __init__(self) -> None:
                self.prompts: list[str] = []

            def generate(self, prompt: str) -> str:
                self.prompts.append(prompt)
                if "ROLE: match_commentator" in prompt:
                    match_line = next(line for line in prompt.splitlines() if line.startswith("match_id: "))
                    match_id = json.loads(match_line.removeprefix("match_id: "))
                    return json.dumps({
                        "match_id": match_id,
                        "candidate_strategy": {"summary": f"candidate-{match_id}"},
                        "opponent_strategy": {"summary": f"opponent-{match_id}"},
                        "turning_points": [{"tick": 0, "event": match_id}],
                        "candidate_strengths": [f"strength-{match_id}"],
                        "candidate_weaknesses": [f"weakness-{match_id}"],
                        "win_loss_analysis": {"result": "loss", "primary_reason": match_id},
                        "strategy_observations": [f"observation-{match_id}"],
                        "unconsumed_exact_field": {"match": match_id},
                    })
                return json.dumps({
                    "strategy_changes": {
                        "preserved": ["opening"],
                        "removed_or_reduced": [],
                        "added_or_strengthened": ["conditional attack"],
                    },
                    "strategy_signature": {
                        "opening": "worker_first",
                        "economy": "balanced",
                        "production": ["worker", "light"],
                        "attack_timing": "mid",
                        "combat_style": "pressure",
                        "expansion": "conditional",
                        "defense": "reactive",
                        "target_priority": "workers",
                    },
                    "parent_strategy_prompt": parent_strategy,
                    "new_strategy_prompt": raw_child_strategy,
                    "unconsumed_exact_field": "coach-raw-value",
                })

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rows: list[dict[str, object]] = []
            for index in range(2):
                states = root / f"states-{index}"
                write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
                log_path = root / f"match-{index}.jsonl.gz"
                _write_trace(
                    log_path,
                    metadata={"match_id": f"match-{index}", "candidate_side": "p0"},
                    round_state_dir=states,
                    raw_result={"final_tick": 0},
                    tick_limit=0,
                )
                row = self._result(
                    f"match-{index}",
                    "loss",
                    opponent="lightrush" if index == 0 else "heavyrush",
                    map_id=f"map_{index + 1}",
                )
                row["match_trace_path"] = str(log_path)
                row["extra_not_selected"] = "must not be copied"
                rows.append(row)

            candidate = Candidate(
                id="child-candidate",
                generation=3,
                parent_ids=("parent-source",),
                strategy_prompt=parent_strategy,
                strategy_parent_id="parent-source",
            )
            context = ReflectionContext(
                candidate=CandidateReflectionSummary(
                    candidate_id="parent-source",
                    strategy_prompt=parent_strategy,
                ),
                evolution=EvolutionContext(generation_index=3),
                per_match_results=tuple(rows),
            )
            backend = ExactBackend()
            artifact_dir = root / "child"
            result = StrategyReflectionMutation(
                backend,
                max_attempts=1,
                selection_seed=11,
                sample_budget=2,
            ).run(
                candidate,
                context,
                artifact_dir=artifact_dir,
                mutation_intent="REFINE",
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(len(backend.prompts), 3)
            self.assertEqual(sum("ROLE: match_commentator" in item for item in backend.prompts), 2)
            self.assertEqual(sum("ROLE: coach" in item for item in backend.prompts), 1)

            reflection_dir = artifact_dir / "mutation" / "strategy_reflection"
            self.assertEqual(
                (reflection_dir / "parent_strategy_prompt.txt").read_text(encoding="utf-8"),
                parent_strategy,
            )
            metadata = json.loads((reflection_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["child_candidate_id"], "child-candidate")
            self.assertEqual(metadata["parent_candidate_id"], "parent-source")
            self.assertEqual(metadata["selected_match_count"], 2)
            self.assertEqual(metadata["commentator_call_count"], 2)
            self.assertEqual(metadata["commentator_prompt_name"], "match_commentator")
            self.assertEqual(metadata["coach_prompt_name"], "coach_refine")

            selected = json.loads((reflection_dir / "selected_matches.json").read_text(encoding="utf-8"))
            selection = json.loads((reflection_dir / "match_selection.json").read_text(encoding="utf-8"))
            self.assertEqual([item["match_id"] for item in selected], selection["selected_match_ids"])
            self.assertNotIn("extra_not_selected", selected[0])
            commentator_outputs = [
                json.loads((reflection_dir / f"commentator_{index:02d}.json").read_text(encoding="utf-8"))
                for index in (1, 2)
            ]
            self.assertEqual(
                [item["match_id"] for item in commentator_outputs],
                selection["selected_match_ids"],
            )
            self.assertTrue(all("unconsumed_exact_field" in item for item in commentator_outputs))

            coach_input = json.loads((reflection_dir / "coach_input.json").read_text(encoding="utf-8"))
            self.assertEqual(coach_input["prompt_name"], "coach_refine")
            self.assertEqual(
                coach_input["semantic_payload"]["parent_strategy_prompt"],
                parent_strategy,
            )
            diagnoses = coach_input["semantic_payload"]["commentator_diagnoses_and_evaluation_metadata"]["commentator_diagnoses"]
            self.assertEqual([item["match_id"] for item in diagnoses], selection["selected_match_ids"])
            self.assertEqual(
                coach_input["render_variables"]["parent_strategy_prompt"],
                json.dumps(parent_strategy, ensure_ascii=False),
            )
            self.assertEqual(
                (reflection_dir / "coach_prompt.txt").read_text(encoding="utf-8"),
                next(item for item in backend.prompts if "ROLE: coach" in item),
            )
            coach_raw = (reflection_dir / "coach_raw.txt").read_text(encoding="utf-8")
            coach_output = json.loads((reflection_dir / "coach_output.json").read_text(encoding="utf-8"))
            self.assertEqual(coach_output, json.loads(coach_raw))
            self.assertEqual(coach_output["unconsumed_exact_field"], "coach-raw-value")
            self.assertEqual(result.candidate.strategy_prompt, "Revised policy.\n\nAttack conditionally.")
            self.assertEqual(
                (reflection_dir / "child_strategy_prompt.txt").read_text(encoding="utf-8"),
                result.candidate.strategy_prompt,
            )
            coach_request = json.loads((reflection_dir / "coach_request.json").read_text(encoding="utf-8"))
            self.assertEqual(coach_request["parent_candidate_id"], "parent-source")

    def test_ten_selected_logs_have_ten_independent_commentator_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rows = []
            for index in range(10):
                states = root / f"states-{index}"
                write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
                log_path = root / f"match-{index}.jsonl.gz"
                _write_trace(
                    log_path,
                    metadata={"match_id": f"match-{index}", "candidate_side": "p0", "opponent_name": "LightRush", "map_name": f"map_{index + 1}"},
                    round_state_dir=states,
                    raw_result={"final_tick": 0, "players": {"p0": {"resource_total": 10}, "p1": {"resource_total": 10}}},
                    tick_limit=0,
                )
                row = self._result(f"match-{index}", "loss", map_id=f"map_{index + 1}")
                row["match_trace_path"] = str(log_path)
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

    def test_commentator_direct_coach_preserves_trace_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            for tick in range(4):
                write_mock_round_state(states, tick=tick, p0_resource=10 + tick, p1_resource=10)
            log_path = root / "match_trace.jsonl.gz"
            _write_trace(
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
                },
                round_state_dir=states,
                raw_result={"final_tick": 3, "players": {"p0": {"resource_total": 13}, "p1": {"resource_total": 10}}},
                tick_limit=3,
            )
            self.assertEqual([item["tick"] for item in iter_match_trace(log_path)], [0, 1, 2, 3])
            candidate = Candidate(id="candidate-1", generation=1, strategy_prompt="Open with workers and defend the base.")
            context = ReflectionContext(
                generation=1,
                index=0,
                candidate_id=candidate.id,
                aggregate_game_performance=12.0,
                per_match_results=({
                    "match_id": "match-1",
                    "match_index": 0,
                    "match_trace_path": str(log_path),
                    "opponent_name": "LightRush",
                    "map_name": "maps/8x8/basesWorkers8x8.xml",
                    "candidate_side": "p0",
                },),
            )
            mutation = StrategyReflectionMutation(MockRoleBackend(), max_attempts=2)
            result = mutation.run(candidate, context, artifact_dir=root / "child")

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.coach)
            self.assertTrue(log_path.exists())
            self.assertTrue((root / "child" / "mutation" / "strategy_reflection" / "commentary" / "match-1" / "match_analysis.json").exists())
            self.assertTrue((root / "child" / "mutation" / "strategy_reflection" / "commentary" / "match-1" / "commentary_status.json").exists())
            self.assertTrue((root / "child" / "mutation" / "strategy_reflection" / "coach_result.json").exists())
            coach_request = json.loads((root / "child" / "mutation" / "strategy_reflection" / "coach_request.json").read_text(encoding="utf-8"))["prompt"]
            self.assertIn("commentator_diagnoses_and_evaluation_metadata", coach_request)
            self.assertIn("stable opening", coach_request)
            self.assertNotIn("ROLE: manager", "\n".join(mutation.backend.prompts))
            self.assertIn("If the first combat group is ready", result.candidate.strategy_prompt)

    def test_repeated_siblings_can_reuse_the_same_parent_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
            log_path = root / "match_trace.jsonl.gz"
            _write_trace(log_path, metadata={"match_id": "match-3"}, round_state_dir=states, raw_result={}, tick_limit=0)
            context = ReflectionContext(
                generation=1,
                index=0,
                candidate_id="parent",
                per_match_results=({"match_id": "match-3", "match_trace_path": str(log_path)},),
            )

            first = StrategyReflectionMutation(MockRoleBackend(), max_attempts=1).run(
                Candidate(id="sibling-1", strategy_prompt="Defend, then attack."),
                context,
                artifact_dir=root / "sibling-1",
            )
            second = StrategyReflectionMutation(MockRoleBackend(), max_attempts=1).run(
                Candidate(id="sibling-2", strategy_prompt="Defend, then attack."),
                context,
                artifact_dir=root / "sibling-2",
            )

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            self.assertTrue(log_path.exists())

    def test_malformed_commentary_is_retried_with_raw_attempt_evidence(self) -> None:
        class RetryBackend:
            def __init__(self) -> None:
                self.mock = MockRoleBackend()
                self.commentator_attempts = 0

            def generate(self, prompt: str) -> str:
                if "ROLE: match_commentator" in prompt:
                    self.commentator_attempts += 1
                    if self.commentator_attempts == 1:
                        return '{"match_id":"match-4" "turning_points":[]}'
                    if self.commentator_attempts == 2:
                        return json.dumps({
                            "match_id": "match-4",
                            "candidate_strategy": {"summary": "passive"},
                            "opponent_strategy": {"summary": "pressure"},
                            "turning_points": [],
                            "candidate_strengths": [],
                            "candidate_weaknesses": [],
                            "win_loss_analysis": {"result": "loss"},
                            "strategy_observations": [],
                        })
                return self.mock.generate(prompt)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
            log_path = root / "match_trace.jsonl.gz"
            _write_trace(log_path, metadata={"match_id": "match-4"}, round_state_dir=states, raw_result={}, tick_limit=0)
            backend = RetryBackend()
            result = StrategyReflectionMutation(backend, max_attempts=3).run(
                Candidate(id="retry-commentary", strategy_prompt="Defend, then attack."),
                ReflectionContext(
                    generation=1,
                    index=0,
                    candidate_id="parent",
                    per_match_results=({"match_id": "match-4", "match_trace_path": str(log_path)},),
                ),
                artifact_dir=root / "child",
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(backend.commentator_attempts, 3)
            attempt_dir = root / "child" / "mutation" / "strategy_reflection" / "commentary" / "match-4"
            first_attempt = json.loads((attempt_dir / "response_attempt_001.json").read_text(encoding="utf-8"))
            second_attempt = json.loads((attempt_dir / "response_attempt_002.json").read_text(encoding="utf-8"))
            third_attempt = json.loads((attempt_dir / "response_attempt_003.json").read_text(encoding="utf-8"))
            self.assertEqual(first_attempt["status"], "error")
            self.assertIn('"match_id":"match-4"', first_attempt["response"])
            self.assertEqual(second_attempt["status"], "error")
            self.assertIn('"turning_points": []', second_attempt["response"])
            self.assertEqual(third_attempt["status"], "success")

    def test_semantically_invalid_coach_is_retried(self) -> None:
        class RetryCoachBackend:
            def __init__(self) -> None:
                self.mock = MockRoleBackend()
                self.coach_attempts = 0

            def generate(self, prompt: str) -> str:
                if "ROLE: coach" in prompt:
                    self.coach_attempts += 1
                    if self.coach_attempts == 1:
                        return json.dumps({"new_strategy_prompt": "public void invalidJava() {}"})
                return self.mock.generate(prompt)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
            log_path = root / "match_trace.jsonl.gz"
            _write_trace(log_path, metadata={"match_id": "match-5"}, round_state_dir=states, raw_result={}, tick_limit=0)
            backend = RetryCoachBackend()
            result = StrategyReflectionMutation(backend, max_attempts=2).run(
                Candidate(id="retry-coach", strategy_prompt="Defend, then attack."),
                ReflectionContext(
                    generation=1,
                    index=0,
                    candidate_id="parent",
                    per_match_results=({"match_id": "match-5", "match_trace_path": str(log_path)},),
                ),
                artifact_dir=root / "child",
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(backend.coach_attempts, 2)
            reflection_dir = root / "child" / "mutation" / "strategy_reflection"
            first_attempt = json.loads((reflection_dir / "coach_response_attempt_001.json").read_text(encoding="utf-8"))
            second_attempt = json.loads((reflection_dir / "coach_response_attempt_002.json").read_text(encoding="utf-8"))
            self.assertEqual(first_attempt["status"], "error")
            self.assertIn("public void", first_attempt["response"])
            self.assertEqual(second_attempt["status"], "success")

    def test_commentary_failure_preserves_trace_without_changing_candidate(self) -> None:
        class BadBackend:
            def __init__(self) -> None:
                self.prompts: list[str] = []

            def generate(self, prompt: str) -> str:
                self.prompts.append(prompt)
                return "not json"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            states = root / "states"
            write_mock_round_state(states, tick=0, p0_resource=10, p1_resource=10)
            log_path = root / "match_trace.jsonl.gz"
            _write_trace(log_path, metadata={"match_id": "match-2"}, round_state_dir=states, raw_result={}, tick_limit=0)
            candidate = Candidate(id="candidate-2", strategy_prompt="Keep the base safe.")
            context = ReflectionContext(generation=1, index=0, candidate_id=candidate.id, per_match_results=({"match_id": "match-2", "match_trace_path": str(log_path)},))
            backend = BadBackend()
            result = StrategyReflectionMutation(backend, max_attempts=1).run(candidate, context, artifact_dir=root / "child")

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.candidate.strategy_prompt, candidate.strategy_prompt)
            self.assertTrue(log_path.exists())
            self.assertFalse(any("ROLE: coach" in prompt for prompt in backend.prompts))
            self.assertTrue((root / "child" / "mutation" / "strategy_reflection" / "commentary_failure.json").exists())

    def test_generation_boundary_cleanup_removes_only_retired_candidate_traces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidates_dir = Path(temp_dir) / "candidates"
            survivor = Candidate(id="survivor")
            retired = Candidate(id="retired")
            survivor_trace = candidates_dir / survivor.id / "matches" / "match_00" / "match_trace.jsonl.gz"
            retired_trace = candidates_dir / retired.id / "matches" / "match_00" / "match_trace.jsonl.gz"
            survivor_trace.parent.mkdir(parents=True)
            retired_trace.parent.mkdir(parents=True)
            survivor_trace.write_bytes(b"survivor")
            retired_trace.write_bytes(b"retired")

            cleanup_retired_match_traces(
                candidates_dir,
                [survivor, retired],
                surviving_candidate_ids={survivor.id},
            )

            self.assertTrue(survivor_trace.exists())
            self.assertFalse(retired_trace.exists())

    def test_commentary_normalizes_0823_match_analysis_shape(self) -> None:
        analysis = _parse_commentary({
            "match_analysis": {
                "match_id": "match_48",
                "opponent": "WorkerRush",
                "result": "loss",
                "candidate_strategy": "WorkerRush with conditional base targeting",
                "key_observations": [
                    {
                        "time": "0-18",
                        "event": "Initial stalemate",
                        "analysis": {
                            "candidate": {"behavior": "one idle Worker", "issue": "no harvesting"},
                            "opponent": {"behavior": "passive"},
                        },
                    },
                    {"time": "18+", "event": "Opponent builds Barracks", "analysis": {"impact": "pressure begins"}},
                    {"time": "1137-1138", "event": "Final defeat", "analysis": {"issue": "last Worker dies"}},
                ],
                "strategic_failures": [
                    {"category": "Resource Management", "issue": "Failed to harvest."},
                ],
                "opponent_strengths": [
                    {"tactic": "Combat unit spam", "impact": "Overwhelmed the Worker."},
                ],
                "recommendations": [{"action": "rewrite the policy"}],
            }
        }, "fallback-match")

        self.assertEqual(analysis.match_id, "match_48")
        self.assertEqual(analysis.candidate_strategy["summary"], "WorkerRush with conditional base targeting")
        self.assertEqual([item["tick"] for item in analysis.turning_points], [0, 18, 1137])
        self.assertEqual(analysis.win_loss_analysis["result"], "loss")
        self.assertEqual(analysis.candidate_weaknesses, ("Resource Management: Failed to harvest.",))
        self.assertIn("Combat unit spam", analysis.opponent_strategy["summary"])
        self.assertEqual(analysis.strategy_observations, ())

    def test_commentary_still_rejects_turning_points_without_numeric_ticks(self) -> None:
        with self.assertRaisesRegex(ValueError, "tick-backed turning points"):
            _parse_commentary({
                "match_analysis": {
                    "candidate_strategy": "Worker pressure",
                    "opponent_strategy": "Defensive economy",
                    "key_observations": [{"time": "opening", "event": "No tick evidence"}],
                }
            }, "match-without-ticks")

    def test_roles_disabled_still_persists_known_provenance_without_selection_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = Candidate(
                id="child-disabled",
                generation=2,
                strategy_prompt="Exact parent strategy.",
                strategy_parent_id="parent-disabled",
            )
            result = StrategyReflectionMutation(
                MockRoleBackend(),
                max_attempts=1,
                enabled_roles={"coach"},
            ).run(
                candidate,
                ReflectionContext(evolution=EvolutionContext(generation_index=2)),
                artifact_dir=root / "child",
                mutation_intent="COUNTER",
            )

            self.assertEqual(result.status, "failed")
            reflection_dir = root / "child" / "mutation" / "strategy_reflection"
            metadata = json.loads((reflection_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["child_candidate_id"], "child-disabled")
            self.assertEqual(metadata["parent_candidate_id"], "parent-disabled")
            self.assertEqual(metadata["coach_prompt_name"], "coach_counter")
            self.assertNotIn("selected_match_count", metadata)
            self.assertNotIn("commentator_call_count", metadata)
            self.assertEqual(
                (reflection_dir / "parent_strategy_prompt.txt").read_text(encoding="utf-8"),
                candidate.strategy_prompt,
            )


if __name__ == "__main__":
    unittest.main()
