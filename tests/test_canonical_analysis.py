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
