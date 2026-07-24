import json
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from eagle.analysis.errors import (
    error_summary,
    export_error_frame,
    filter_error_frame,
    load_error_frame,
    normalize_failure_category,
    root_cause_groups,
)
from eagle.analysis.objectives import (
    ObjectiveFilters,
    filter_objective_frame,
    generation_statistics,
    load_objective_directions,
    pareto_frame,
    prepare_objective_frame,
)
from eagle.analysis.records import discover_runs, load_candidate, load_candidate_records
from eagle.candidate import Candidate
from eagle.llm_profiles import LLMProfile, load_role_profiles, save_role_profiles
from eagle.prompts import PromptTemplateError, load_prompt_templates, save_prompt_template
from eagle_ui.controllers.prompt_controller import InitialPromptController
from eagle_ui.runtime import DEFAULT_GUI_PORT, GUI_PORT_ENV, resolve_gui_port


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class LLMRoleConfigTests(unittest.TestCase):
    def test_gui_port_defaults_away_from_llm_endpoint_and_allows_override(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_gui_port(), DEFAULT_GUI_PORT)
        with patch.dict(os.environ, {GUI_PORT_ENV: "8090"}, clear=True):
            self.assertEqual(resolve_gui_port(), 8090)
        with patch.dict(os.environ, {GUI_PORT_ENV: "not-a-port"}, clear=True):
            with self.assertRaises(ValueError):
                resolve_gui_port()

    def test_role_config_load_save_round_trip_uses_json_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topology.json"
            path.write_text(json.dumps({
                "version": 1,
                "servers": {"server": {"base_url": "http://127.0.0.1:8080/v1", "model_id": "general-real"}},
                "roles": {role: {"server_id": "server"} for role in ("reflector", "rewriter", "generator")},
            }), encoding="utf-8")
            roles = load_role_profiles(path)
            updated = {
                name: LLMProfile(profile=name, base_url=profile.base_url, model="updated-model", server_profile=profile.server_profile)
                for name, profile in roles.items()
            }
            save_role_profiles(path, updated)
            reloaded = load_role_profiles(path)
            self.assertEqual(reloaded["generator"].model, "updated-model")


class PromptServiceTests(unittest.TestCase):
    def test_template_validation_save_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompts.toml"
            path.write_text((REPOSITORY_ROOT / "config" / "prompt_templates.toml").read_text(encoding="utf-8"), encoding="utf-8")
            templates = load_prompt_templates(path)
            item = templates["strategy_rewrite"]
            with self.assertRaises(PromptTemplateError):
                item.validate("missing every placeholder")
            changed = item.template + "\n\nKeep the result concise."
            save_prompt_template("strategy_rewrite", changed, path=path)
            self.assertEqual(load_prompt_templates(path)["strategy_rewrite"].template, changed)

    def test_initial_preview_uses_candidate_canonical_builder(self):
        controller = InitialPromptController()
        java = (REPOSITORY_ROOT / "eagle" / "java_templates" / "CandidateAgent.java").read_text(encoding="utf-8")
        preview = controller.preview("Build workers first.", "Return complete Java.", java)
        expected = Candidate(
            strategy_prompt="Build workers first.",
            generation_prompt="Return complete Java.",
            previous_code=java,
        ).generation_input(class_name="CandidateAgent")
        self.assertEqual(preview, expected)


class ArtifactAndAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run = self.root / "20260722_120000_000001"
        (self.run / "candidates" / "good").mkdir(parents=True)
        (self.run / "candidates" / "bad" / "compilation").mkdir(parents=True)
        self._write_run()

    def tearDown(self):
        self.temporary.cleanup()

    def _candidate(self, candidate_id, generation, status, objectives, *, failure=None):
        return {
            "id": candidate_id,
            "candidate_id": candidate_id,
            "generation": generation,
            "parent_ids": [],
            "operator": "seed" if generation == 0 else "mutation",
            "mutation_type": None if generation == 0 else "code",
            "status": status,
            "fitness_objectives": objectives,
            "strategy_prompt": f"strategy-{candidate_id}",
            "generation_prompt": "generation",
            "generated_java": "",
            "failure_stage": "compilation" if failure else None,
            "failure_reason": failure,
            "metadata": {"failure_category": "Java compile failure"} if failure else {},
            "code_quality_result": {
                "code_quality_breakdown": {
                    "compilation_score": -1000 if failure else 0,
                    "function_score": 0 if failure else 100,
                    "strategy_alignment_score": 0 if failure else 9,
                }
            },
        }

    def _write_run(self):
        good = self._candidate("good", 0, "evaluated", {"game_performance": 10, "code_quality": 609})
        bad = self._candidate("bad", 1, "failed", {"game_performance": -1000, "code_quality": -1000}, failure="javac failed")
        lines = [
            {"candidate": good, "candidate_result": {"failure_category": None}},
            {"candidate": bad, "candidate_result": {"failure_category": "Java compile failure", "failure_stage": "compilation", "failure_reason": "javac failed"}},
        ]
        (self.run / "results.jsonl").write_text("\n".join(json.dumps(value) for value in lines) + "\n", encoding="utf-8")
        (self.run / "resolved_config.json").write_text(json.dumps({
            "population_size": 2,
            "generation_count": 2,
            "objective_directions": {"game_performance": "maximize", "code_quality": "minimize"},
        }), encoding="utf-8")
        (self.run / "summary.json").write_text("{}", encoding="utf-8")
        (self.run / "candidates" / "good" / "individual.json").write_text(json.dumps(good), encoding="utf-8")
        (self.run / "candidates" / "bad" / "individual.json").write_text(json.dumps(bad), encoding="utf-8")
        (self.run / "candidates" / "bad" / "compilation" / "compilation_result.json").write_text(json.dumps({
            "stderr": "CandidateAgent.java:9: error: cannot find symbol\n"
        }), encoding="utf-8")

    def test_run_discovery_and_candidate_loading_with_missing_optional_artifacts(self):
        runs = discover_runs(self.root)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].candidate_count, 2)
        self.assertEqual(runs[0].failure_count, 1)
        candidate = load_candidate(self.run, "good")
        self.assertEqual(candidate.record.candidate_id, "good")
        self.assertEqual(candidate.raw_llm_response, "")
        self.assertIsNone(candidate.validation)
        self.assertEqual(set(candidate.artifact_paths), {"individual"})

    def test_objective_directions_pareto_and_generation_statistics(self):
        records = load_candidate_records(self.run)
        frame = prepare_objective_frame(records)
        directions = load_objective_directions(self.run)
        self.assertEqual(directions["code_quality"], "minimize")
        front = pareto_frame(frame, ("game_performance", "code_quality"), directions)
        self.assertEqual(set(front["candidate_id"]), {"good", "bad"})
        stats = generation_statistics(frame, "game_performance")
        self.assertEqual(list(stats["generation"]), [0, 1])
        self.assertEqual(int(stats.iloc[1]["failure_count"]), 1)
        filtered = filter_objective_frame(frame, ObjectiveFilters(generation_min=1, operators=("mutation",)))
        self.assertEqual(list(filtered["candidate_id"]), ["bad"])

    def test_failure_normalization_summary_grouping_and_filtered_export(self):
        self.assertEqual(normalize_failure_category("Backend request failure", "request exceeds the available context size"), "Context-size overflow")
        frame = load_error_frame(self.run)
        self.assertEqual(frame.iloc[0]["root_cause"], "cannot find symbol")
        summary = error_summary(frame, total_candidates=2, total_failed=1)
        self.assertEqual(float(summary.iloc[0]["percent_all"]), 50.0)
        groups = root_cause_groups(frame)
        self.assertEqual(int(groups.iloc[0]["count"]), 1)
        filtered = filter_error_frame(frame, generation_min=1, categories=("Java compile failure",))
        csv_path = self.root / "export" / "errors.csv"
        json_path = self.root / "export" / "errors.json"
        export_error_frame(filtered, csv_path, "csv")
        export_error_frame(filtered, json_path, "json")
        self.assertEqual(list(pd.read_csv(csv_path)["candidate_id"]), ["bad"])
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))[0]["candidate_id"], "bad")


if __name__ == "__main__":
    unittest.main()
