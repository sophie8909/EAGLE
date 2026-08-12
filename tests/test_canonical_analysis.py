from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eagle.analysis.loader import load_run, resolve_explicit_run, resolve_latest_run
from eagle.analysis.report import OUTPUT_FILES, generate_analysis
from eagle.run_artifacts import atomic_json


class CanonicalAnalysisTests(unittest.TestCase):
    def make_run(self, root: Path, name: str, *, stamp: datetime, valid: bool = True) -> Path:
        run = root / name
        run.mkdir()
        atomic_json(run / "resolved_config.json", {})
        atomic_json(run / "manifest.json", {
            "schema_version": "eagle-run-v1" if valid else "bad",
            "status": "initialized",
            "configuration": "resolved_config.json",
            "completed_generations": [],
            "last_update_time": stamp.isoformat(),
        })
        return run

    def test_latest_uses_valid_direct_children_and_manifest_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            older = self.make_run(root, "older", stamp=now)
            newer = self.make_run(root, "newer", stamp=now + timedelta(seconds=1))
            self.make_run(root, "invalid", stamp=now + timedelta(days=1), valid=False)
            nested_parent = root / "parent"
            nested_parent.mkdir()
            self.make_run(nested_parent, "nested", stamp=now + timedelta(days=2))
            self.assertEqual(resolve_latest_run(root), newer.resolve())
            self.assertNotEqual(resolve_latest_run(root), older.resolve())

    def test_explicit_relative_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            self.assertEqual(resolve_explicit_run(run), run.resolve())
            current = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(resolve_explicit_run("run"), run.resolve())
            finally:
                os.chdir(current)
            with self.assertRaises(ValueError):
                resolve_explicit_run(root)

    def test_outputs_partial_run_without_results_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            (run / "results.jsonl").write_text("not json\n", encoding="utf-8")
            output = generate_analysis(load_run(run), force=True)
            for name in OUTPUT_FILES:
                self.assertTrue((output / name).is_file())
            self.assertEqual((run / "results.jsonl").read_text(encoding="utf-8"), "not json\n")

    def test_outputs_individual_agent_game_performance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            (run / "generations").mkdir()
            atomic_json(run / "generations" / "generation_0000.json", {
                "schema_version": "eagle-generation-v2",
                "generation": 0,
                "population": [{
                    "candidate_id": "agent-a",
                    "generation": 0,
                    "status": "evaluated",
                    "operator": "seed",
                    "mutation_type": None,
                    "fitness_objectives": {"game_performance": 12.5, "code_quality": 80.0},
                }],
            })
            output = generate_analysis(load_run(run), force=True)
            rows = (output / "agent_game_performance.csv").read_text(encoding="utf-8")
            self.assertIn("candidate_id", rows)
            self.assertIn("agent-a", rows)
            self.assertIn("12.5", rows)

    def test_outputs_strategy_diversity_and_niche_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            atomic_json(run / "generation_metrics.jsonl", {})
            (run / "generation_metrics.jsonl").write_text(
                json.dumps({
                    "generation": 2,
                    "population_size": 2,
                    "strategy_diversity": {
                        "unique_niches": 2,
                        "dominant_niche": "early-light-rush",
                        "dominant_niche_count": 1,
                        "dominant_niche_ratio": 0.5,
                        "mean_strategy_distance": 0.25,
                        "new_niches": 1,
                        "revisited_niches": 1,
                        "niche_change_rate": 0.5,
                        "niche_distribution": {"early-light-rush": 1, "mid-mixed-balanced": 1},
                        "intent_niche_change_rates": {"STRUCTURAL": 1.0},
                    },
                    "objectives": {},
                }) + "\n",
                encoding="utf-8",
            )
            output = generate_analysis(load_run(run), force=True)
            diversity = (output / "strategy_diversity.csv").read_text(encoding="utf-8")
            niches = (output / "strategy_niches.csv").read_text(encoding="utf-8")
            self.assertIn("early-light-rush", diversity)
            self.assertIn("0.25", diversity)
            self.assertIn("mid-mixed-balanced", niches)
            self.assertFalse(list((output / "plots").glob("*.png")))

    def test_plot_set_contains_only_objectives_agents_and_opponents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            (run / "generations").mkdir()
            atomic_json(run / "generations" / "generation_0000.json", {
                "schema_version": "eagle-generation-v2",
                "generation": 0,
                "population": [{
                    "candidate_id": "agent-a", "generation": 0, "status": "evaluated",
                    "fitness_objectives": {"game_performance": 12.5, "code_quality": 80.0},
                }],
            })
            (run / "generation_metrics.jsonl").write_text(json.dumps({
                "generation": 0,
                "objectives": {
                    "game_performance": {"objective_id": "game_performance", "best": 12.5, "mean": 12.5, "median": 12.5, "worst": 12.5},
                    "code_quality": {"objective_id": "code_quality", "best": 80.0, "mean": 80.0, "median": 80.0, "worst": 80.0},
                },
                "opponent_scores": {"by_opponent": {
                    "passive": {"game_performance": 20.0},
                    "random": {"game_performance": 5.0},
                }},
            }) + "\n", encoding="utf-8")
            output = generate_analysis(load_run(run), force=True)
            plot_names = {path.name for path in (output / "plots").glob("*.png")}
            self.assertEqual(plot_names, {
                "agent_game_performance.png",
                "code_quality_by_generation.png",
                "game_performance_by_generation.png",
                "game_performance_by_generation_passive.png",
                "game_performance_by_generation_random.png",
            })
            opponent_rows = (output / "opponent_game_performance.csv").read_text(encoding="utf-8")
            self.assertIn("passive", opponent_rows)
            self.assertIn("20.0", opponent_rows)
