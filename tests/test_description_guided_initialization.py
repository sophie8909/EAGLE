from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tempfile
import unittest

from eagle.artifacts import write_run_config
from eagle.evolution.resume import load_resume_config
from eagle.run_artifacts import freeze_framework_bundle, initialize_run_manifest
from eagle.config import ExperimentConfig
from eagle.evolution.framework_reflection import generate_initial_strategy, initialize_framework_strategies
from eagle.operators.initialization import FRAMEWORK_INITIAL_STRATEGIES, initialize_population
from eagle.operators.framework_coach import framework_initial_selection_prompt, framework_coach_selection_prompt
from eagle.generation.framework_slots import load_framework_bundle


CONFIG = Path("configs/experiments/1104_description_guided/experiment.yaml")


class DescriptionGuidedInitializationTests(unittest.TestCase):
    def test_mock_initialization_and_config(self):
        config = ExperimentConfig.from_file(CONFIG)
        config.validate()
        assert ExperimentConfig.from_mapping(config.to_mapping()).framework_initial_strategy_mode == "llm_plus_authored"
        legacy = replace(config, framework_initial_strategy_mode="authored")
        assert "initial_strategy_mode" not in legacy.to_mapping()["framework"]
        assert ExperimentConfig.from_mapping(legacy.to_mapping()).framework_initial_strategy_mode == "authored"
        assert config.needs_llm_runtime
        assert config.to_mapping()["framework"]["initial_strategy_mode"] == "llm_plus_authored"
        population = initialize_population(config)
        result = initialize_framework_strategies(population=population, config=config, run_dir=Path("unused"), client=None, mock=True)
        assert [p.strategy_description for p in result[1:]] == list(FRAMEWORK_INITIAL_STRATEGIES[1:10])
        assert len({" ".join(p.strategy_description.split()).casefold() for p in result}) == 10
        for invalid in (replace(config, population_size=9), replace(config, framework_gpt_initial_candidates=1),
                        replace(config, framework_initial_genomes=((('x', 1),),))):
            with self.assertRaisesRegex(ValueError, "initial_strategy_mode"):
                invalid.validate()


    def test_generate_retries_and_records(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        config = ExperimentConfig.from_file(CONFIG)
        population = initialize_population(config)
        backend = Mock(model="test")
        backend.generate.side_effect = [json.dumps({"strategy_description": population[1].strategy_description.upper()}),
                                        "{}", json.dumps({"strategy_description": "A distinct scouting plan."})]
        client = Mock(selected_endpoint=SimpleNamespace(base_url="mock://test"))
        client.prompt_backend.return_value = backend
        result = generate_initial_strategy(population=population, config=config, run_dir=tmp_path, client=client)
        assert result == "A distinct scouting plan."
        assert backend.generate.call_count == 3
        first = tmp_path / "initialization/framework_initial_strategy/attempt_001"
        assert json.loads((first / "result.json").read_text())["status"] == "failed"
        assert population[1].strategy_description in (first / "request.txt").read_text(encoding="utf-8")
        assert (first / "response_raw.txt").read_text(encoding="utf-8")
        backend.generate.side_effect = ['{"strategy_description":"x","strategy_description":"y"}', "null", "[]", '{"strategy_description": 3}']
        with self.assertRaisesRegex(ValueError, "Initial strategy generation failed"):
            generate_initial_strategy(population=population, config=config, run_dir=tmp_path / "failure", client=client)
        assert backend.generate.call_count == 7
        backend.generate.side_effect = ["{", '{"strategy_description":"   "}', "null", "[]"]
        with self.assertRaisesRegex(ValueError, "Initial strategy generation failed"):
            generate_initial_strategy(population=population, config=config, run_dir=tmp_path / "malformed", client=client)


    def test_selection_uses_descriptions(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        config = ExperimentConfig.from_file(CONFIG)
        population = initialize_population(config)
        bundle = load_framework_bundle(config.framework_bundle_path)
        genome = population[1].control_genome
        text = "Protect miners and scout early"
        assert text in framework_initial_selection_prompt(bundle, framework_bundle_sha256=config.framework_bundle_sha256, current_control_genome=genome, strategy_description=text)
        assert text in framework_coach_selection_prompt(bundle, framework_bundle_sha256=config.framework_bundle_sha256, evaluated_parent_control_genome=genome, current_child_control_genome=genome, coach_evidence={}, strategy_description=text)
        with patch("eagle.evolution.framework_reflection.generate_initial_strategy", return_value=text), patch("eagle.generation.framework_reflection.select_reflected_genomes", return_value={p.id: p.control_genome for p in population}) as select:
            result = initialize_framework_strategies(population=population, config=config, run_dir=tmp_path, client=object(), mock=False)
        assert result[0].strategy_description == text
        assert [x["strategy_description"] for x in select.call_args.kwargs["population_evidence"]] == [p.strategy_description for p in result]

    def test_resume_fences_initial_mode_and_accepts_legacy(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run_dir = Path(temporary.name) / "run"
        config = freeze_framework_bundle(run_dir, ExperimentConfig.from_file(CONFIG))
        write_run_config(run_dir, config, mock=True)
        initialize_run_manifest(run_dir, config=config)
        assert load_resume_config(run_dir).framework_initial_strategy_mode == "llm_plus_authored"
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["framework_initial_strategy_mode"] = "authored"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "initial strategy mode mismatch"):
            load_resume_config(run_dir)
        legacy_dir = Path(temporary.name) / "legacy"
        legacy = freeze_framework_bundle(legacy_dir, replace(config, framework_initial_strategy_mode="authored"))
        write_run_config(legacy_dir, legacy, mock=True)
        initialize_run_manifest(legacy_dir, config=legacy)
        legacy_manifest = legacy_dir / "manifest.json"
        payload = json.loads(legacy_manifest.read_text(encoding="utf-8"))
        del payload["framework_initial_strategy_mode"]
        legacy_manifest.write_text(json.dumps(payload), encoding="utf-8")
        assert load_resume_config(legacy_dir).framework_initial_strategy_mode == "authored"
