from __future__ import annotations

import hashlib
import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.offspring import plan_offspring
from eagle.evolution.runtime import build_search_runtime
from eagle.generation.framework_slots import load_framework_bundle, validate_genome
from eagle.operators.adaptive import build_reflection_operator_controller
from eagle.operators.initialization import initialize_population


def bundle_payload() -> dict:
    return {
        "schema_version": "eagle-framework-bundle-v1",
        "framework_id": "coach_integration_v1",
        "java_template": Path("eagle/java_templates/CandidateAgent.java").read_text(encoding="utf-8").replace(
            "    private void decide(AgentContext context) {\n",
            "    private void decide(AgentContext context) {\n"
            "        int horizon = {{EAGLE_SLOT:horizon}};\n"
            "        boolean policy = {{EAGLE_SLOT:policy}};\n",
            1,
        ),
        "slots": [
            {"slot_id": "horizon", "kind": "integer", "marker": "{{EAGLE_SLOT:horizon}}", "default": 2, "minimum": 1, "maximum": 3, "step": 1, "choices": [], "purpose": "Bound search."},
            {"slot_id": "policy", "kind": "expression_choice", "marker": "{{EAGLE_SLOT:policy}}", "default": "balanced", "minimum": None, "maximum": None, "step": None, "choices": [{"choice_id": "balanced", "java_expression": "true", "description": "Balanced."}, {"choice_id": "aggressive", "java_expression": "false", "description": "Aggressive."}], "purpose": "Choose profile."},
        ],
        "slot_generation_prompt": "Return every declared slot.",
        "report": {"architecture_summary": "Small test scaffold.", "decision_flow": ["Observe", "Act"], "invariants": ["Fixed Java scaffold."], "slot_rationale": {"horizon": "Bounds search.", "policy": "Selects a profile."}, "assumptions": ["Values stay in domain."], "risks": ["Small domain."]},
    }


