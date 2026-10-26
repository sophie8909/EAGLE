from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from eagle.config import ExperimentConfig
from eagle.evolution.resume import load_resume_config, resume_search, validate_resume_config
from eagle.evolution.runtime import build_search_runtime
from eagle.evolution.search import run_search
from eagle.run_artifacts import FRAMEWORK_BUNDLE_ARTIFACT
from tests.test_framework_slots_artifacts import bundle_payload


class FrameworkStartupTests(unittest.TestCase):
    def test_fixed_bundle_config_skips_bootstrap_but_keeps_coach_runtime(self):
        config = ExperimentConfig.from_mapping({
            "java_materialization_mode": "framework_slots",
            "framework": {
                "bundle_path": "configs/framework_bundles/fixed_worker_combat/bundle.json",
                "evolution_mode": "llm_coach",
            },
            "model": {
                "name": "qwen3_5_9b",
                "additional_endpoints": [{
                    "base_url": "http://192.168.1.136:1234",
                    "model": "qwen/qwen3.5-9b",
                }],
            },
        })

        self.assertEqual(config.execution_mode, "openai")
        self.assertEqual(config.framework_evolution_mode, "llm_coach")
        self.assertIsNotNone(config.framework_bundle_path)
        self.assertIsNone(config.framework_design_brief)
        self.assertTrue(config.needs_llm_runtime)
        self.assertEqual(len(config.model.additional_endpoints), 1)

    def _source_config(self, root: Path, **framework_overrides) -> ExperimentConfig:
        framework = {
            "design_brief": "Build a bounded MicroRTS strategy framework.",
            "model": "openai/gpt-oss-120b",
        }
        framework.update(framework_overrides)
        return replace(
            ExperimentConfig.from_mapping(
                {
                    "java_materialization_mode": "framework_slots",
                    "framework": framework,
                    "candidate_java_mode": "generated_phenotype",
                    "parent_evaluation_mode": "reuse_cached",
                    "reflection_operator_mode": "static",
                    "population_size": 2,
                    "generations": 1,
                    "evaluation": {"mode": "self_play"},
                }
            ),
            runs_dir=root / "runs",
        )

    def _generator_result(self, output: Path) -> SimpleNamespace:
        output.mkdir(parents=True, exist_ok=True)
        bundle_path = output / "bundle.json"
        bundle_path.write_text(json.dumps(bundle_payload()), encoding="utf-8")
        return SimpleNamespace(bundle_path=bundle_path)

    def test_yaml_round_trip_keeps_framework_source_without_frozen_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(root)
            mapping = config.to_mapping()
            self.assertEqual(mapping["framework"]["design_brief"], config.framework_design_brief)
            self.assertEqual(mapping["framework"]["model"], config.framework_model)
            self.assertEqual(mapping["framework"]["evolution_mode"], "local")
            self.assertEqual(config.framework_bootstrap_backend, "groq")
            self.assertNotIn("bundle_path", mapping["framework"])
            self.assertNotIn("bundle_sha256", mapping["framework"])
            path = root / "experiment.yaml"
            path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
            restored = ExperimentConfig.from_file(path)
            self.assertEqual(restored.framework_design_brief, config.framework_design_brief)
            self.assertEqual(restored.framework_model, config.framework_model)
            self.assertIsNone(restored.framework_bundle_path)

    def test_local_bootstrap_backend_routes_to_local_endpoint_without_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(
                root,
                bootstrap_backend="local",
                model="qwen3_5_9b",
            )

            with patch("eagle.generation.groq_framework.generate_framework_bundle") as generate, patch(
                "eagle.evolution.search.preflight_evaluation_opponents"
            ), patch(
                "eagle.evolution.runtime.preflight_llm_endpoint"
            ) as preflight:
                generate.side_effect = lambda output_dir, **kwargs: self._generator_result(Path(output_dir))
                with self.assertRaises(KeyboardInterrupt):
                    run_search(
                        config,
                        mock=False,
                        run_id="local-framework-bootstrap",
                        on_run_created=lambda run_dir: (_ for _ in ()).throw(KeyboardInterrupt),
                    )

            self.assertEqual(generate.call_args.kwargs["provider"], "local")
            preflight.assert_called_once()
            self.assertEqual(generate.call_args.kwargs["api_root"], "http://127.0.0.1:8080/v1")
            self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 12288)
            self.assertFalse(generate.call_args.kwargs["require_api_key"])
            self.assertFalse(generate.call_args.kwargs["require_https"])
            self.assertFalse(generate.call_args.kwargs["json_object_mode"])
            self.assertIsNone(generate.call_args.kwargs["reasoning_effort"])
            self.assertEqual(
                generate.call_args.kwargs["chat_template_kwargs"],
                {"enable_thinking": False},
            )

    def test_mistral_bootstrap_backend_routes_to_mistral_api_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(
                root,
                bootstrap_backend="mistral",
                model="mistral-small-latest",
            )

            with patch("eagle.generation.groq_framework.generate_framework_bundle") as generate, patch(
                "eagle.evolution.search.preflight_evaluation_opponents"
            ):
                generate.side_effect = lambda output_dir, **kwargs: self._generator_result(Path(output_dir))
                with self.assertRaises(KeyboardInterrupt):
                    run_search(
                        config,
                        mock=False,
                        run_id="mistral-framework-bootstrap",
                        on_run_created=lambda on_run_dir: (_ for _ in ()).throw(KeyboardInterrupt),
                    )

            self.assertEqual(generate.call_args.kwargs["provider"], "mistral")
            self.assertEqual(
                generate.call_args.kwargs["api_root"],
                "https://api.mistral.ai/v1",
            )
            self.assertEqual(generate.call_args.kwargs["model"], "mistral-small-latest")
            self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 12288)
            self.assertTrue(generate.call_args.kwargs["require_api_key"])
            self.assertTrue(generate.call_args.kwargs["require_https"])
            self.assertTrue(generate.call_args.kwargs["json_object_mode"])
            self.assertIsNone(generate.call_args.kwargs["reasoning_effort"])

    def test_gpt_bootstrap_backend_routes_to_openai_without_local_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(
                root,
                bootstrap_backend="gpt",
                model="gpt-6.1-sol",
            )

            with patch("eagle.generation.groq_framework.generate_framework_bundle") as generate, patch(
                "eagle.evolution.search.preflight_evaluation_opponents"
            ), patch(
                "eagle.evolution.runtime.preflight_llm_endpoint"
            ) as preflight:
                generate.side_effect = lambda output_dir, **kwargs: self._generator_result(Path(output_dir))
                with self.assertRaises(KeyboardInterrupt):
                    run_search(
                        config,
                        mock=False,
                        run_id="gpt-framework-bootstrap",
                        on_run_created=lambda on_run_dir: (_ for _ in ()).throw(KeyboardInterrupt),
                    )

            self.assertEqual(generate.call_args.kwargs["provider"], "gpt")
            self.assertEqual(generate.call_args.kwargs["api_root"], "https://api.openai.com/v1")
            self.assertEqual(generate.call_args.kwargs["model"], "gpt-6.1-sol")
            self.assertEqual(generate.call_args.kwargs["max_output_tokens"], 32768)
            self.assertTrue(generate.call_args.kwargs["require_api_key"])
            self.assertTrue(generate.call_args.kwargs["require_https"])
            self.assertFalse(generate.call_args.kwargs["json_object_mode"])
            self.assertEqual(generate.call_args.kwargs["reasoning_effort"], "low")
            preflight.assert_not_called()

    def test_gpt_bootstrap_backend_is_accepted_by_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._source_config(
                Path(directory),
                bootstrap_backend="gpt",
                model="gpt-6.1-sol",
            )
            config.validate()
            self.assertEqual(config.framework_bootstrap_backend, "gpt")

    def test_codex_bootstrap_is_primary_and_skips_gpt_api(self):
        from eagle.generation.codex_framework import CodexFrameworkResult

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(
                root,
                bootstrap_backend="codex",
                model="gpt-6.1-sol",
            )

            def codex_generate(output_dir, **kwargs):
                result = self._generator_result(Path(output_dir))
                return CodexFrameworkResult(
                    output_dir=Path(output_dir),
                    bundle_path=result.bundle_path,
                    result_path=Path(output_dir) / "result.json",
                    bundle=bundle_payload(),
                )

            with patch(
                "eagle.generation.codex_framework.generate_codex_framework_bundle",
                side_effect=codex_generate,
            ) as codex, patch(
                "eagle.generation.groq_framework.generate_framework_bundle"
            ) as gpt, patch(
                "eagle.evolution.search.preflight_evaluation_opponents"
            ):
                with self.assertRaises(KeyboardInterrupt):
                    run_search(
                        config,
                        mock=False,
                        run_id="codex-framework-bootstrap",
                        on_run_created=lambda run_dir: (_ for _ in ()).throw(KeyboardInterrupt),
                    )

            codex.assert_called_once()
            self.assertEqual(codex.call_args.kwargs["model"], "gpt-6.1-sol")
            gpt.assert_not_called()
            framework_dir = root / "runs" / "codex-framework-bootstrap" / "framework"
            self.assertTrue((framework_dir / "bundle.json").is_file())
            route = json.loads((framework_dir / "bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(route["selected_provider"], "codex")
            self.assertFalse(route["fallback_used"])

    def test_codex_failure_uses_gpt_api_fallback(self):
        from eagle.generation.codex_framework import CodexFrameworkError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(
                root,
                bootstrap_backend="codex",
                model="gpt-6.1-sol",
            )

            with patch(
                "eagle.generation.codex_framework.generate_codex_framework_bundle",
                side_effect=CodexFrameworkError("codex unavailable"),
            ) as codex, patch(
                "eagle.generation.groq_framework.generate_framework_bundle"
            ) as gpt, patch(
                "eagle.evolution.search.preflight_evaluation_opponents"
            ):
                gpt.side_effect = lambda output_dir, **kwargs: self._generator_result(Path(output_dir))
                with self.assertRaises(KeyboardInterrupt):
                    run_search(
                        config,
                        mock=False,
                        run_id="codex-gpt-fallback",
                        on_run_created=lambda run_dir: (_ for _ in ()).throw(KeyboardInterrupt),
                    )

            codex.assert_called_once()
            gpt.assert_called_once()
            self.assertEqual(gpt.call_args.kwargs["provider"], "gpt")
            self.assertEqual(gpt.call_args.kwargs["api_root"], "https://api.openai.com/v1")
            self.assertEqual(gpt.call_args.kwargs["model"], "gpt-6.1-sol")
            self.assertEqual(gpt.call_args.kwargs["max_output_tokens"], 32768)
            self.assertEqual(gpt.call_args.kwargs["reasoning_effort"], "low")
            framework_dir = root / "runs" / "codex-gpt-fallback" / "framework"
            route = json.loads((framework_dir / "bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(route["selected_provider"], "gpt")
            self.assertTrue(route["fallback_used"])
            self.assertEqual(route["codex_error"], "codex unavailable")

    def test_codex_and_gpt_failure_preserves_both_diagnostics(self):
        from eagle.generation.codex_framework import CodexFrameworkError
        from eagle.generation.groq_framework import GroqFrameworkError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(
                root,
                bootstrap_backend="codex",
                model="gpt-6.1-sol",
            )

            with patch(
                "eagle.generation.codex_framework.generate_codex_framework_bundle",
                side_effect=CodexFrameworkError("codex unavailable"),
            ), patch(
                "eagle.generation.groq_framework.generate_framework_bundle",
                side_effect=GroqFrameworkError("GPT API key is required in api_key/gpt."),
            ), self.assertRaisesRegex(
                GroqFrameworkError,
                "Codex framework bootstrap failed and GPT API fallback also failed",
            ):
                run_search(
                    config,
                    mock=False,
                    run_id="codex-gpt-both-fail",
                )

            framework_dir = root / "runs" / "codex-gpt-both-fail" / "framework"
            route = json.loads((framework_dir / "bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(route["status"], "failed")
            self.assertEqual(route["codex_error"], "codex unavailable")
            self.assertIn("api_key/gpt", route["fallback_error"])
            self.assertFalse((framework_dir / "bundle.json").exists())

    def test_codex_bootstrap_backend_is_accepted_by_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._source_config(
                Path(directory),
                bootstrap_backend="codex",
                model="gpt-6.1-sol",
            )
            config.validate()
            self.assertEqual(config.framework_bootstrap_backend, "codex")

    def test_framework_reflection_uses_local_model_after_codex_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(
                root,
                bootstrap_backend="codex",
                model="gpt-6.1-sol",
                evolution_mode="reflection",
            )
            with patch("eagle.evolution.runtime.preflight_llm_endpoint") as preflight:
                runtime = build_search_runtime(
                    config,
                    mock=False,
                    run_dir=root / "run",
                    candidates_dir=root / "run" / "candidates",
                )

            self.assertEqual(runtime.client.model, config.llm_model)
            self.assertNotEqual(runtime.client.model, config.framework_model)
            preflight.assert_called_once_with(runtime.client)

    def test_resume_validation_accepts_frozen_bundle_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._source_config(root)
            frozen_path = root / "run" / FRAMEWORK_BUNDLE_ARTIFACT
            frozen_path.parent.mkdir(parents=True)
            frozen_path.write_text(json.dumps(bundle_payload()), encoding="utf-8")
            frozen = replace(
                source,
                framework_bundle_path=frozen_path.resolve(),
                framework_bundle_version="eagle-framework-bundle-v1",
                framework_bundle_sha256=hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
            )
            resolved_mapping = frozen.to_mapping()
            resolved = ExperimentConfig.from_mapping(resolved_mapping)
            validate_resume_config(source, resolved)
            for overrides in (
                {"framework_design_brief": "Changed brief."},
                {"framework_model": "another/model"},
                {"framework_bootstrap_backend": "local"},
                {"framework_evolution_mode": "llm_coach"},
                {"framework_design_brief": "Changed brief.", "framework_model": "another/model"},
            ):
                with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "framework"):
                    validate_resume_config(replace(source, **overrides), resolved)

    def test_mocked_generator_runs_during_fresh_startup_before_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(root)
            callback_runs = []

            def stop_after_bootstrap(run_dir: Path) -> None:
                callback_runs.append(run_dir)
                raise KeyboardInterrupt

            with patch("eagle.generation.groq_framework.generate_framework_bundle") as generate, patch(
                "eagle.evolution.search.preflight_evaluation_opponents"
            ):
                generate.side_effect = lambda output_dir, **kwargs: self._generator_result(Path(output_dir))
                with self.assertRaises(KeyboardInterrupt):
                    run_search(
                        config,
                        mock=False,
                        run_id="framework-bootstrap",
                        on_run_created=stop_after_bootstrap,
                    )
            generate.assert_called_once()
            self.assertEqual(generate.call_args.args[0], root / "runs" / "framework-bootstrap" / "framework")
            self.assertEqual(generate.call_args.kwargs["design_brief"], config.framework_design_brief)
            self.assertEqual(generate.call_args.kwargs["model"], config.framework_model)
            self.assertEqual(callback_runs, [root / "runs" / "framework-bootstrap"])
            run_dir = callback_runs[0]
            self.assertTrue((run_dir / FRAMEWORK_BUNDLE_ARTIFACT).is_file())
            self.assertTrue((run_dir / "manifest.json").is_file())
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["startup_checkpoint"], "framework_frozen")
            self.assertTrue(manifest["resumable"])

    def test_resume_from_frozen_framework_checkpoint_replays_generation_zero_without_api(self):
        from tests.test_framework_slots_integration import FrameworkSlotsIntegrationTests

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(root, evolution_mode="reflection")
            created: list[Path] = []
            fixture = FrameworkSlotsIntegrationTests()

            def stop_after_bootstrap(run_dir: Path) -> None:
                created.append(run_dir)
                raise KeyboardInterrupt

            with patch(
                "eagle.generation.groq_framework.generate_framework_bundle"
            ) as generate, patch("eagle.evolution.search.preflight_evaluation_opponents"):
                def generate_bundle(output_dir, **_kwargs):
                    output = Path(output_dir)
                    output.mkdir(parents=True, exist_ok=True)
                    return SimpleNamespace(bundle_path=fixture._write_bundle(output))

                generate.side_effect = generate_bundle
                with self.assertRaises(KeyboardInterrupt):
                    run_search(
                        config,
                        mock=False,
                        run_id="framework-bootstrap-resume",
                        on_run_created=stop_after_bootstrap,
                    )
                run_dir = created[0]
                legacy_manifest_path = run_dir / "manifest.json"
                legacy_manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
                legacy_manifest.pop("startup_checkpoint", None)
                legacy_manifest["resumable"] = False
                legacy_manifest_path.write_text(
                    json.dumps(legacy_manifest), encoding="utf-8"
                )
                partial = run_dir / "candidates" / "gen_0000_partial"
                partial.mkdir(parents=True)
                (partial / "evidence.txt").write_text("partial", encoding="utf-8")
                (run_dir / "timing.jsonl").write_text(
                    '{"event":"partial"}\n', encoding="utf-8"
                )
                stale_initialization = (
                    run_dir
                    / "initialization"
                    / "framework_strategy"
                    / "attempt_001"
                    / "stale.txt"
                )
                stale_initialization.parent.mkdir(parents=True)
                stale_initialization.write_text("stale", encoding="utf-8")

                result = resume_search(run_dir=run_dir, mock=True)

            generate.assert_called_once()
            self.assertEqual(result.run_dir, run_dir)
            self.assertEqual(result.completed_generation, 1)
            self.assertTrue(
                (
                    run_dir
                    / "archives/interrupted_work/startup_attempt_0001"
                    / "candidates/gen_0000_partial/evidence.txt"
                ).is_file()
            )
            self.assertTrue(
                (
                    run_dir
                    / "archives/interrupted_work/startup_attempt_0001/timing.jsonl"
                ).is_file()
            )
            self.assertTrue(
                (
                    run_dir
                    / "archives/interrupted_work/startup_attempt_0001"
                    / "initialization/framework_strategy/attempt_001/stale.txt"
                ).is_file()
            )
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["latest_generation"], 1)

    def test_bootstrap_completes_a_mock_evaluated_run_and_resumes_by_source(self):
        from eagle.evolution.runtime import build_search_runtime as real_build_search_runtime
        from eagle.evolution.search import evaluate_population as real_evaluate_population
        from tests.test_framework_slots_integration import FrameworkSlotsIntegrationTests

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(root)
            fixture = FrameworkSlotsIntegrationTests()

            def generate(output_dir, **kwargs):
                output = Path(output_dir)
                output.mkdir(parents=True, exist_ok=True)
                return SimpleNamespace(bundle_path=fixture._write_bundle(output))

            def build_mock_runtime(config, *, mock, run_dir, candidates_dir):
                return real_build_search_runtime(
                    config, mock=True, run_dir=run_dir, candidates_dir=candidates_dir
                )

            def evaluate_as_mock(*args, **kwargs):
                kwargs["mock"] = True
                return real_evaluate_population(*args, **kwargs)

            with patch("eagle.generation.groq_framework.generate_framework_bundle", side_effect=generate) as generator, patch(
                "eagle.evolution.search.build_search_runtime", side_effect=build_mock_runtime
            ), patch("eagle.evolution.search.evaluate_population", side_effect=evaluate_as_mock), patch(
                "eagle.evolution.generation.evaluate_population", side_effect=evaluate_as_mock
            ):
                result = run_search(config, mock=False, run_id="framework-e2e")
            generator.assert_called_once()
            persisted = load_resume_config(result.run_dir)
            validate_resume_config(config, persisted)
            self.assertEqual(result.completed_generation, 1)
            self.assertTrue(all(candidate.status == "evaluated" for candidate in result.final_population))
            self.assertEqual(json.loads((result.run_dir / "manifest.json").read_text())["status"], "complete")
            self.assertTrue((result.run_dir / FRAMEWORK_BUNDLE_ARTIFACT).is_file())

    def test_failed_bootstrap_retains_manifest_and_pending_config_without_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(root)
            callback_runs = []
            with patch(
                "eagle.generation.groq_framework.generate_framework_bundle",
                side_effect=RuntimeError("bootstrap failed"),
            ), patch("eagle.evolution.search.preflight_evaluation_opponents"):
                with self.assertRaisesRegex(RuntimeError, "bootstrap failed"):
                    run_search(
                        config,
                        mock=False,
                        run_id="failed-framework-bootstrap",
                        on_run_created=callback_runs.append,
                    )
            run_dir = root / "runs" / "failed-framework-bootstrap"
            self.assertEqual(callback_runs, [])
            self.assertEqual(
                json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["status"],
                "failed",
            )
            pending = yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(pending["framework"]["design_brief"], config.framework_design_brief)
            self.assertFalse((run_dir / FRAMEWORK_BUNDLE_ARTIFACT).exists())

    def test_resume_reads_frozen_config_without_generating_framework(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._source_config(root)
            frozen_path = root / "run" / FRAMEWORK_BUNDLE_ARTIFACT
            frozen_path.parent.mkdir(parents=True)
            frozen_path.write_text(json.dumps(bundle_payload()), encoding="utf-8")
            frozen = replace(
                config,
                framework_bundle_path=frozen_path.resolve(),
                framework_bundle_version="eagle-framework-bundle-v1",
                framework_bundle_sha256=hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
            )
            run_dir = root / "run"
            run_dir.mkdir(exist_ok=True)
            mapping = frozen.to_mapping()
            from eagle.run_artifacts import initialize_run_manifest

            initialize_run_manifest(run_dir, config=frozen)
            (run_dir / "config.yaml").write_text(yaml.safe_dump(mapping), encoding="utf-8")
            with patch("eagle.generation.groq_framework.generate_framework_bundle") as generate:
                persisted = load_resume_config(run_dir)
            generate.assert_not_called()
            self.assertEqual(persisted.framework_bundle_path, frozen_path.resolve())
            self.assertEqual(persisted.framework_design_brief, config.framework_design_brief)
            self.assertEqual(persisted.framework_model, config.framework_model)

    def test_invalid_source_and_unresolved_mock_framework_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "design_brief"):
                self._source_config(root, design_brief=" ").validate()
            with self.assertRaisesRegex(ValueError, "model"):
                self._source_config(root, model=" ").validate()
            config = self._source_config(root)
            with patch("eagle.generation.groq_framework.generate_framework_bundle") as generate:
                with self.assertRaisesRegex(ValueError, "provider bootstrap is disabled in mock mode"):
                    run_search(config, mock=True, run_id="mock-framework-bootstrap")
            generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
