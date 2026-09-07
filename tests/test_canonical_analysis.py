from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

from eagle.analysis.loader import RunData, load_run, resolve_explicit_run, resolve_latest_run
from eagle.analysis import report
from eagle.analysis.report import OUTPUT_FILES, generate_analysis
from eagle.run_artifacts import atomic_json


class CanonicalAnalysisTests(unittest.TestCase):
    def make_run(self, root: Path, name: str, *, stamp: datetime, valid: bool = True) -> Path:
        run = root / name
        run.mkdir()
        (run / "config.yaml").write_text(
            yaml.safe_dump({"schema_version": "experiment-v2"}),
            encoding="utf-8",
        )
        atomic_json(run / "manifest.json", {
            "schema_version": "eagle-run-v2" if valid else "bad",
            "status": "initialized",
            "latest_generation": None,
            "updated_at": stamp.isoformat(),
        })
        return run

    def test_v2_loader_reads_config_and_generation_owned_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            (run / "generations").mkdir(parents=True)
            candidate_dir = run / "candidates" / "candidate-a"
            (candidate_dir / "evaluation").mkdir(parents=True)
            (run / "archives").mkdir()
            (run / "config.yaml").write_text(
                yaml.safe_dump({"schema_version": "experiment-v2"}),
                encoding="utf-8",
            )
            atomic_json(run / "manifest.json", {
                "schema_version": "eagle-run-v2", "status": "complete",
                "latest_generation": 0, "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            atomic_json(run / "candidates" / "candidate-a" / "candidate.json", {
                "candidate_id": "candidate-a", "fitness_objectives": {"lightrush": 1.0},
                "artifacts": {
                    "game_performance": "evaluation/game_performance.json",
                    "code_quality": "evaluation/code_quality.json",
                },
            })
            atomic_json(candidate_dir / "evaluation" / "game_performance.json", {
                "game_performance": 1.0,
                "win_rate": 1.0,
                "opponent_results": [{
                    "opponent_id": "lightrush", "wins": 1, "draws": 0, "losses": 0,
                    "expected_match_count": 1, "completed_match_count": 1,
                    "match_scores": [101.5],
                }],
                "match_results": [{"large_payload": "must not be retained"}],
            })
            atomic_json(candidate_dir / "evaluation" / "code_quality.json", {
                "code_quality": 75.0, "failure_stage": None,
            })
            atomic_json(run / "generations" / "generation_0000.json", {
                "schema_version": "eagle-generation-v3", "generation": 0,
                "population": [{"candidate_id": "candidate-a", "fitness_objectives": {"lightrush": 1.0}}],
                "metrics": {"generation": 0, "population_size": 1},
                "aos": {"mode": "static"},
            })
            data = load_run(run)
            self.assertEqual(data.resolved_config["schema_version"], "experiment-v2")
            self.assertEqual(data.generation_metrics[0]["aos"]["mode"], "static")
            self.assertEqual(data.final_population["population"][0]["candidate_id"], "candidate-a")
            materialized = data.generations[0]["population"][0]
            self.assertEqual(materialized["game_eval_result"]["opponent_results"][0]["match_scores"], [101.5])
            self.assertNotIn("match_results", materialized["game_eval_result"])
            self.assertEqual(materialized["code_quality_result"]["code_quality"], 75.0)
            output = generate_analysis(data, force=True)
            summary = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["schema_version"], "eagle-analysis-v2")
            match_rows = (output / "match_game_performance.csv").read_text(encoding="utf-8")
            self.assertIn("101.5", match_rows)

    def test_operator_probability_plot_title_labels_mode(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            report.plt, "title"
        ) as title:
            report._aos_plot(Path(directory) / "plot.png", [{
                "generation": 0,
                "mode": "static",
                "operator": "strategy_reflection",
                "selection_probability": 0.2,
            }])
        title.assert_called_with("Reflection operator probabilities by generation — static")

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

    def test_run_v1_is_explicitly_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            (run / "config.yaml").write_text("schema_version: experiment-v2\n", encoding="utf-8")
            atomic_json(run / "manifest.json", {"schema_version": "eagle-run-v1"})
            with self.assertRaisesRegex(ValueError, "Unsupported run manifest schema"):
                load_run(run)

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

    def test_survivor_analysis_uses_snapshot_generation_and_retains_birth_generation(self):
        survivor = {
            "candidate_id": "survivor-a",
            "generation": 2,
            "status": "evaluated",
            "game_eval_result": {
                "game_performance": 25.0,
                "opponent_results": [{
                    "opponent_id": "lightrush",
                    "wins": 1,
                    "draws": 0,
                    "losses": 0,
                    "expected_match_count": 1,
                    "completed_match_count": 1,
                    "match_scores": [101.0],
                }],
            },
        }
        data = RunData(
            run_dir=Path("/unused"),
            manifest={},
            resolved_config={},
            generation_metrics=[],
            generations=[
                {"generation": 4, "population": [survivor]},
                {"generation": 5, "population": [survivor]},
            ],
            final_population=None,
            timing=[],
            errors=[],
        )

        for rows in (
            report._agent_game_performance_rows(data),
            report._agent_win_rate_rows(data),
            report._match_game_performance_rows(data),
        ):
            self.assertEqual([row["generation"] for row in rows], [4, 5])
            self.assertEqual([row["birth_generation"] for row in rows], [2, 2])

    def test_outputs_strategy_diversity_and_niche_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            (run / "generations").mkdir()
            atomic_json(run / "generations" / "generation_0002.json", {
                    "schema_version": "eagle-generation-v3",
                    "generation": 2,
                    "population": [],
                    "metrics": {
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
                    },
                    "aos": None,
                })
            output = generate_analysis(load_run(run), force=True)
            diversity = (output / "strategy_diversity.csv").read_text(encoding="utf-8")
            niches = (output / "strategy_niches.csv").read_text(encoding="utf-8")
            self.assertIn("early-light-rush", diversity)
            self.assertIn("0.25", diversity)
            self.assertIn("mid-mixed-balanced", niches)
            self.assertFalse(list((output / "plots").glob("*.png")))

    def test_outputs_capability_regression_metrics_in_generation_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            (run / "generations").mkdir()
            atomic_json(run / "generations" / "generation_0000.json", {
                "schema_version": "eagle-generation-v3",
                "generation": 0,
                "population": [],
                "metrics": {
                    "generation": 0,
                    "population_size": 2,
                    "light_rush_win_rate": 0.5,
                    "heavy_rush_win_rate": 0.0,
                    "objectives": {},
                },
                "aos": None,
            })
            output = generate_analysis(load_run(run), force=True)
            rows = (output / "generation_metrics.csv").read_text(encoding="utf-8")
            self.assertIn("light_rush_win_rate", rows)
            self.assertIn("heavy_rush_win_rate", rows)
            self.assertIn("0.5", rows)

    def test_aggregate_game_performance_plot_adds_neutral_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plot.png"
            with mock.patch.object(report.plt, "axhline") as axhline:
                report._line_plot(
                    output,
                    [{"generation": 0, "game_performance_mean": 0.0}],
                    "generation",
                    ("game_performance_mean",),
                    "Game Performance",
                    neutral_line=True,
                )
            self.assertEqual([call.args[0] for call in axhline.call_args_list], [0.0])
            self.assertEqual(axhline.call_args_list[0].kwargs["linestyle"], "--")

    def test_match_distribution_uses_narrow_violins_instead_of_scatter(self):
        body = mock.Mock()
        medians = mock.Mock()
        with (
            mock.patch.object(
                report.plt,
                "violinplot",
                return_value={"bodies": [body], "cmedians": medians},
            ) as violinplot,
            mock.patch.object(report.plt, "scatter") as scatter,
            mock.patch.object(report.plt, "hlines") as hlines,
        ):
            report._match_violin_overlay(
                [
                    {"generation": 0, "game_performance": -100.0},
                    {"generation": 0, "game_performance": 0.0},
                    {"generation": 0, "game_performance": 100.0},
                    {"generation": 1, "game_performance": 25.0},
                ],
                x="generation",
                y="game_performance",
            )

        self.assertEqual(violinplot.call_args.args[0], [[-100.0, 0.0, 100.0]])
        self.assertEqual(violinplot.call_args.kwargs["positions"], [0])
        self.assertEqual(violinplot.call_args.kwargs["widths"], 0.42)
        scatter.assert_not_called()
        hlines.assert_called_once()
        body.set_label.assert_called_once_with("Single-match distribution")
        medians.set_linewidth.assert_called_once_with(1.0)

    def test_analysis_writes_agent_win_rates_and_match_distribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            (run / "generations").mkdir()
            atomic_json(run / "generations" / "generation_0000.json", {
                "schema_version": "eagle-generation-v3",
                "generation": 0,
                "population": [{
                    "candidate_id": "agent-a", "generation": 0, "status": "evaluated",
                    "game_eval_result": {
                        "game_performance": 0.0, "win_rate": 0.5,
                        "opponent_results": [{
                            "opponent_id": "lightrush", "wins": 1, "draws": 1, "losses": 1,
                            "expected_match_count": 3, "completed_match_count": 3,
                            "match_scores": [-100.0, 0.0, 100.0],
                        }],
                    },
                }],
                "metrics": {
                    "generation": 0,
                    "population_size": 1,
                    "game_performance": {"best": 0.0, "mean": 0.0, "median": 0.0, "worst": 0.0},
                    "opponent_scores": {"by_opponent": {"lightrush": {"game_performance": 0.0}}},
                    "objectives": {},
                },
                "aos": {"mode": "aos_head2head", "reward_source": "head2head", "operators": {
                    "strategy_reflection": {
                        "usage_count": 0, "reward_count": 0, "mean_reward": None,
                        "recent_credit": 0.0, "selection_probability": 0.2,
                        "selection_probability_before": 0.2,
                    },
                    "code_reflection": {
                        "usage_count": 1, "reward_count": 1, "mean_reward": 1.0,
                        "operator_quality_before": 0.0, "operator_quality_after": 0.2,
                        "recent_credit": 0.2, "selection_probability": 0.8,
                        "selection_probability_before": 0.8,
                        "head_to_head": {"wins": 18, "draws": 0, "losses": 0, "errors": 0, "total_matches": 18},
                    },
                }},
            })
            output = generate_analysis(load_run(run), force=True)
            win_rates = (output / "agent_win_rate.csv").read_text(encoding="utf-8")
            match_scores = (output / "match_game_performance.csv").read_text(encoding="utf-8")
            self.assertIn("agent-a", win_rates)
            self.assertIn("lightrush", win_rates)
            self.assertIn("0.333333", win_rates)
            self.assertIn("-100.0", match_scores)
            self.assertIn("100.0", match_scores)
            self.assertTrue((output / "plots" / "win_rate_by_generation_lightrush.png").is_file())
            self.assertTrue((output / "plots" / "aos_operator_probabilities.png").is_file())
            aos_csv = (output / "aos_operator_statistics.csv").read_text(encoding="utf-8")
            self.assertIn("strategy_reflection", aos_csv)
            self.assertIn("aos_head2head", aos_csv)
            self.assertIn("head2head", aos_csv)
            self.assertIn("parent_vs_offspring_wins", aos_csv)
            self.assertIn("code_reflection,1,1,1.0,0.0,0.2", aos_csv)
            self.assertIn(",18,0,0,0,18,", aos_csv)

    def test_plot_set_contains_only_objectives_agents_and_opponents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.make_run(root, "run", stamp=datetime.now(timezone.utc))
            (run / "generations").mkdir()
            atomic_json(run / "generations" / "generation_0000.json", {
                "schema_version": "eagle-generation-v3",
                "generation": 0,
                "population": [{
                    "candidate_id": "agent-a", "generation": 0, "status": "evaluated",
                    "fitness_objectives": {"game_performance": 12.5, "code_quality": 80.0},
                    "game_eval_result": {
                        "game_performance": 12.5,
                        "opponent_results": [
                            {"opponent_id": "passive", "wins": 1, "expected_match_count": 1, "completed_match_count": 1},
                            {"opponent_id": "random", "wins": 0, "expected_match_count": 1, "completed_match_count": 1},
                        ],
                    },
                }],
                "metrics": {
                    "generation": 0,
                    "objectives": {
                        "game_performance": {"objective_id": "game_performance", "best": 12.5, "mean": 12.5, "median": 12.5, "worst": 12.5},
                        "code_quality": {"objective_id": "code_quality", "best": 80.0, "mean": 80.0, "median": 80.0, "worst": 80.0},
                    },
                    "opponent_scores": {"by_opponent": {
                        "passive": {"game_performance": 20.0},
                        "random": {"game_performance": 5.0},
                    }},
                },
                "aos": None,
            })
            output = generate_analysis(load_run(run), force=True)
            plot_names = {path.name for path in (output / "plots").glob("*.png")}
            self.assertEqual(plot_names, {
                "agent_game_performance.png",
                "code_quality_by_generation.png",
                "game_performance_by_generation.png",
                "game_performance_by_generation_passive.png",
                "game_performance_by_generation_random.png",
                "win_rate_by_generation_passive.png",
                "win_rate_by_generation_random.png",
            })
            opponent_rows = (output / "opponent_game_performance.csv").read_text(encoding="utf-8")
            self.assertIn("passive", opponent_rows)
            self.assertIn("20.0", opponent_rows)