class FrameworkCoachIntegrationTests(unittest.TestCase):
    def config(self, root: Path, *, mode: str | None = "llm_coach", **overrides) -> ExperimentConfig:
        bundle = root / "bundle.json"
        bundle.write_text(json.dumps(bundle_payload(), indent=2) + "\n", encoding="utf-8")
        payload = {
            "java_materialization_mode": "framework_slots",
            "framework": {"bundle_path": str(bundle), **({} if mode is None else {"evolution_mode": mode})},
            "candidate_java_mode": "generated_phenotype",
            "parent_evaluation_mode": "reuse_cached",
            "reflection_operator_mode": "static",
            "population_size": 1,
            "random_seed": 23,
            "crossover_rate": 0.0,
            "mutation_rate": 0.0,
            "semantic_probes_enabled": False,
        }
        coach_probability = overrides.pop("framework_coach_offspring_probability", None)
        gpt_initial_candidates = overrides.pop("framework_gpt_initial_candidates", None)
        initial_genomes = overrides.pop("framework_initial_genomes", None)
        payload.update(overrides)
        if coach_probability is not None:
            payload["framework"]["coach_offspring_probability"] = coach_probability
        if gpt_initial_candidates is not None:
            payload["framework"]["gpt_initial_candidates"] = gpt_initial_candidates
        if initial_genomes is not None:
            payload["framework"]["initial_genomes"] = initial_genomes
        config = ExperimentConfig.from_mapping(payload)
        config.validate()
        return config

    def runtime(self, config: ExperimentConfig, root: Path):
        return build_search_runtime(config, mock=True, run_dir=root / "run", candidates_dir=root / "run" / "candidates")

    def test_coach_mode_needs_llm_at_zero_mutation_and_resolves_yaml_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coach = self.config(root)
            local = self.config(root, mode="local")
            default_local = self.config(root, mode=None)
        self.assertTrue(coach.needs_llm_runtime)
        self.assertFalse(local.needs_llm_runtime)
        self.assertEqual(default_local.framework_evolution_mode, "local")
        self.assertFalse(default_local.needs_llm_runtime)
        self.assertEqual(coach.to_mapping()["framework"]["evolution_mode"], "llm_coach")
        self.assertEqual(local.to_mapping()["framework"]["evolution_mode"], "local")

    def test_runtime_keeps_java_generation_mocked_and_registers_only_strategy_coach(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = self.runtime(self.config(root, mutation_rate=0.0), root)
        self.assertEqual(set(runtime.mutations), {"strategy"})
        self.assertEqual(type(runtime.generation_backend).__name__, "MockGenerationBackend")
        self.assertEqual(type(runtime.initial_policy_backend).__name__, "MockFrameworkRoleBackend")

    def test_initial_population_selects_all_valid_slots_with_exact_bundle_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root, population_size=3)
            exact_hash = hashlib.sha256(config.framework_bundle_path.read_bytes()).hexdigest()
            runtime = self.runtime(config, root)
            population = initialize_population(config, policy_backend=runtime.initial_policy_backend, candidates_dir=root / "run" / "candidates", timing_logger=runtime.llm_logger)
            bundle = load_framework_bundle(config.framework_bundle_path, expected_sha256=exact_hash)
        self.assertEqual(len(population), 3)
        for candidate in population:
            self.assertEqual(validate_genome(bundle, candidate.control_genome), candidate.control_genome)
            self.assertEqual(set(candidate.control_genome), set(bundle.slot_ids))
            self.assertEqual(candidate.framework_bundle_sha256, exact_hash)
            self.assertEqual(candidate.slot_parent_ids, {})

    def test_direct_gpt_selects_only_configured_gen0_prefix_and_keeps_offspring_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(
                root,
                mode="local",
                population_size=3,
                framework_gpt_initial_candidates=1,
            )
            runtime = self.runtime(config, root)
            population = initialize_population(
                config,
                policy_backend=runtime.initial_policy_backend,
                candidates_dir=root / "run" / "candidates",
                timing_logger=runtime.llm_logger,
            )

        self.assertFalse(config.needs_llm_runtime)
        self.assertEqual(runtime.mutations, {})
        self.assertEqual(len(population), 3)
        first_selection = population[0].metadata["framework_coach_selection"]
        self.assertEqual(first_selection["provider"], "direct_openai_gpt")
        self.assertEqual(first_selection["model"], config.framework_model)
        self.assertNotIn("framework_coach_selection", population[1].metadata)
        self.assertNotIn("framework_coach_selection", population[2].metadata)
        persisted = population[0].to_json_dict()["metadata"]["framework_coach_selection"]
        self.assertEqual(persisted["provider"], "direct_openai_gpt")

    def test_configured_initial_genomes_seed_exact_local_prefix_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            configured_genome = {"horizon": 3, "policy": "aggressive"}
            config = self.config(
                root,
                mode="local",
                population_size=3,
                framework_initial_genomes=[configured_genome],
            )
            runtime = self.runtime(config, root)
            population = initialize_population(
                config,
                policy_backend=runtime.initial_policy_backend,
                candidates_dir=root / "run" / "candidates",
                timing_logger=runtime.llm_logger,
            )
            reloaded = ExperimentConfig.from_mapping(config.to_mapping())
            reloaded.validate()

        self.assertFalse(config.needs_llm_runtime)
        self.assertEqual(runtime.mutations, {})
        self.assertEqual(reloaded.framework_initial_genomes, config.framework_initial_genomes)
        self.assertEqual(population[0].control_genome, configured_genome)
        self.assertEqual(population[0].metadata["initial_genome_source"], "configured_frozen")
        self.assertEqual(population[0].metadata["initial_genome_config_index"], 0)
        self.assertNotIn("initial_genome_sample_index", population[0].metadata)
        self.assertEqual(population[1].metadata["initial_genome_sample_index"], 1)
        self.assertEqual(population[2].metadata["initial_genome_sample_index"], 2)

    def test_configured_initial_genomes_validate_mode_and_gpt_exclusivity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            genome = [{"horizon": 2, "policy": "balanced"}]
            with self.assertRaisesRegex(ValueError, "initial_genomes.*gpt_initial_candidates"):
                self.config(
                    root,
                    mode="local",
                    framework_gpt_initial_candidates=1,
                    framework_initial_genomes=genome,
                )
            with self.assertRaisesRegex(ValueError, "initial_genomes.*evolution_mode=local"):
                self.config(root, mode="llm_coach", framework_initial_genomes=genome)
            with self.assertRaisesRegex(ValueError, "initial_genomes\\[0\\].*invalid"):
                self.config(
                    root,
                    mode="local",
                    framework_initial_genomes=[{"horizon": 99, "policy": "balanced"}],
                )

    def test_configured_initial_genome_hash_is_manifest_fenced_on_resume(self) -> None:
        from eagle.artifacts import write_run_config
        from eagle.evolution.resume import load_resume_config
        from eagle.run_artifacts import freeze_framework_bundle, initialize_run_manifest

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.config(
                root,
                mode="local",
                framework_initial_genomes=[{"horizon": 2, "policy": "balanced"}],
            )
            run_dir = root / "run"
            run_dir.mkdir()
            frozen = freeze_framework_bundle(run_dir, source)
            initialize_run_manifest(run_dir, config=frozen)
            write_run_config(run_dir, frozen, mock=True)
            self.assertEqual(load_resume_config(run_dir).framework_initial_genome_count, 1)

            manifest_path = run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["framework_initial_genomes_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "initial genome hash"):
                load_resume_config(run_dir)

    def test_gpt_initial_count_round_trips_validates_and_allows_zero_generations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(
                root,
                mode="local",
                population_size=3,
                generations=0,
                framework_gpt_initial_candidates=1,
            )
            reloaded = ExperimentConfig.from_mapping(config.to_mapping())
            reloaded.validate()
            self.assertEqual(reloaded.framework_gpt_initial_candidates, 1)
            self.assertEqual(reloaded.generations, 0)
            for invalid, message in (
                (
                    replace(config, framework_gpt_initial_candidates=4),
                    "gpt_initial_candidates",
                ),
                (
                    replace(config, framework_evolution_mode="llm_coach"),
                    "evolution_mode=local",
                ),
            ):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    invalid.validate()

    def test_direct_gpt_transport_authenticates_and_uses_strict_schema(self) -> None:
        from io import BytesIO
        from eagle.operators.framework_coach import (
            DirectGPTFrameworkSelectionBackend,
            framework_selection_response_schema,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root, mode="local")
            bundle = load_framework_bundle(
                config.framework_bundle_path,
                expected_sha256=config.framework_bundle_sha256,
            )
            schema = framework_selection_response_schema(bundle, config.framework_bundle_sha256)
            key_path = root / "gpt-key"
            key_path.write_text("secret-test-key\n", encoding="utf-8")
            content = json.dumps({
                "schema_version": "eagle-framework-selection-v1",
                "framework_bundle_sha256": config.framework_bundle_sha256,
                "control_genome": {slot.slot_id: slot.default for slot in bundle.slots},
            })
            response = BytesIO(json.dumps({
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            }).encode("utf-8"))
            with patch("eagle.operators.framework_coach.GPT_API_KEY_PATH", key_path), patch(
                "eagle.operators.framework_coach.urllib.request.urlopen",
                return_value=response,
            ) as urlopen:
                backend = DirectGPTFrameworkSelectionBackend(
                    model="gpt-6.1-sol",
                    response_schema=schema,
                )
                self.assertEqual(backend.generate("choose slots"), content)

            request = urlopen.call_args.args[0]
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(request.get_header("Authorization"), "Bearer secret-test-key")
            self.assertEqual(payload["model"], "gpt-6.1-sol")
            self.assertTrue(payload["response_format"]["json_schema"]["strict"])
            self.assertNotIn("temperature", payload)
            self.assertNotIn("seed", payload)

            truncated = BytesIO(json.dumps({
                "choices": [{"finish_reason": "length", "message": {"content": content}}],
            }).encode("utf-8"))
            with patch("eagle.operators.framework_coach.GPT_API_KEY_PATH", key_path), patch(
                "eagle.operators.framework_coach.urllib.request.urlopen",
                return_value=truncated,
            ):
                backend = DirectGPTFrameworkSelectionBackend(
                    model="gpt-6.1-sol",
                    response_schema=schema,
                )
                with self.assertRaisesRegex(RuntimeError, "finish with stop"):
                    backend.generate("choose slots")

    def test_gpt_initial_count_is_manifest_fenced_on_resume(self) -> None:
        from eagle.artifacts import write_run_config
        from eagle.evolution.resume import load_resume_config
        from eagle.run_artifacts import freeze_framework_bundle, initialize_run_manifest

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.config(
                root,
                mode="local",
                population_size=3,
                framework_gpt_initial_candidates=1,
            )
            run_dir = root / "run"
            run_dir.mkdir()
            frozen = freeze_framework_bundle(run_dir, source)
            initialize_run_manifest(run_dir, config=frozen)
            write_run_config(run_dir, frozen, mock=True)
            self.assertEqual(load_resume_config(run_dir).framework_gpt_initial_candidates, 1)

            manifest_path = run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["framework_gpt_initial_candidates"] = 0
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "GPT initial candidate count"):
                load_resume_config(run_dir)

    def test_1030_ablation_configs_load_with_expected_treatments(self) -> None:
        root = Path("configs/experiments/1030_gpt_framework_slot_ablation_seed8_10")
        configs = [
            ExperimentConfig.from_file(root / "01_gpt_framework_gpt_slot_once.yaml"),
            ExperimentConfig.from_file(root / "02_gpt_framework_local_evolution.yaml"),
            ExperimentConfig.from_file(root / "03_gpt_framework_gpt_seed_local_evolution.yaml"),
        ]
        for config in configs:
            config.validate()
        self.assertEqual(configs[0].generations, 0)
        self.assertEqual(configs[0].population_size, 1)
        self.assertEqual(configs[0].framework_gpt_initial_candidates, 1)
        self.assertEqual(configs[0].initial_policy_max_attempts, 1)
        self.assertEqual(configs[1].random_seeds, (8, 9, 10))
        self.assertEqual(configs[1].generations, 100)
        self.assertEqual(configs[1].framework_gpt_initial_candidates, 0)
        self.assertEqual(configs[2].random_seeds, (8, 9, 10))
        self.assertEqual(configs[2].generations, 100)
        self.assertEqual(configs[2].framework_gpt_initial_candidates, 0)
        self.assertEqual(configs[2].framework_initial_genome_count, 1)
        self.assertEqual(
            dict(configs[2].framework_initial_genomes[0])["attack_priority"],
            170,
        )
        self.assertFalse(configs[2].needs_llm_runtime)
        self.assertEqual(
            {config.framework_bundle_sha256 for config in configs},
            {"f674a580f0db088bd3436232d2dd36d071a231c9886f480a7aaed25669203e2b"},
        )

        for random_seed in configs[1].random_seeds:
            local_population = initialize_population(
                replace(configs[1], random_seed=random_seed)
            )
            frozen_gpt_population = initialize_population(
                replace(configs[2], random_seed=random_seed)
            )
            self.assertEqual(
                [candidate.control_genome for candidate in local_population[1:]],
                [candidate.control_genome for candidate in frozen_gpt_population[1:]],
            )
            self.assertEqual(
                frozen_gpt_population[0].control_genome,
                dict(configs[2].framework_initial_genomes[0]),
            )
            self.assertEqual(
                [candidate.id for candidate in local_population],
                [candidate.id for candidate in frozen_gpt_population],
            )

    def test_zero_generation_search_completes_after_gpt_seed_initialization(self) -> None:
        from eagle.evolution.search import run_search

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = replace(
                self.config(
                    root,
                    mode="local",
                    generations=0,
                    framework_gpt_initial_candidates=1,
                ),
                runs_dir=root / "runs",
            )
            result = run_search(config, mock=True, run_id="gpt_gen0_only")
            manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
            generation_one_exists = (
                result.run_dir / "generations" / "generation_0001.json"
            ).exists()

        self.assertEqual(result.completed_generation, 0)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["latest_generation"], 0)
        self.assertFalse(generation_one_exists)

    def test_offspring_selects_strategy_coach_with_evaluated_parent_a_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root, mutation_rate=1.0)
            runtime = self.runtime(config, root)
            bundle = load_framework_bundle(config.framework_bundle_path, expected_sha256=config.framework_bundle_sha256)
            parent = Candidate(
                id="evaluated-parent-a", generation=0, candidate_java_mode="generated_phenotype",
                java_materialization_mode="framework_slots", java_compiler_version=config.java_compiler_version,
                control_genome={"horizon": 2, "policy": "balanced"}, slot_parent_ids={},
                framework_bundle_sha256=config.framework_bundle_sha256,
                game_eval_result={"game_performance": 0.5, "match_results": [
                    {"match_id": "parent-a-win", "performance": 1.0, "winner": 0, "candidate_player": 0, "opponent_id": "easy"},
                    {"match_id": "parent-a-loss", "performance": -1.0, "winner": 1, "candidate_player": 0, "opponent_id": "hard"},
                ]}, fitness_objectives={"game_performance": 0.5}, status="evaluated",
            )
            plans = plan_offspring([parent], config=config, generation=1, rng=random.Random(1), mutations=runtime.mutations, operator_controller=build_reflection_operator_controller(config))
        self.assertEqual(validate_genome(bundle, parent.control_genome), parent.control_genome)
        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual(plan.mutation_name, "strategy")
        self.assertIs(plan.mutation, runtime.mutations["strategy"])
        self.assertEqual(plan.candidate.control_genome, parent.control_genome)
        self.assertIsNone(plan.candidate.mutation_type)
        self.assertNotIn("mutation", plan.candidate.metadata)
        self.assertEqual(plan.candidate.slot_parent_ids, {slot: parent.id for slot in bundle.slot_ids})
        self.assertEqual(plan.candidate.source_candidate_ids, (parent.id,))
        self.assertEqual(plan.mutation_context.candidate.candidate_id, parent.id)
        self.assertEqual(plan.mutation_context.parent_comparison["framework_control_genome"], parent.control_genome)
        self.assertEqual([row["match_id"] for row in plan.mutation_context.per_match_results], ["parent-a-win", "parent-a-loss"])

    def test_configured_coach_offspring_route_is_seeded_and_exclusive_of_traditional_reproduction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root, population_size=40, mutation_rate=1.0,
                                 crossover_rate=1.0, framework_coach_offspring_probability=0.5)
            runtime = self.runtime(config, root)
            parents = [
                Candidate(
                    id=f"parent-{index}", generation=0,
                    candidate_java_mode="generated_phenotype",
                    java_materialization_mode="framework_slots",
                    java_compiler_version=config.java_compiler_version,
                    control_genome={"horizon": 1 + index % 3,
                                    "policy": "balanced" if index % 2 == 0 else "aggressive"},
                    slot_parent_ids={}, framework_bundle_sha256=config.framework_bundle_sha256,
                    game_eval_result={"game_performance": index / 40, "match_results": []},
                    status="evaluated",
                )
                for index in range(2)
            ]
            from eagle.evolution import offspring as offspring_module
            original_crossover = offspring_module.crossover_framework_slots
            original_select = offspring_module.select_parent
            with (
                patch("eagle.evolution.offspring.crossover_framework_slots", wraps=original_crossover) as crossover_spy,
                patch("eagle.evolution.offspring.select_parent", wraps=original_select) as select_spy,
            ):
                first = plan_offspring(
                    parents, config=config, generation=1, rng=random.Random(999),
                    mutations=runtime.mutations,
                    operator_controller=build_reflection_operator_controller(config),
                )
                crossover_calls = crossover_spy.call_count
                select_calls = select_spy.call_count
            second = plan_offspring(
                parents, config=config, generation=1, rng=random.Random(1),
                mutations=runtime.mutations,
                operator_controller=build_reflection_operator_controller(config),
            )
            endpoint_plans = {}
            for probability, mutation_rate in ((0.0, 1.0), (1.0, 0.0)):
                endpoint_config = self.config(
                    root, population_size=4, mutation_rate=mutation_rate,
                    crossover_rate=1.0,
                    framework_coach_offspring_probability=probability,
                )
                endpoint_runtime = self.runtime(endpoint_config, root)
                endpoint_plans[probability] = plan_offspring(
                    parents, config=endpoint_config, generation=1,
                    rng=random.Random(123), mutations=endpoint_runtime.mutations,
                    operator_controller=build_reflection_operator_controller(endpoint_config),
                )

        self.assertEqual(
            [(plan.mutation_name, plan.candidate.control_genome) for plan in first],
            [(plan.mutation_name, plan.candidate.control_genome) for plan in second],
        )
        coach = [plan for plan in first
                 if plan.candidate.metadata.get("framework_reproduction_route") == "coach"]
        traditional = [plan for plan in first
                       if plan.candidate.metadata.get("framework_reproduction_route") == "traditional"]
        self.assertTrue(coach)
        self.assertTrue(traditional)
        self.assertEqual(len(coach) + len(traditional), len(first))
        self.assertEqual(crossover_calls, len(traditional))
        self.assertEqual(select_calls, len(coach) + 2 * len(traditional))
        self.assertTrue(all(
            plan.candidate.metadata["framework_reproduction_route"] == "traditional"
            and plan.candidate.mutation_type == "slot"
            for plan in endpoint_plans[0.0]
        ))
        self.assertTrue(all(
            plan.candidate.metadata["framework_reproduction_route"] == "coach"
            and plan.mutation_name == "strategy"
            for plan in endpoint_plans[1.0]
        ))
        for plan in coach:
            self.assertEqual(plan.mutation_name, "strategy")
            self.assertEqual(len(plan.candidate.parent_ids), 1)
            self.assertIsNotNone(plan.mutation_context)
            self.assertEqual(
                plan.candidate.control_genome,
                plan.mutation_context.parent_comparison["framework_control_genome"],
            )
            self.assertEqual(set(plan.candidate.slot_parent_ids.values()), set(plan.candidate.parent_ids))
            self.assertNotIn("mutation", plan.candidate.metadata)
        for plan in traditional:
            self.assertIsNone(plan.mutation_name)
            self.assertEqual(plan.candidate.mutation_type, "slot")
            self.assertEqual(plan.candidate.operator, "crossover")
            record = plan.candidate.metadata["mutation"]
            self.assertEqual(record["operation"], "framework_slot_mutation")
            self.assertTrue(record["applied"])
            self.assertIn(record["slot_id"], plan.candidate.control_genome)


    def test_invalid_initial_selection_fails_before_compile_integration_or_matches(self) -> None:
        class InvalidSelector:
            def generate(self, prompt: str) -> str:
                return json.dumps({
                    "schema_version": "eagle-framework-selection-v1",
                    "framework_bundle_sha256": "0" * 64,
                    "control_genome": {"horizon": 2, "policy": "balanced"},
                })

        from unittest.mock import patch
        from eagle.evaluation.pipeline import evaluate_population
        from eagle.generation.backend import MockGenerationBackend
        from eagle.opponent_cases import FAILED_OPPONENT_SCORE

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root, initial_policy_max_attempts=1)
            population = initialize_population(config, policy_backend=InvalidSelector(), candidates_dir=root / "run" / "candidates")
            self.assertEqual(population[0].failure_stage, "initialization")
            with (
                patch("eagle.evaluation.decoding.compile_agent_source") as compile_agent,
                patch("eagle.evaluation.pipeline.integrate_microrts_agent") as integrate,
                patch("eagle.evaluation.pipeline.match_module.evaluate_matches") as matches,
            ):
                evaluated = evaluate_population(
                    population, generation=0, config=config,
                    backend=build_search_runtime(config, mock=True, run_dir=root / "run", candidates_dir=root / "run" / "candidates").generation_backend,
                    generated_agents_dir=root / "run" / "generated_agents",
                    classes_dir=root / "run" / "classes",
                    candidates_dir=root / "run" / "candidates", mock=True,
                )
            compile_agent.assert_not_called()
            integrate.assert_not_called()
            matches.assert_not_called()

        candidate = evaluated[0]
        self.assertEqual(candidate.failure_stage, "initialization")
        self.assertTrue(candidate.fitness_objectives)
        self.assertTrue(all(score == FAILED_OPPONENT_SCORE for score in candidate.fitness_objectives.values()))

    def test_zero_mutation_rate_keeps_initial_coach_but_plans_no_strategy_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root, mutation_rate=0.0)
            runtime = self.runtime(config, root)
            parent = Candidate(
                id="parent-zero-mutation", generation=0,
                candidate_java_mode="generated_phenotype",
                java_materialization_mode="framework_slots",
                java_compiler_version=config.java_compiler_version,
                control_genome={"horizon": 2, "policy": "balanced"},
                slot_parent_ids={}, framework_bundle_sha256=config.framework_bundle_sha256,
                game_eval_result={"game_performance": 0.5, "match_results": []}, status="evaluated",
            )
            plans = plan_offspring(
                [parent], config=config, generation=1, rng=random.Random(2),
                mutations=runtime.mutations,
                operator_controller=build_reflection_operator_controller(config),
            )
        self.assertEqual(set(runtime.mutations), {"strategy"})
        self.assertEqual(len(plans), 1)
        self.assertIsNone(plans[0].mutation_name)
        self.assertIsNone(plans[0].mutation)
        self.assertIsNone(plans[0].mutation_context)
        self.assertEqual(plans[0].candidate.control_genome, parent.control_genome)

    def test_resume_fences_coach_mode_and_treats_missing_mode_as_local(self) -> None:
        import yaml
        from eagle.artifacts import write_run_config
        from eagle.evolution.resume import load_resume_config, validate_resume_config
        from eagle.run_artifacts import freeze_framework_bundle, initialize_run_manifest

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.config(root, mode="llm_coach", framework_coach_offspring_probability=0.5)
            coach_run = root / "coach_run"
            coach_run.mkdir()
            frozen_coach = freeze_framework_bundle(coach_run, source)
            initialize_run_manifest(coach_run, config=frozen_coach)
            write_run_config(coach_run, frozen_coach, mock=True)
            manifest = json.loads((coach_run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["framework_evolution_mode"], "llm_coach")
            self.assertEqual(manifest["framework_coach_offspring_probability"], 0.5)
            local_source = self.config(root, mode="local")
            with self.assertRaisesRegex(ValueError, "framework.evolution_mode"):
                validate_resume_config(local_source, frozen_coach)
            changed_coach = self.config(
                root, mode="llm_coach", framework_coach_offspring_probability=0.25
            )
            with self.assertRaisesRegex(ValueError, "coach_offspring_probability"):
                validate_resume_config(changed_coach, frozen_coach)
            config_path = coach_run / "config.yaml"
            persisted_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            persisted_config["framework"]["coach_offspring_probability"] = 0.25
            config_path.write_text(yaml.safe_dump(persisted_config, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Coach offspring probability mismatch"):
                load_resume_config(coach_run)

            local_run = root / "legacy_local_run"
            local_run.mkdir()
            frozen_local = freeze_framework_bundle(local_run, local_source)
            initialize_run_manifest(local_run, config=frozen_local)
            write_run_config(local_run, frozen_local, mock=True)
            manifest_path = local_run / "manifest.json"
            legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            legacy_manifest.pop("framework_evolution_mode")
            legacy_manifest.pop("framework_coach_offspring_probability")
            manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")
            config_path = local_run / "config.yaml"
            legacy_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            legacy_config["framework"].pop("evolution_mode")
            config_path.write_text(yaml.safe_dump(legacy_config, sort_keys=False), encoding="utf-8")
            restored = load_resume_config(local_run)

        self.assertEqual(restored.framework_evolution_mode, "local")

    def test_coach_context_keeps_evaluated_parent_separate_from_crossover_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root, mutation_rate=1.0, crossover_rate=1.0)
            runtime = self.runtime(config, root)
            parents = [
                Candidate(
                    id="parent-a", generation=0, candidate_java_mode="generated_phenotype",
                    java_materialization_mode="framework_slots", java_compiler_version=config.java_compiler_version,
                    control_genome={"horizon": 1, "policy": "balanced"}, slot_parent_ids={},
                    framework_bundle_sha256=config.framework_bundle_sha256,
                    game_eval_result={"game_performance": 0.4, "match_results": [
                        {"match_id": "a-worst", "performance": -0.8, "winner": 1, "candidate_player": 0, "opponent_id": "hard"},
                    ]}, status="evaluated",
                ),
                Candidate(
                    id="parent-b", generation=0, candidate_java_mode="generated_phenotype",
                    java_materialization_mode="framework_slots", java_compiler_version=config.java_compiler_version,
                    control_genome={"horizon": 3, "policy": "aggressive"}, slot_parent_ids={},
                    framework_bundle_sha256=config.framework_bundle_sha256,
                    game_eval_result={"game_performance": 0.8, "match_results": [
                        {"match_id": "b-best", "performance": 0.9, "winner": 0, "candidate_player": 0, "opponent_id": "easy"},
                    ]}, status="evaluated",
                ),
            ]
            with patch("eagle.evolution.offspring.select_parent", side_effect=parents):
                plan = plan_offspring(
                    parents, config=config, generation=1, rng=random.Random(3),
                    mutations=runtime.mutations,
                    operator_controller=build_reflection_operator_controller(config),
                )[0]
            context_parent = next(item for item in parents if item.id == plan.mutation_context.candidate.candidate_id)

        self.assertEqual(plan.mutation_name, "strategy")
        self.assertEqual(plan.mutation_context.parent_comparison["framework_control_genome"], context_parent.control_genome)
        self.assertEqual(plan.candidate.parent_ids, ("parent-a", "parent-b"))
        self.assertLessEqual(set(plan.candidate.slot_parent_ids.values()), {"parent-a", "parent-b"})
        for slot, parent_id in plan.candidate.slot_parent_ids.items():
            source = next(item for item in parents if item.id == parent_id)
            self.assertEqual(plan.candidate.control_genome[slot], source.control_genome[slot])

    def test_one_generation_mock_search_completes_with_framework_coach(self) -> None:
        from eagle.evolution.search import run_search
        from eagle.evolution.resume import resume_search

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(
                root, population_size=1, generations=1, mutation_rate=1.0,
                runs_dir=str(root / "runs"),
            )
            result = run_search(config, mock=True, run_id="coach_mock")
            manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
            coach_results = list((result.run_dir / "candidates").glob("*/mutation/strategy_reflection/coach_result.json"))
            initial_snapshot = next(
                json.loads(path.read_text(encoding="utf-8"))
                for path in (result.run_dir / "candidates").glob("*/candidate.json")
                if json.loads(path.read_text(encoding="utf-8"))["generation"] == 0
            )
            initial_dir = result.run_dir / "candidates" / initial_snapshot["candidate_id"]
            self.assertTrue((initial_dir / initial_snapshot["artifacts"]["initial_framework_selection"]).is_file())
            self.assertIn("reflection_llm", initial_snapshot["timing_summary"]["child_total"]["includes"])
            self.assertIn("framework_coach_selection", initial_snapshot["metadata"])
            self.assertTrue(coach_results)
            child_snapshot = json.loads((coach_results[0].parents[2] / "candidate.json").read_text(encoding="utf-8"))
            self.assertNotIn("generator_strategy_input", child_snapshot["artifacts"])
            self.assertEqual(child_snapshot["metadata"]["mutation"]["reflection_status"], "success")
            self.assertEqual(child_snapshot["timing_summary"]["mutation"]["status"], "success")
            resumed = resume_search(run_dir=result.run_dir, mock=True)
            self.assertEqual(resumed.completed_generation, 1)
            self.assertEqual(
                [candidate.control_genome for candidate in resumed.final_population],
                [candidate.control_genome for candidate in result.final_population],
            )

        self.assertEqual(result.completed_generation, 1)
        self.assertEqual(manifest["framework_evolution_mode"], "llm_coach")

    def test_one_generation_mock_search_runs_configured_50_50_coach_and_traditional_routes(self) -> None:
        from eagle.evolution.search import run_search
        from eagle.evolution.resume import resume_search

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(
                root, population_size=4, generations=1, mutation_rate=1.0,
                framework_coach_offspring_probability=0.5,
                runs_dir=str(root / "runs"),
            )
            result = run_search(config, mock=True, run_id="coach_traditional_mock")
            manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
            generation_one = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (result.run_dir / "candidates").glob("*/candidate.json")
                if json.loads(path.read_text(encoding="utf-8"))["generation"] == 1
            ]
            routes = [candidate["metadata"].get("framework_reproduction_route")
                      for candidate in generation_one]
            coach_results = list(
                (result.run_dir / "candidates").glob("*/mutation/strategy_reflection/coach_result.json")
            )
            self.assertEqual(manifest["framework_coach_offspring_probability"], 0.5)
            self.assertEqual(set(routes), {"coach", "traditional"})
            self.assertEqual(len(generation_one), 4)
            self.assertTrue(coach_results)
            self.assertTrue(all("mutation" in candidate["metadata"] for candidate in generation_one
                                if candidate["metadata"]["framework_reproduction_route"] == "coach"))
            resumed = resume_search(run_dir=result.run_dir, mock=True)
            self.assertEqual(resumed.completed_generation, 1)
            self.assertEqual(
                [candidate.control_genome for candidate in resumed.final_population],
                [candidate.control_genome for candidate in result.final_population],
            )

        self.assertEqual(result.completed_generation, 1)


if __name__ == "__main__":
    unittest.main()
