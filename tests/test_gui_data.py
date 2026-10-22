from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eagle.gui_data import config_choices, inspect_run, list_runs, read_config, save_config, validate_config


class GuiConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "configs").mkdir()

    def test_save_preserves_unknown_nested_fields_and_yaml_text(self):
        text = "# retain my notes\nexperiment_name: gui\ncustom_option:\n  future: [one, two]\n"
        result = save_config(self.root, "configs/nested/new.yml", text)
        self.assertEqual(result["path"], "configs/nested/new.yml")
        self.assertEqual(result["text"], text)
        self.assertEqual(result["payload"]["custom_option"], {"future": ["one", "two"]})
        self.assertEqual(config_choices(self.root), ["configs/nested/new.yml"])
        self.assertEqual(validate_config(self.root, text).experiment_name, "gui")

    def test_invalid_config_never_overwrites_existing_file(self):
        path = self.root / "configs" / "test.yaml"
        path.write_text("{}\n", encoding="utf-8")
        for text in ("[]", "test: [", "generations: 0", "population_size: []", "model: invalid"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                save_config(self.root, "configs/test.yaml", text)
            self.assertEqual(path.read_text(encoding="utf-8"), "{}\n")

    def test_rejects_path_escapes_and_non_yaml(self):
        for path in ("configs/../../outside.yaml", "outside.yaml", "configs/test.json", str(self.root.parent / "outside.yaml")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                save_config(self.root, path, "{}")

    def test_symlink_cannot_escape_configs(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.root / "configs" / "link").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaises(ValueError):
            save_config(self.root, "configs/link/escape.yaml", "{}")

    def test_excludes_and_protects_generated_indices(self):
        (self.root / "configs" / "a.yaml").write_text("{}", encoding="utf-8")
        for text in (
            "schema_version: eagle-experiment-index-v1\nconfigs: {}\n",
            "a.yaml: runs/run_a\n",
        ):
            index = self.root / "configs" / "experiment.yaml"
            index.write_text(text, encoding="utf-8")
            self.assertEqual(config_choices(self.root), ["configs/a.yaml"])
            with self.assertRaises(ValueError):
                read_config(self.root, "configs/experiment.yaml")
            with self.assertRaises(ValueError):
                save_config(self.root, "configs/experiment.yaml", "{}")
            self.assertEqual(index.read_text(encoding="utf-8"), text)

    def test_gui_data_import_does_not_load_experiment_orchestration(self):
        subprocess.run(
            [sys.executable, "-c", "import sys; import eagle.gui_data; assert 'eagle.experiment' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
        )

    def test_save_as_cannot_create_an_index_shaped_config(self):
        with self.assertRaises(ValueError):
            save_config(self.root, "configs/experiment.yaml", "{}")
        self.assertFalse((self.root / "configs" / "experiment.yaml").exists())

    def test_failed_atomic_replace_preserves_original_and_cleans_temp(self):
        target = self.root / "configs" / "test.yaml"
        target.write_text("experiment_name: original\n", encoding="utf-8")
        with patch("eagle.gui_data.os.replace", side_effect=OSError("busy")), self.assertRaises(OSError):
            save_config(self.root, "configs/test.yaml", "experiment_name: changed\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "experiment_name: original\n")
        self.assertEqual(list(target.parent.iterdir()), [target])


class GuiRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runs = Path(self.temporary.name)
        self.run = self.runs / "run_a"
        self.write("manifest.json", {"schema_version": "eagle-run-v2", "status": "running", "latest_generation": 1})

    def write(self, relative, value):
        path = self.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def candidate(self, candidate_id, generation, source=True):
        self.write(f"candidates/{candidate_id}/candidate.json", {
            "candidate_schema_version": "eagle-candidate-v6", "candidate_id": candidate_id, "generation": generation, "status": "evaluated",
            "aggregate_game_performance": 42.0,
        })
        if source:
            path = self.run / "candidates" / candidate_id / "phenotype" / "CandidateAgent.java"
            path.parent.mkdir()
            path.write_text("class CandidateAgent {}", encoding="utf-8")

    def test_population_uses_snapshot_membership_and_preserves_retained_parents(self):
        self.candidate("parent", 0)
        self.candidate("child", 1)
        self.candidate("discarded", 0)
        self.candidate("new", 2)
        self.candidate("unfinished", 2, source=False)
        for generation, identities in ((0, ["parent"]), (1, ["parent", "child"])):
            self.write(f"generations/generation_{generation:04d}.json", {
                "schema_version": "eagle-generation-v3", "generation": generation, "population": [{"candidate_id": identity, "status": "selected"} for identity in identities],
            })
        result = inspect_run(self.run)
        self.assertEqual([row["candidate_id"] for row in result["generations"][0]["population"]], ["parent"])
        self.assertEqual([row["candidate_id"] for row in result["generations"][1]["population"]], ["parent", "child"])
        self.assertEqual(result["generations"][1]["population"][0]["status"], "selected")
        self.assertEqual(result["generations"][1]["population"][0]["score"], 42.0)
        pending = {item["candidate_id"]: item for item in result["pending"]}
        self.assertEqual(set(pending), {"discarded", "new", "unfinished"})
        self.assertTrue(pending["new"]["watchable"])
        self.assertFalse(pending["unfinished"]["watchable"])

    def test_transient_and_incomplete_artifacts_do_not_break_polling(self):
        self.candidate("early", 0)
        self.write("candidates/audit/candidate.json", {"candidate_schema_version": "eagle-candidate-v6", "candidate_id": "audit", "generation": 0, "operator": "code_check"})
        self.write("candidates/future/candidate.json", {"candidate_schema_version": "eagle-candidate-v99", "candidate_id": "future", "generation": 0})
        malformed = self.write("candidates/broken/candidate.json", {})
        malformed.write_text('{"candidate_id":', encoding="utf-8")
        self.write("candidates/mismatch/candidate.json", {"candidate_id": "wrong", "generation": 0})
        self.write("generations/generation_0000.json", {"generation": 0, "population": None})
        self.write("generations/generation_0001_parent_rematerialization.json", {"generation": 1, "population": []})
        result = inspect_run(self.run)
        self.assertEqual(result["generations"], [])
        self.assertEqual([item["candidate_id"] for item in result["pending"]], ["early"])

    def test_runs_only_include_canonical_manifests(self):
        legacy = self.runs / "legacy"
        legacy.mkdir()
        (legacy / "manifest.json").write_text('{"schema_version":"legacy"}', encoding="utf-8")
        broken = self.runs / "broken"
        broken.mkdir()
        (broken / "manifest.json").write_text("{", encoding="utf-8")
        self.assertEqual(list_runs(self.runs), [{"path": str(self.run.resolve()), "name": "run_a", "status": "running", "latest_generation": 1}])
        with self.assertRaises(ValueError):
            inspect_run(legacy)


if __name__ == "__main__":
    unittest.main()
