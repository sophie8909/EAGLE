from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_framework_slots_artifacts as fixtures

from eagle.artifacts import write_run_config
from eagle.evolution.resume import _resume_search_impl, load_resume_config
from eagle.framework_versions import (
    FRAMEWORK_REFLECTION_VERSION_SCHEMA,
    config_for_population,
    framework_bundle_artifact,
)
from eagle.run_artifacts import freeze_framework_bundle, initialize_run_manifest, load_candidate


class FrameworkVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixtures = fixtures.FrameworkSlotsArtifactTests()
        _, config, _ = self.fixtures.make_source_config(self.root)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.config = replace(
            config, framework_evolution_mode="reflection", evaluation_mode="self_play",
            algorithm="game_performance_semantic_tiebreak",
            semantic_probes_enabled=True,
        )
        self.config = freeze_framework_bundle(self.run_dir, self.config)
        initialize_run_manifest(self.run_dir, config=self.config)
        write_run_config(self.run_dir, self.config, mock=False)

    def version(self, parent: str, *, indent: int = 4) -> str:
        data = json.dumps(fixtures.bundle_payload(), indent=indent).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        directory = self.run_dir / "framework" / "versions" / digest
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "bundle.json").write_bytes(data)
        (directory / "reflection.json").write_text(json.dumps({
            "schema_version": FRAMEWORK_REFLECTION_VERSION_SCHEMA,
            "status": "accepted",
            "parent_bundle_sha256": parent,
            "bundle_sha256": digest,
        }), encoding="utf-8")
        return digest

    def test_candidate_round_trip_keeps_initial_identity_and_version_reference(self) -> None:
        initial_bytes = (self.run_dir / "framework/bundle.json").read_bytes()
        digest = self.version(self.config.framework_bundle_sha256)
        active = replace(self.config, framework_bundle_sha256=digest)
        candidate = self.fixtures.write_seed_candidate(self.run_dir, active)
        restored = load_candidate(self.run_dir, candidate.id)
        self.assertEqual(restored.framework_bundle_sha256, digest)
        payload = json.loads((self.run_dir / "candidates" / candidate.id / "candidate.json").read_text())
        self.assertEqual(payload["artifacts"]["framework_bundle"], f"../../framework/versions/{digest}/bundle.json")
        self.assertEqual((self.run_dir / "framework/bundle.json").read_bytes(), initial_bytes)
        self.assertEqual(json.loads((self.run_dir / "manifest.json").read_text())["framework_bundle_sha256"], self.config.framework_bundle_sha256)
        self.assertEqual(load_resume_config(self.run_dir).framework_bundle_sha256, self.config.framework_bundle_sha256)
        payload["artifacts"]["framework_bundle"] = "../../framework/versions/../bundle.json"
        (self.run_dir / "candidates" / candidate.id / "candidate.json").write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "artifact reference"):
            load_candidate(self.run_dir, candidate.id)

    def test_population_binding_ignores_uncommitted_newer_version_and_rejects_mixing(self) -> None:
        first = self.version(self.config.framework_bundle_sha256)
        second = self.version(first, indent=1)
        candidate = self.fixtures.write_seed_candidate(self.run_dir, replace(self.config, framework_bundle_sha256=first))
        active = config_for_population(self.config, self.run_dir, [candidate])
        self.assertEqual(active.framework_bundle_sha256, first)
        self.assertEqual(active.framework_bundle_path, (self.run_dir / f"framework/versions/{first}/bundle.json").resolve())
        self.assertEqual(framework_bundle_artifact(self.run_dir, second), f"framework/versions/{second}/bundle.json")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            config_for_population(self.config, self.run_dir, [candidate, replace(candidate, framework_bundle_sha256=second)])

    def test_resolver_rejects_tampering_unaccepted_versions_and_unlinked_ancestry(self) -> None:
        digest = self.version(self.config.framework_bundle_sha256)
        directory = self.run_dir / "framework/versions" / digest
        for mutation in (
            {"status": "failed"},
            {"bundle_sha256": "a" * 64},
            {"parent_bundle_sha256": "../outside"},
            {"parent_bundle_sha256": digest},
            {"parent_bundle_sha256": "a" * 64},
        ):
            self.version(self.config.framework_bundle_sha256)
            evidence = json.loads((directory / "reflection.json").read_text())
            evidence.update(mutation)
            (directory / "reflection.json").write_text(json.dumps(evidence))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                framework_bundle_artifact(self.run_dir, digest)
        self.version(self.config.framework_bundle_sha256)
        (directory / "bundle.json").write_bytes((directory / "bundle.json").read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "bundle hash mismatch"):
            framework_bundle_artifact(self.run_dir, digest)
        for invalid in ("../outside", "a" * 63, "A" * 64, None):
            with self.subTest(digest=invalid), self.assertRaises(ValueError):
                framework_bundle_artifact(self.run_dir, invalid)

    def test_non_reflection_run_rejects_version_and_root_tampering(self) -> None:
        digest = self.version(self.config.framework_bundle_sha256)
        manifest_path = self.run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["framework_evolution_mode"] = "local"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "reflection evolution mode"):
            framework_bundle_artifact(self.run_dir, digest)
        initial = self.run_dir / "framework/bundle.json"
        initial.write_bytes(initial.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "bundle hash mismatch"):
            framework_bundle_artifact(self.run_dir, self.config.framework_bundle_sha256)

    def test_option_reflection_accepts_only_the_root_frozen_bundle(self) -> None:
        digest = self.version(self.config.framework_bundle_sha256)
        manifest_path = self.run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["framework_evolution_mode"] = "option_reflection"
        manifest_path.write_text(json.dumps(manifest))
        option_config = replace(self.config, framework_evolution_mode="option_reflection")
        root_candidate = self.fixtures.write_seed_candidate(self.run_dir, option_config)
        active = config_for_population(option_config, self.run_dir, [root_candidate])
        self.assertEqual(active.framework_bundle_sha256, option_config.framework_bundle_sha256)
        with self.assertRaisesRegex(ValueError, "reflection evolution mode"):
            framework_bundle_artifact(self.run_dir, digest)
        with self.assertRaisesRegex(ValueError, "reflection evolution mode"):
            config_for_population(
                option_config,
                self.run_dir,
                [replace(root_candidate, framework_bundle_sha256=digest)],
            )

    def test_resolver_rejects_bundle_schema_and_symlink_escape(self) -> None:
        payload = fixtures.bundle_payload()
        payload["schema_version"] = "unknown-framework-schema"
        data = json.dumps(payload).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        version = self.run_dir / "framework/versions" / digest
        version.mkdir(parents=True)
        (version / "bundle.json").write_bytes(data)
        with self.assertRaises(ValueError):
            framework_bundle_artifact(self.run_dir, digest)
        outside = self.root / "outside"
        outside.mkdir()
        escape_digest = "e" * 64
        link = self.run_dir / "framework/versions" / escape_digest
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlinks unavailable on this platform")
        with self.assertRaisesRegex(ValueError, "escapes the run directory"):
            framework_bundle_artifact(self.run_dir, escape_digest)

    def test_resume_binds_population_before_building_runtime(self) -> None:
        digest = self.version(self.config.framework_bundle_sha256)
        candidate = self.fixtures.write_seed_candidate(self.run_dir, replace(self.config, framework_bundle_sha256=digest))
        snapshot = self.run_dir / "generations/generation_0000.json"
        snapshot.write_text(json.dumps({"stagnation_count": 0}))
        with (
            patch("eagle.evolution.resume.load_resume_population", return_value=(0, [candidate])),
            patch("eagle.evolution.resume.preflight_evaluation_opponents"),
            patch("eagle.evolution.resume._restore_completed_generation"),
            patch("eagle.evolution.resume.ensure_strategy_archive"),
            patch("eagle.evolution.resume.update_strategy_archive"),
            patch("eagle.evolution.resume.load_self_play_snapshot", return_value=None),
            patch("eagle.evolution.resume.build_search_runtime") as runtime,
            patch("eagle.evolution.resume.continue_search") as continue_search,
        ):
            _resume_search_impl(self.config, config_path=None, run_dir=self.run_dir, mock=True)
        self.assertEqual(runtime.call_args.args[0].framework_bundle_sha256, digest)
        self.assertEqual(continue_search.call_args.kwargs["config"].framework_bundle_sha256, digest)


if __name__ == "__main__":
    unittest.main()
