from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from eagle.artifacts import write_candidate_inputs, write_candidate_snapshot
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.run_artifacts import finalize_run, initialize_run_manifest, record_generation


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fork-eagle-run"


class ForkEagleRunTests(unittest.TestCase):
    def _build_source(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        source.mkdir()
        initialize_run_manifest(source, config=ExperimentConfig.from_mapping({}))
        (source / "config.yaml").write_text(
            "schema_version: experiment-v2\n"
            "experiment_name: source_experiment\n"
            "parent_evaluation_mode: reuse_cached\n",
            encoding="utf-8",
        )
        generation_zero = Candidate(
            id="gen_0000_survivor",
            generation=0,
            strategy_prompt="worker rush policy",
            status="evaluated",
            operator="seed",
        )
        write_candidate_inputs(source / "candidates", generation_zero)
        write_candidate_snapshot(source / "candidates", generation_zero)
        record_generation(source, 0, [generation_zero])

        # A later generation proves that the fork only copies the requested
        # survivor checkpoint, not every candidate in the source run.
        generation_one = Candidate(
            id="gen_0001_later",
            generation=1,
            strategy_prompt="later policy",
            status="evaluated",
            operator="mutation",
        )
        write_candidate_inputs(source / "candidates", generation_one)
        write_candidate_snapshot(source / "candidates", generation_one)
        record_generation(source, 1, [generation_zero, generation_one])
        finalize_run(source, [generation_zero, generation_one], stop_reason=None)

        (source / "timing.jsonl").write_text(
            json.dumps({"event": "generation", "run_id": source.name, "generation": 0})
            + "\n"
            + json.dumps({"event": "generation", "run_id": source.name, "generation": 1})
            + "\n",
            encoding="utf-8",
        )
        return source, generation_zero.id

    def test_gen0_fork_loads_resume_population_and_preserves_audit_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, candidate_id = self._build_source(root)
            destination = root / "fork"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(source),
                    str(destination),
                    "--generation",
                    "0",
                    "--experiment-name",
                    "regenerate_comparison",
                    "--parent-evaluation-mode",
                    "regenerate_same_genotype",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            from eagle.run_artifacts import load_resume_population

            generation, population = load_resume_population(destination)
            self.assertEqual(generation, 0)
            self.assertEqual([candidate.id for candidate in population], [candidate_id])
            self.assertFalse((destination / "candidates" / "gen_0001_later").exists())
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "interrupted")
            self.assertTrue(manifest["resumable"])
            self.assertEqual(manifest["latest_generation"], 0)
            self.assertEqual(manifest["run_id"], destination.name)
            self.assertEqual(manifest["parent_evaluation_mode"], "regenerate_same_genotype")
            config_text = (destination / "config.yaml").read_text(encoding="utf-8")
            self.assertIn("experiment_name: regenerate_comparison", config_text)
            self.assertIn("parent_evaluation_mode: regenerate_same_genotype", config_text)
            timing = [json.loads(line) for line in (destination / "timing.jsonl").read_text().splitlines()]
            self.assertEqual([event["generation"] for event in timing], [0])
            self.assertTrue(all(event["run_id"] == destination.name for event in timing))
            self.assertTrue(all(event["forked_from_run_id"] == source.name for event in timing))
            provenance = json.loads((destination / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["source"]["generation"], 0)
            self.assertEqual(provenance["source"]["run_id"], source.name)
            for directory_name in ("generated_agents", "classes", "archives", "llm_logs", "final_test"):
                self.assertEqual(list((destination / directory_name).iterdir()), [])

    def test_destination_must_be_new_and_source_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = self._build_source(root)
            destination = root / "fork"
            first = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), str(destination), "--generation", "0"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            source_manifest_before = (source / "manifest.json").read_bytes()
            second = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), str(destination), "--generation", "0"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("already exists", second.stderr)
            self.assertEqual((source / "manifest.json").read_bytes(), source_manifest_before)

    def test_gen1_fork_keeps_survivor_born_in_generation_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = self._build_source(root)
            destination = root / "fork-gen1"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), str(destination), "--generation", "1"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            from eagle.run_artifacts import load_resume_population

            generation, population = load_resume_population(destination)
            self.assertEqual(generation, 1)
            self.assertEqual(
                {candidate.id for candidate in population},
                {"gen_0000_survivor", "gen_0001_later"},
            )
            self.assertEqual(
                next(candidate for candidate in population if candidate.id == "gen_0000_survivor").generation,
                0,
            )

    def test_reflection_probability_overrides_are_atomic_and_auditable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = self._build_source(root)
            destination = root / "fork-ablation"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(source),
                    str(destination),
                    "--generation",
                    "0",
                    "--strategy-reflection-probability",
                    "0.0",
                    "--prompt-reflection-probability",
                    "0.5",
                    "--code-reflection-probability",
                    "0.5",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            config = yaml.safe_load((destination / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(config["strategy_reflection_probability"], 0.0)
            self.assertEqual(config["prompt_reflection_probability"], 0.5)
            self.assertEqual(config["code_reflection_probability"], 0.5)
            provenance = json.loads((destination / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(
                provenance["config_overrides"],
                {
                    "experiment_name": None,
                    "parent_evaluation_mode": None,
                    "strategy_reflection_probability": 0.0,
                    "prompt_reflection_probability": 0.5,
                    "code_reflection_probability": 0.5,
                },
            )

            incomplete = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(source),
                    str(root / "fork-incomplete"),
                    "--generation",
                    "0",
                    "--strategy-reflection-probability",
                    "0.0",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(incomplete.returncode, 2)
            self.assertIn("must provide strategy, prompt, and code together", incomplete.stderr)


if __name__ == "__main__":
    unittest.main()
