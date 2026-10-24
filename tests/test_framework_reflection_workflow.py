from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from eagle.candidate import Candidate
from eagle.evaluation.compiler import CompileResult
from eagle.evolution.framework_reflection import (
    initialize_framework_strategies, reflect_population_framework, validate_framework_compilation,
)
from eagle.evolution.runtime import build_search_runtime
from eagle.evolution.search import run_search
from eagle.evolution.resume import resume_search
from eagle.evolution.parent_refresh import build_self_play_fitness_refresh_replicas
from eagle.operators.initialization import initialize_population
from eagle.framework_versions import config_for_population
from eagle.llm import LLMClient
from eagle.generation.framework_slots import load_framework_bundle, validate_framework_bundle
from eagle.run_artifacts import freeze_framework_bundle, initialize_run_manifest


class FrameworkReflectionWorkflowTests(unittest.TestCase):
    def setup_run(self, root):
        from tests.test_framework_slots_integration import FrameworkSlotsIntegrationTests
        config = FrameworkSlotsIntegrationTests()._config(root, evaluation={"mode": "self_play"})
        config = replace(config, framework_evolution_mode="reflection")
        run_dir = root / "run"
        config = freeze_framework_bundle(run_dir, config)
        initialize_run_manifest(run_dir, config=config)
        bundle = load_framework_bundle(config.framework_bundle_path)
        parents = [Candidate(
            id=f"parent_{i}", generation=5, java_materialization_mode="framework_slots",
            framework_bundle_sha256=config.framework_bundle_sha256,
            control_genome={"horizon": i + 1, "aggression": 0.5, "early_return": "never"},
            strategy_description=f"Original strategy {i}: defend resources before attacking.",
            fitness_objectives={"game_performance": float(i)},
        ) for i in range(2)]
        return run_dir, config, bundle, parents

    def redesign(self, bundle):
        payload = bundle.to_json_dict()
        payload["framework_id"] = "redesigned"
        payload["java_template"] = payload["java_template"].replace(
            "{{EAGLE_SLOT:aggression}}", "0.5",
        ).replace("{{EAGLE_SLOT:horizon}}", "{{EAGLE_SLOT:lookahead}}")
        payload["slots"] = [slot for slot in payload["slots"] if slot["slot_id"] != "aggression"]
        payload["slots"][0]["slot_id"] = "lookahead"
        payload["slots"][0]["marker"] = "{{EAGLE_SLOT:lookahead}}"
        payload["slots"][1]["choices"] = [payload["slots"][1]["choices"][1]]
        payload["slots"][1]["default"] = "always"
        payload["report"]["slot_rationale"] = {"lookahead": "New slot", "early_return": "Reduced options"}
        return validate_framework_bundle(payload)

    def coach_genomes(self, parents):
        return {p.id: {"lookahead": 4, "early_return": "always"} for p in parents}

    def revised_strategies(self, parents):
        return {p.id: f"Revised strategy for {p.id}: attack vulnerable harvesters sooner." for p in parents}

    def accept(self, proposed):
        def validated_proposal(**kwargs):
            kwargs["validate_bundle"](proposed)
            return proposed
        return validated_proposal

    def test_accepted_version_migrates_all_parents_and_keeps_original_config(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, config, bundle, parents = self.setup_run(Path(temp))
            original_bytes = config.framework_bundle_path.read_bytes()
            proposed = self.redesign(bundle)
            with patch("eagle.generation.framework_reflection.reflect_framework", side_effect=self.accept(proposed)) as reflect, \
                    patch("eagle.generation.framework_reflection.revise_strategy_descriptions", return_value=self.revised_strategies(parents)) as revise, \
                    patch("eagle.generation.framework_reflection.select_reflected_genomes", return_value=self.coach_genomes(parents)) as coach, \
                    patch("eagle.evolution.framework_reflection.validate_framework_compilation") as compile_check:
                updated, replicas = reflect_population_framework(
                    population=parents, config=config, run_dir=run_dir,
                    generation=6, client=object(), mock=False,
                )
            evidence = reflect.call_args.kwargs["population_evidence"]
            self.assertEqual([item["control_genome"] for item in evidence], [p.control_genome for p in parents])
            self.assertEqual([item["fitness_objectives"] for item in evidence], [p.fitness_objectives for p in parents])
            self.assertEqual(config.framework_bundle_path.read_bytes(), original_bytes)
            self.assertNotEqual(updated.framework_bundle_sha256, config.framework_bundle_sha256)
            self.assertEqual(len(replicas), len(parents))
            coach.assert_called_once()
            revise.assert_called_once()
            self.assertEqual([item["strategy_description"] for item in coach.call_args.kwargs["population_evidence"]],
                             list(self.revised_strategies(parents).values()))
            self.assertEqual(compile_check.call_args.kwargs["genomes"], list(self.coach_genomes(parents).values()))
            for parent, replica in zip(parents, replicas, strict=True):
                self.assertEqual(replica.control_genome, self.coach_genomes(parents)[parent.id])
                self.assertEqual(replica.strategy_description, self.revised_strategies(parents)[parent.id])
                self.assertEqual(replica.parent_ids, (parent.id,))
                self.assertEqual(set(replica.slot_parent_ids), set(replica.control_genome))
                self.assertEqual(replica.status, "pending")
                self.assertEqual(replica.generated_java, "")
                self.assertEqual(replica.fitness_objectives, {})
            restored = config_for_population(config, run_dir, replicas)
            self.assertEqual(restored.framework_bundle_sha256, updated.framework_bundle_sha256)
            # A proposal created during an unfinished generation cannot activate itself.
            self.assertEqual(config_for_population(config, run_dir, parents).framework_bundle_sha256,
                             config.framework_bundle_sha256)

    def test_exhausted_reflection_and_mock_search_retain_previous_state(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, config, _, parents = self.setup_run(Path(temp))
            with patch("eagle.generation.framework_reflection.reflect_framework", return_value=None) as reflect:
                for mock in (False, True):
                    updated, replicas = reflect_population_framework(
                        population=parents, config=config, run_dir=run_dir,
                        generation=6, client=object(), mock=mock,
                    )
                    self.assertIs(updated, config)
                    self.assertIsNone(replicas)
                self.assertEqual(reflect.call_count, 1)

    def test_compilation_checks_nondefault_options_and_passes_exact_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, config, bundle, parents = self.setup_run(root)
            with patch("eagle.evolution.framework_reflection.compile_generated_agent",
                       side_effect=[CompileResult(True, []), CompileResult(False, [], stderr="invalid option")]) as compiler:
                with self.assertRaisesRegex(ValueError, "invalid option"):
                    validate_framework_compilation(bundle, genomes=[p.control_genome for p in parents], config=config,
                                                   artifact_dir=root / "compile", mock=False)
            self.assertEqual(compiler.call_count, 2)
            saved = list((root / "compile").glob("*/compilation.json"))
            self.assertEqual(len(saved), 2)

    def test_reflection_runtime_has_no_candidate_llm_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, config, _, _ = self.setup_run(Path(temp))
            with patch("eagle.evolution.runtime.preflight_llm_endpoint") as preflight:
                runtime = build_search_runtime(config, mock=False, run_dir=run_dir,
                                               candidates_dir=run_dir / "candidates")
            preflight.assert_called_once()
            self.assertEqual(runtime.mutations, {})

    def test_ordinary_refresh_records_direct_slot_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, parents = self.setup_run(Path(temp))
            replicas = build_self_play_fitness_refresh_replicas(parents, generation=6)
            for parent, replica in zip(parents, replicas, strict=True):
                self.assertEqual(replica.control_genome, parent.control_genome)
                self.assertEqual(replica.strategy_description, parent.strategy_description)
                self.assertEqual(replica.slot_parent_ids,
                                 {slot_id: parent.id for slot_id in parent.control_genome})
                self.assertEqual(replica.source_candidate_ids, (parent.id,))
                self.assertIsNone(replica.java_parent_id)

    def test_framework_compiles_with_real_javac(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, config, bundle, parents = self.setup_run(root)
            validate_framework_compilation(self.redesign(bundle), genomes=list(self.coach_genomes(parents).values()), config=config,
                                           artifact_dir=root / "javac", mock=False)

    def test_refresh_barrier_and_interrupted_resume_use_accepted_framework(self):
        from eagle.evolution.generation import run_generation_step
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, config, bundle, parents = self.setup_run(root)
            config = replace(config, runs_dir=root / "runs", generations=7,
                             population_size=2, stagnation_generations=0,
                             semantic_probes_enabled=True)
            proposed = self.redesign(bundle)
            reflection_generations = []

            def reflection_at_barrier(**kwargs):
                reflection_generations.append(kwargs["generation"])
                self.assertEqual(kwargs["generation"], 6)
                kwargs["mock"] = False
                genomes = self.coach_genomes(kwargs["population"])
                with patch("eagle.generation.framework_reflection.select_reflected_genomes", return_value=genomes), \
                        patch("eagle.generation.framework_reflection.revise_strategy_descriptions",
                              return_value=self.revised_strategies(kwargs["population"])), \
                        patch("eagle.evolution.framework_reflection.validate_framework_compilation"):
                    return reflect_population_framework(**kwargs)

            def interrupt_after_reflection(**kwargs):
                if kwargs["generation"] == 7:
                    raise KeyboardInterrupt
                return run_generation_step(**kwargs)

            with redirect_stdout(StringIO()), \
                    patch("eagle.generation.framework_reflection.reflect_framework", side_effect=self.accept(proposed)), \
                    patch("eagle.evolution.generation.reflect_population_framework", side_effect=reflection_at_barrier), \
                    patch("eagle.evolution.loop.run_generation_step", side_effect=interrupt_after_reflection):
                with self.assertRaises(KeyboardInterrupt):
                    run_search(config, run_id="reflection-test", mock=True)
            self.assertEqual(reflection_generations, [6])
            run_dir = config.runs_dir / "reflection-test"
            with redirect_stdout(StringIO()):
                resumed = resume_search(run_dir=run_dir, mock=True)
            self.assertEqual(resumed.completed_generation, 7)
            self.assertEqual({frozenset(p.control_genome) for p in resumed.final_population},
                             {frozenset(("early_return", "lookahead"))})
            self.assertTrue(all(p.framework_bundle_sha256 != config.framework_bundle_sha256
                                for p in resumed.final_population))
            self.assertTrue(all(p.strategy_description.startswith("Revised strategy")
                                for p in resumed.final_population))

    def test_coach_or_selected_genome_compile_failure_rolls_back_whole_transition(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, config, bundle, parents = self.setup_run(Path(temp))
            proposed = self.redesign(bundle)
            for failure_stage in ("strategy", "coach", "compile"):
                backend = SimpleNamespace(model="qwen", generate=Mock(return_value=json.dumps(proposed.to_json_dict())))
                with patch.object(LLMClient, "prompt_backend", return_value=backend), \
                        patch("eagle.generation.framework_reflection.revise_strategy_descriptions",
                              side_effect=ValueError("invalid strategy revision") if failure_stage == "strategy" else None,
                              return_value=self.revised_strategies(parents)), \
                        patch("eagle.generation.framework_reflection.select_reflected_genomes",
                              side_effect=ValueError("illegal Coach slots") if failure_stage == "coach" else None,
                              return_value=self.coach_genomes(parents)), \
                        patch("eagle.evolution.framework_reflection.validate_framework_compilation",
                              side_effect=ValueError("Coach genome compilation failed")):
                    updated, replicas = reflect_population_framework(
                        population=parents, config=config, run_dir=run_dir,
                        generation=6, client=LLMClient("http://localhost:8080", "qwen"), mock=False,
                    )
                self.assertIs(updated, config)
                self.assertIsNone(replicas)
                self.assertEqual(backend.generate.call_count, 4)
                self.assertFalse((run_dir / "framework" / "versions").exists())

    def test_initial_ten_distinct_strategies_include_worker_rush_and_condition_slot_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, config, _, _ = self.setup_run(Path(temp))
            config = replace(config, population_size=10)
            population = initialize_population(config)
            self.assertEqual(len({p.strategy_description for p in population}), 10)
            self.assertIn("WorkerRush reference", population[0].strategy_description)
            self.assertIn("one free Worker", population[0].strategy_description)
            selected = {p.id: {"horizon": 4, "aggression": 1.0, "early_return": "always"} for p in population}
            with patch("eagle.generation.framework_reflection.select_reflected_genomes", return_value=selected) as coach:
                filled = initialize_framework_strategies(population=population, config=config,
                    run_dir=run_dir, client=object(), mock=False)
            self.assertEqual([p.control_genome for p in filled], list(selected.values()))
            evidence = coach.call_args.kwargs["population_evidence"]
            self.assertEqual([p["strategy_description"] for p in evidence],
                             [p.strategy_description for p in population])
            self.assertEqual([p.strategy_description for p in filled], [p.strategy_description for p in population])
            with patch("eagle.operators.initialization.FRAMEWORK_INITIAL_STRATEGIES", ("same strategy",) * 10):
                with self.assertRaisesRegex(ValueError, "must be distinct"):
                    initialize_population(config)

    def test_unchanged_framework_still_updates_strategies_and_slot_values(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, config, bundle, parents = self.setup_run(Path(temp))
            selected = {p.id: {"horizon": 4, "aggression": 1.0, "early_return": "always"} for p in parents}
            with patch("eagle.generation.framework_reflection.reflect_framework", side_effect=self.accept(bundle)), \
                    patch("eagle.generation.framework_reflection.revise_strategy_descriptions", return_value=self.revised_strategies(parents)), \
                    patch("eagle.generation.framework_reflection.select_reflected_genomes", return_value=selected) as coach, \
                    patch("eagle.evolution.framework_reflection.validate_framework_compilation"):
                updated, replicas = reflect_population_framework(population=parents, config=config,
                    run_dir=run_dir, generation=6, client=object(), mock=False)
            self.assertEqual(updated.framework_bundle_sha256, config.framework_bundle_sha256)
            self.assertEqual(coach.call_args.kwargs["framework_bundle_sha256"], config.framework_bundle_sha256)
            self.assertEqual([p.control_genome for p in replicas], list(selected.values()))
            self.assertEqual([p.strategy_description for p in replicas], list(self.revised_strategies(parents).values()))

    def test_initial_selection_exhaustion_fails_instead_of_using_random_slots(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir, config, _, _ = self.setup_run(Path(temp))
            population = initialize_population(config)
            with patch("eagle.generation.framework_reflection.select_reflected_genomes", side_effect=ValueError("invalid slots")) as coach:
                with self.assertRaisesRegex(ValueError, "Initial strategy-guided"):
                    initialize_framework_strategies(population=population, config=config,
                        run_dir=run_dir, client=object(), mock=False)
            self.assertEqual(coach.call_count, 4)


if __name__ == "__main__":
    unittest.main()
