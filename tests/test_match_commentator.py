import tempfile
import unittest
from pathlib import Path

from eagle.commentary_aggregation import aggregate_commentaries
from eagle.match_commentator import CommentaryConfig, CommentaryResult, commentate_match
from eagle.mutation import MockReflectionBackend
from evaluation.runtime_evaluation import run_microrts_match


class _InvalidBackend:
    def generate(self, prompt):
        return "{}"


class MatchCommentatorTests(unittest.TestCase):
    def _match(self, root, tick_limit=5):
        return run_microrts_match(
            microrts_dir=root, classes_dir=root, agent_class="Agent", opponent="Opp",
            tick_limit=tick_limit, match_index=0, match_artifacts_dir=root / "matches",
            match_output_dir=root / "matches" / "match_000", mock=True, artifact_mode="compact",
        )

    def test_short_match_uses_one_chunk_and_final_synthesis(self):
        with tempfile.TemporaryDirectory() as value:
            result = self._match(Path(value), 5)
            output = commentate_match(result, backend=MockReflectionBackend(), config=CommentaryConfig(chunk_ticks=20))
            self.assertEqual(output.status, "success")
            self.assertEqual(len(output.status_payload["covered_tick_ranges"]), 1)
            self.assertTrue((Path(result.match_dir) / "commentary" / "match_commentary.json").is_file())

    def test_long_match_chunks_are_contiguous_without_overlap(self):
        with tempfile.TemporaryDirectory() as value:
            result = self._match(Path(value), 7)
            output = commentate_match(result, backend=MockReflectionBackend(), config=CommentaryConfig(chunk_ticks=3))
            ranges = output.status_payload["covered_tick_ranges"]
            self.assertEqual([(item["first_tick"], item["last_tick"]) for item in ranges], [(0, 2), (3, 5), (6, 7)])
            self.assertEqual(sum(item["tick_count"] for item in ranges), 8)

    def test_invalid_final_response_is_persisted_without_fitness_effect(self):
        with tempfile.TemporaryDirectory() as value:
            result = self._match(Path(value), 2)
            output = commentate_match(result, backend=_InvalidBackend(), config=CommentaryConfig(chunk_ticks=10, max_attempts=2))
            self.assertEqual(output.status, "unavailable")
            self.assertIn(output.status_payload["failure_category"], {"invalid_response", "commentary_error"})
            self.assertEqual(result.score, result.performance_breakdown.match_score)

    def test_aggregation_groups_by_opponent_and_preserves_side_and_ticks(self):
        with tempfile.TemporaryDirectory() as value:
            result = self._match(Path(value), 2)
            commentary = {"match_id": "match_000", "candidate_side": "p0", "match_summary": "x", "turning_points": [{"tick": 1, "evidence": ["state"]}], "candidate_strengths": [{"description": "stable opening", "evidence_ticks": [1]}], "candidate_weaknesses": [], "decisive_causes": [{"description": "late attack", "evidence_ticks": [2]}], "strategy_recommendations": [{"recommendation": "attack after production", "supported_by_ticks": [2]}], "coverage": {"first_tick": 0, "last_tick": 2, "all_ticks_processed": True}}
            item = CommentaryResult("success", "match_000", commentary, {"status": "success"})
            aggregate = aggregate_commentaries([result], [item], candidate_id="candidate")
            self.assertEqual(aggregate["commented_match_count"], 1)
            self.assertEqual(aggregate["opponent_summaries"][0]["opponent"], "Opp")
            self.assertEqual(aggregate["opponent_summaries"][0]["representative_matches"][0]["tick_references"], [1, 2])


if __name__ == "__main__":
    unittest.main()
