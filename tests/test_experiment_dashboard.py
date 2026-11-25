import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.analysis import experiment_dashboard as dashboard


class ExperimentDashboardTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        self.runs = []
        self.treatments = []
        for treatment, seeds in (("base", [8, 9, 10]), ("change", [8, 9])):
            self.treatments.append(dict(experiment="exp", treatment=treatment, label=treatment, expected_seeds=seeds))
            for seed in seeds:
                self.runs.append(dict(
                    experiment="exp", treatment=treatment, label=treatment, seed=seed,
                    run_id=f"{treatment}-{seed}", indexed=True, status="complete",
                    latest_generation=5 if treatment == "base" else 3,
                    planned_generation=5 if treatment == "base" else 3,
                ))
        self.runs.append({**self.runs[0], "indexed": False, "run_id": "old-attempt", "status": "failed"})
        for name, value in (("discover", self.discover), ("read_metrics", self.metrics)):
            replacement = patch.object(dashboard, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def discover(self, root, runs_roots):
        return {"schema_version": "eagle-experiment-catalog-v1", "issues": [], "runs": self.runs, "treatments": self.treatments}

    def metrics(self, run, *, fixed_opponent=None):
        seed = run["seed"]
        offset = 10 if run["treatment"] == "change" else 0
        value = offset + seed + (100 if run["run_id"] == "old-attempt" else 0)
        points = [
            dict(metric="fixed", statistic="mean", generation=generation, value=value,
                 protocol="p", source="fixed_evaluation/summary.json")
            for generation in (0, 2, 3) if seed != 9 or generation != 2
        ]
        points.append(dict(metric="final", statistic="score", generation=run["latest_generation"],
                           value=value, protocol="p"))
        return {
            "points": points, "issues": [], "protocols": {"p": {"scoring": "fixture"}},
            "opponents": [dict(opponent="WorkerRush", wins=seed, draws=0, losses=seed - 8,
                               errors=4, faults=1, protocol="p")],
        }

    def view(self, **filters):
        return dashboard.view(self.root, [], {"experiment": "exp", **filters})

    def test_pairs_equal_weight_seeds_and_require_shared_checkpoint(self):
        data = self.view(paired=True, baseline="base")
        self.assertEqual(data["horizon"], {"observed": 3, "planned": 3})
        self.assertEqual({item["seed"] for item in data["selected"]}, {8, 9})
        deltas = [row for row in data["deltas"] if row["seed"] is None and row["metric"] == "fixed"]
        self.assertEqual([(row["generation"], row["value"], row["n"]) for row in deltas],
                         [(0, 10, 2), (2, 10, 1), (3, 10, 2)])
        self.assertEqual(deltas[1]["missing_seeds"], [9])
        self.assertTrue(all(row["n"] == 0 for row in data["deltas"] if row["metric"] == "final"))
        self.assertFalse(any(item["run_id"] == "old-attempt" for item in data["selected"]))

    def test_dashboard_keeps_all_seed_traces_when_pairing(self):
        data = self.view(paired=True, baseline="base", include_all_seeds=True, seeds=[8])
        self.assertEqual({item["seed"] for item in data["selected"]}, {8, 9, 10})
        self.assertTrue(any(item["seed"] == 10 for item in data["points"]))
        self.assertFalse(any(row["seed"] == 10 for row in data["deltas"]))

    def test_cohort_attempt_and_win_rate_denominators(self):
        data = self.view(treatments=["base"], seeds=[8, 9], fixed_cohort=True, attempts={"base:8": "old-attempt"})
        rows = [row for row in data["aggregates"] if row["metric"] == "fixed"]
        self.assertEqual([(row["value"], row["seeds"]) for row in rows], [(108, [8])] * 3)
        pooled = next(row for row in data["opponents"] if row["seed"] is None)
        self.assertEqual((pooled["counted"], pooled["errors"], pooled["faults"]), (18, 8, 2))
        self.assertAlmostEqual(pooled["win_rate"], 17 / 18)
        self.assertAlmostEqual(pooled["mean_seed_win_rate"], .95)

    def test_bundle_roundtrip(self):
        filters = {"experiment": "exp", "paired": True, "baseline": "base", "fixed_cohort": True}
        expected = dashboard.view(self.root, [], filters)
        result = dashboard.export(self.root, [], filters)
        path = self.root / result["path"]
        self.assertEqual(path.parent.name, "results")
        for file in ("manifest.json", "points.csv", "aggregates.csv", "deltas.csv", "opponents.csv", "fixed.png"):
            self.assertGreater((path / file).stat().st_size, 0)
        reopened = self.view(bundle=True)
        for key in ("aggregates", "deltas", "opponents"):
            self.assertEqual(reopened[key], expected[key])

    def test_catalog_finds_committed_results_without_source_runs(self):
        dashboard.export(self.root, [], {"experiment": "exp"})
        catalog = dashboard.catalog(self.root, [])
        bundle, = [row for row in catalog["experiments"] if row.get("bundle")]
        self.assertEqual((bundle["id"], bundle["label"], bundle["run_count"]), ("exp", "exp", 5))
        legacy = self.root / "reports" / "experiments" / "old"
        legacy.mkdir(parents=True)
        (legacy / "manifest.json").write_bytes((self.root / "results" / "exp" / "manifest.json").read_bytes())
        with patch.object(dashboard, "discover") as discover:
            published = dashboard.catalog(self.root, [], published_only=True)
        discover.assert_not_called()
        self.assertEqual(published["experiments"], [bundle])

    def test_only_export_loads_all_fixed_opponent_curves(self):
        def evidence(run, *, fixed_opponent=None):
            result = self.metrics(run, fixed_opponent=fixed_opponent)
            result["fixed_opponents"] = ["mayari"]
            if fixed_opponent:
                for point in result["points"]:
                    if point["metric"] == "fixed":
                        point["opponent"] = fixed_opponent
            return result

        def details(run, opponents):
            return [evidence(run, fixed_opponent=opponent) for opponent in opponents]

        with patch.object(dashboard, "read_metrics", side_effect=evidence), patch.object(
            dashboard, "read_fixed_opponents", side_effect=details,
        ) as detail_loader:
            overview = self.view()
            detail_loader.assert_not_called()
            self.assertEqual(overview["fixed_opponents"], ["mayari"])
            dashboard.export(self.root, [], {"experiment": "exp"})
            self.assertEqual(detail_loader.call_count, len(overview["selected"]))

        overview = self.view(bundle=True)
        detail = self.view(bundle=True, fixed_opponent="mayari")
        self.assertEqual({r.get("opponent") for r in overview["points"] if r["metric"] == "fixed"}, {None})
        self.assertEqual({r.get("opponent") for r in detail["points"] if r["metric"] == "fixed"}, {"mayari"})

    def test_unknown_protocol_is_inspectable_without_pooling(self):
        with patch.object(dashboard, "read_metrics", return_value={
            "points": [dict(metric="final", statistic="score", generation=3, value=2)],
            "opponents": [dict(opponent="WorkerRush", wins=1, draws=0, losses=0, errors=1)],
            "issues": [], "protocols": {},
        }):
            data = self.view(paired=True)
        self.assertTrue(data["points"])
        self.assertFalse(data["aggregates"])
        self.assertFalse(data["deltas"])
        self.assertTrue(all(row["seed"] is not None for row in data["opponents"]))
