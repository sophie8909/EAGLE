from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from eagle.analysis.experiment_catalog import SETTINGS_PATH, SETTINGS_SCHEMA, discover
from eagle.experiment_index import EXPERIMENT_INDEX_SCHEMA_VERSION
from eagle.run_artifacts import RUN_SCHEMA_VERSION


class ExperimentCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runs = self.root / "runs"

    def yaml(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    def run_folder(self, name, seed, *, status="complete", generation=50):
        folder = self.runs / name
        self.yaml(folder / "config.yaml", {"random_seed": seed, "generations": 50})
        (folder / "manifest.json").write_text(json.dumps({
            "schema_version": RUN_SCHEMA_VERSION, "run_id": name,
            "status": status, "latest_generation": generation,
        }), encoding="utf-8")
        return folder

    def test_relocated_index_and_archived_attempts_preserve_effective_seeds(self):
        batch = "configs/experiments/lab"
        first = self.run_folder("first", 9, status="interrupted", generation=12)
        self.run_folder("current", 9, status="running", generation=17)
        self.yaml(f"{batch}/condition.yaml", {
            "random_seeds": [8, 9, 10], "runs": 1,
            "framework": {"bundle_path": "unavailable.json"},
        })
        index = self.yaml(f"{batch}/experiment.yaml", {
            "schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION,
            "runs": {"condition.yaml": ["/lab/runs/current", "/lab/runs/missing"]},
        })
        self.yaml(SETTINGS_PATH, {
            "schema_version": SETTINGS_SCHEMA,
            "path_mappings": {"/lab/runs": "runs"},
            "batches": {f"{batch}/experiment.yaml": {
                "experiment": "ablation",
                "treatments": {"condition.yaml": {"id": "new", "label": "New selection"}},
            }},
            "runs": [{"path": str(first), "experiment": "ablation", "treatment": "new",
                      "benchmarks": [{"path": "reports/results.csv", "label": "New selection"}]}],
        })

        before = index.read_bytes()
        catalog = discover(self.root, [self.runs])
        self.assertEqual(index.read_bytes(), before)
        rows = {item["run_id"]: item for item in catalog["runs"]}
        self.assertEqual(set(rows), {"current", "first"})
        self.assertTrue(rows["current"]["indexed"])
        self.assertEqual(rows["current"]["replicate_index"], 0)
        self.assertEqual(rows["current"]["seed"], 9)
        self.assertEqual(rows["current"]["latest_generation"], 17)
        self.assertEqual(rows["first"]["status"], "interrupted")
        self.assertFalse(rows["first"]["indexed"])
        self.assertEqual(rows["first"]["benchmarks"], [{
            "path": str(self.root / "reports/results.csv"), "label": "New selection",
        }])
        self.assertEqual(catalog["treatments"], [{
            "experiment": "ablation", "treatment": "new", "label": "New selection",
            "expected_seeds": [8, 9, 10],
        }])
        self.assertEqual(len(catalog["issues"]), 1)
        self.assertIn("missing", catalog["issues"][0]["source"])
        self.assertIn("(condition.yaml)[1]", catalog["issues"][0]["source"])

    def test_conflicting_batch_claims_need_an_explicit_assignment(self):
        path = self.run_folder("shared", 8)
        self.run_folder("unassigned", 10)
        for batch in ("a", "b"):
            self.yaml(f"configs/experiments/{batch}/condition.yml", {"random_seed": 8})
            self.yaml(f"configs/experiments/{batch}/experiment.yaml", {
                "condition.yml": str(path),
            })
        catalog = discover(self.root, [self.runs])
        self.assertEqual(catalog["runs"], [])
        self.assertTrue(any("Ambiguous run shared" in item["reason"] for item in catalog["issues"]))
        self.assertTrue(any("Unassigned run unassigned" in item["reason"] for item in catalog["issues"]))

        self.yaml(SETTINGS_PATH, {
            "schema_version": SETTINGS_SCHEMA,
            "runs": [{"path": str(path), "experiment": "b", "treatment": "condition"}],
        })
        rows = discover(self.root, [self.runs])["runs"]
        self.assertEqual([(row["experiment"], row["replicate_index"]) for row in rows], [("b", 0)])

    def test_external_only_attempt_has_explicit_identity_and_missing_artifact_flags(self):
        self.yaml("reports/archive.json", {})
        self.yaml(SETTINGS_PATH, {
            "schema_version": SETTINGS_SCHEMA,
            "runs": [{"path": "runs/unavailable", "run_id": "known-run", "seed": 9,
                      "experiment": "archive", "treatment": "baseline",
                      "benchmarks": ["reports/archive.json"]}],
        })

        catalog = discover(self.root, [self.runs])
        row, = catalog["runs"]
        self.assertEqual((row["run_id"], row["seed"], row["status"]), ("known-run", 9, "archived"))
        self.assertEqual(row["availability"], {
            "committed_generation": False, "fixed": True, "final": False,
        })
        self.assertIn("Canonical run artifacts unavailable", catalog["issues"][0]["reason"])

    def test_planned_treatment_without_index(self):
        self.yaml("configs/experiments/planned/baseline.yaml", {
            "random_seed": 8, "runs": 2,
        })
        self.yaml(SETTINGS_PATH, {
            "schema_version": SETTINGS_SCHEMA,
            "batches": {"configs/experiments/planned/experiment.yaml": {}},
        })
        catalog = discover(self.root, [])
        self.assertEqual(catalog["treatments"][0]["expected_seeds"], [8, 9])
        self.assertEqual(catalog["issues"], [])

    def test_nested_gui_result_exposes_comparison_metadata(self):
        run = self.runs / "gpt_version" / "seed_8" / "attempt_0001"
        self.yaml(run / "config.yaml", {
            "experiment_name": "gpt_framework_gpt_seed_local_evolution_50x10_seed8_12",
            "random_seed": 8, "generations": 50, "population_size": 10,
            "strategy_reflection_probability": 1.0,
            "prompt_reflection_probability": 0.0,
            "code_reflection_probability": 0.0,
            "framework": {"bundle_sha256": "same", "gpt_initial_candidates": 0,
                           "initial_genomes": [{"slot": 1}], "evolution_mode": "local"},
            "evaluation": {"mode": "self_play", "self_play_refresh_interval": 5},
        })
        (run / "manifest.json").write_text(json.dumps({
            "schema_version": RUN_SCHEMA_VERSION, "run_id": "attempt_0001",
            "status": "complete", "latest_generation": 50,
        }), encoding="utf-8")
        metadata = discover(self.root, [self.runs])["treatments"][0]["comparison"]
        self.assertIn("1 GPT genome", metadata["initialization"])
        self.assertIn("diversity seats", metadata["survivor_selection"])
        self.assertTrue(metadata["opponent_refresh"].startswith("每 5 代"))


if __name__ == "__main__":
    unittest.main()
