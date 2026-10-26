from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from eagle.operators.adaptive import build_reflection_operator_controller
from eagle.config import ExperimentConfig
from eagle.experiment import (
    EXPERIMENT_INDEX_SCHEMA_VERSION, ExperimentOrchestrator,
    _load_experiment_run_index, resolve_experiment_configs,
)
from eagle.evolution.loop import SearchResult


class ExperimentLauncherTests(unittest.TestCase):
    def config(
        self,
        root: Path,
        filename: str,
        *,
        model_name: str,
        model_path: Path,
        port: int = 18080,
        reflection_mode: str = "aos_head2head",
    ) -> Path:
        server = root / "llama-server"
        if not server.is_file():
            server.write_text("#!/bin/sh\n", encoding="utf-8")
            server.chmod(0o755)
        path = root / filename
        path.write_text(yaml.safe_dump({
            "schema_version": "experiment-v2",
            "experiment_name": filename.removesuffix(".yaml"),
            "model": {
                "name": model_name,
                "path": str(model_path),
                "llama_server": str(server),
                "host": "127.0.0.1",
                "port": port,
            },
            "reflection_operator_mode": reflection_mode,
        }), encoding="utf-8")
        return path

    def indexed_run(
        self,
        run_dir: Path,
        source_config: Path,
        *,
        status: str,
        mock: bool,
        final_test_complete: bool = False,
        latest_generation: int | None = 3,
        random_seed: int | None = None,
    ) -> Path:
        run_dir.mkdir(parents=True)
        config = ExperimentConfig.from_file(source_config)
        if random_seed is not None:
            config = replace(config, random_seed=random_seed)
        (run_dir / "config.yaml").write_text(
            yaml.safe_dump(config.to_mapping(mock=mock), sort_keys=False),
            encoding="utf-8",
        )
        (run_dir / "manifest.json").write_text(
            json.dumps({
                "schema_version": "eagle-run-v2",
                "run_id": run_dir.name,
                "status": status,
                "latest_generation": latest_generation,
            }),
            encoding="utf-8",
        )
        if final_test_complete:
            final_dir = run_dir / "final_test"
            final_dir.mkdir()
            (final_dir / "final_test_summary.json").write_text(
                json.dumps({"schema_version": "eagle-final-test-v2"}),
                encoding="utf-8",
            )
        return run_dir

    def orchestrator(
        self,
        events: list[str],
        run_dir: Path,
        *,
        fail_on_ea_call: int | None = None,
        final_status: int = 0,
    ) -> ExperimentOrchestrator:
        class Manager:
            def __init__(self):
                self.runtime = None
                self.current_spec = None
                events.append("manager:init")

            def ensure(self, runtime):
                model = runtime.llm.model_path.name
                if self.current_spec is None:
                    events.append(f"start:{model}")
                elif self.current_spec == runtime.spec:
                    events.append(f"reuse:{model}")
                else:
                    events.append(f"stop:{self.runtime.llm.model_path.name}")
                    events.append(f"start:{model}")
                self.runtime = runtime
                self.current_spec = runtime.spec
                events.append(f"health:{model}")
                return SimpleNamespace(state="healthy", detail="ok")

            def stop_owned(self):
                if self.runtime is not None:
                    events.append(f"stop:{self.runtime.llm.model_path.name}")
                self.current_spec = None

        ea_calls = [0]

        def search(config, **kwargs):
            ea_calls[0] += 1
            events.append(f"ea:{config.model.name}")
            if ea_calls[0] == fail_on_ea_call:
                raise RuntimeError("EA failed")
            return SearchResult(run_dir, [], None)

        def final(_argv):
            events.append(f"final:{run_dir}")
            return final_status

        return ExperimentOrchestrator(
            runtime_factory=Manager,
            search_runner=search,
            final_test_runner=final,
        )

    def test_directory_discovery_is_top_level_sorted_and_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.yml").write_text("experiment_name: b\n", encoding="utf-8")
            (root / "a.yaml").write_text("experiment_name: a\n", encoding="utf-8")
            (root / "ignored.txt").write_text("ignored", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "c.yaml").write_text("experiment_name: c\n", encoding="utf-8")
            self.assertEqual(
                [path.name for path in resolve_experiment_configs(root)],
                ["a.yaml", "b.yml"],
            )

    def test_generated_experiment_index_is_not_treated_as_a_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.yaml").write_text("experiment_name: a\n", encoding="utf-8")
            (root / "experiment.yaml").write_text(
                yaml.safe_dump({"a.yaml": "/tmp/runs/a"}),
                encoding="utf-8",
            )
            self.assertEqual(
                [path.name for path in resolve_experiment_configs(root)],
                ["a.yaml"],
            )
            (root / "experiment.yaml").write_text("{}\n", encoding="utf-8")
            self.assertEqual(
                [path.name for path in resolve_experiment_configs(root)],
                ["a.yaml"],
            )

    def test_single_yaml_runs_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            path = self.config(root, "only.yaml", model_name="one", model_path=model)
            events: list[str] = []
            self.orchestrator(events, root / "run").run(
                config_path=path,
                skip_final_test=True,
            )
            self.assertEqual(events.count("ea:one"), 1)
            self.assertFalse(any(item.startswith("final:") for item in events))
            self.assertEqual(events[-1], "stop:model.gguf")

    def test_direct_config_runs_requested_replicates_with_incremented_seeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            path = self.config(root, "replicated.yaml", model_name="one", model_path=model)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["runs"] = 3
            payload["random_seed"] = 40
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            seeds: list[int] = []

            def search(config, **_kwargs):
                seeds.append(config.random_seed)
                return SearchResult(root / f"run-{len(seeds)}", [], None)

            orchestrator = ExperimentOrchestrator(
                search_runner=search,
                final_test_runner=lambda _argv: 0,
            )
            orchestrator.run(config_path=path, mock=True)

            self.assertEqual(seeds, [40, 41, 42])

    def test_direct_config_repeats_each_explicit_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            path = self.config(root, "explicit-seeds.yaml", model_name="one", model_path=model)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["runs"] = 2
            payload["random_seeds"] = [40, 41, 42]
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            seeds: list[int] = []

            def search(config, **_kwargs):
                seeds.append(config.random_seed)
                return SearchResult(root / f"run-{len(seeds)}", [], None)

            ExperimentOrchestrator(
                search_runner=search,
                final_test_runner=lambda _argv: 0,
            ).run(config_path=path, mock=True)

            self.assertEqual(seeds, [40, 40, 41, 41, 42, 42])

    def test_direct_replicates_restart_runtime_between_seeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            path = self.config(root, "replicated.yaml", model_name="one", model_path=model)
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["runs"] = 3
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            events: list[str] = []

            self.orchestrator(events, root / "run").run(
                config_path=path,
                skip_final_test=True,
            )

            lifecycle = [
                item for item in events
                if item.startswith(("start:", "reuse:", "stop:"))
            ]
            self.assertEqual(
                lifecycle,
                [
                    "start:model.gguf", "stop:model.gguf",
                    "start:model.gguf", "stop:model.gguf",
                    "start:model.gguf", "stop:model.gguf",
                ],
            )

    def test_folder_batch_records_each_replicate_with_the_same_explicit_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.config(root, "a.yaml", model_name="one", model_path=root / "model.gguf")
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload.update(runs=3, random_seeds=[8])
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            seeds = []
            run_dirs = []

            def search(config, **kwargs):
                seeds.append(config.random_seed)
                run_dir = root / "runs" / str(len(seeds))
                run_dirs.append(run_dir.resolve())
                kwargs["on_run_created"](run_dir)
                return SearchResult(run_dir, [], None)

            ExperimentOrchestrator(search_runner=search).run(config_path=root, mock=True)
            self.assertEqual(seeds, [8, 8, 8])
            self.assertEqual(_load_experiment_run_index(root), {"a.yaml": run_dirs})
            self.assertEqual(resolve_experiment_configs(root), [path.resolve()])

    def test_folder_replicates_resume_interruption_and_skip_completed_runs(self):
        for settings, expected_seeds in (
            ({"runs": 3, "random_seed": 40}, [40, 41, 42]),
            ({"runs": 2, "random_seeds": [8, 9]}, [8, 8, 9, 9]),
        ):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = self.config(root, "a.yaml", model_name="one", model_path=root / "model.gguf")
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                payload.update(settings)
                path.write_text(yaml.safe_dump(payload), encoding="utf-8")
                created = []
                resumed = []

                def search(config, **kwargs):
                    run_dir = self.indexed_run(
                        root / "runs" / str(len(created)), path,
                        status="complete" if not created else "interrupted",
                        mock=True, random_seed=config.random_seed,
                    )
                    created.append(config.random_seed)
                    kwargs["on_run_created"](run_dir)
                    if len(created) == 2:
                        raise KeyboardInterrupt
                    (run_dir / "manifest.json").write_text(
                        json.dumps({"schema_version": "eagle-run-v2", "status": "complete", "latest_generation": 3}), encoding="utf-8",
                    )
                    return SearchResult(run_dir, [], None)

                def resume(_config, *, run_dir, **_kwargs):
                    resumed.append(run_dir.name)
                    (run_dir / "manifest.json").write_text(
                        json.dumps({"schema_version": "eagle-run-v2", "status": "complete", "latest_generation": 3}), encoding="utf-8",
                    )
                    return SearchResult(run_dir, [], None, completed_generation=3)

                orchestrator = ExperimentOrchestrator(search_runner=search, resume_runner=resume)
                with self.assertRaises(KeyboardInterrupt):
                    orchestrator.run(config_path=root, mock=True)
                self.assertEqual(len(_load_experiment_run_index(root)["a.yaml"]), 2)
                orchestrator.run(config_path=None, resume_dir=root, mock=True)
                self.assertEqual(created, expected_seeds)
                self.assertEqual(resumed, ["1"])
                self.assertEqual(len(_load_experiment_run_index(root)["a.yaml"]), len(expected_seeds))
                orchestrator.run(config_path=None, resume_dir=root, mock=True)
                self.assertEqual(created, expected_seeds)
                self.assertEqual(resumed, ["1"])

    def test_folder_resume_rejects_changed_seed_or_shortened_schedule_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.config(root, "a.yaml", model_name="one", model_path=root / "model.gguf")
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload.update(runs=3, random_seed=40)
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            run_dirs = [self.indexed_run(
                root / "runs" / str(slot), path, status="complete", mock=True, random_seed=40 + slot,
            ) for slot in range(2)]
            index_path = root / "experiment.yaml"
            original = yaml.safe_dump({"schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION,
                                       "runs": {"a.yaml": [str(folder) for folder in run_dirs]}})
            index_path.write_text(original, encoding="utf-8")
            for change, message in (({"random_seed": 41}, "random_seed"), ({"runs": 1}, "exceeds")):
                path.write_text(yaml.safe_dump({**payload, **change}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    ExperimentOrchestrator().run(config_path=None, resume_dir=root, mock=True)
                self.assertEqual(index_path.read_text(encoding="utf-8"), original)

    def test_run_index_rejects_unknown_schema_and_invalid_entries_without_overwrite(self):
        for payload, message in (
            ({"schema_version": "eagle-experiment-index-v2", "runs": {}}, "Unsupported"),
            ({"schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION, "runs": {"a.yaml": "not-a-list"}}, "Invalid"),
            ({"schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION, "runs": {"a.yaml": []}}, "Invalid"),
            ({"schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION, "runs": {"a.yaml": ["relative/run"]}}, "absolute"),
        ):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                index_path = root / "experiment.yaml"
                original = yaml.safe_dump(payload)
                index_path.write_text(original, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    _load_experiment_run_index(root)
                self.assertEqual(index_path.read_text(encoding="utf-8"), original)

    def test_folder_resume_replaces_only_uncheckpointed_replicate_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.config(root, "a.yaml", model_name="one", model_path=root / "model.gguf")
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload.update(runs=3, random_seed=40)
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            completed = self.indexed_run(root / "runs" / "first", path,
                                         status="complete", mock=True, random_seed=40)
            abandoned = self.indexed_run(root / "runs" / "abandoned", path,
                                         status="interrupted", mock=True, random_seed=41,
                                         latest_generation=None)
            (root / "experiment.yaml").write_text(yaml.safe_dump({
                "schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION,
                "runs": {"a.yaml": [str(completed), str(abandoned)]},
            }), encoding="utf-8")
            seeds = []

            def search(config, **kwargs):
                seeds.append(config.random_seed)
                run_dir = root / "runs" / str(config.random_seed)
                kwargs["on_run_created"](run_dir)
                return SearchResult(run_dir, [], None)

            ExperimentOrchestrator(search_runner=search).run(
                config_path=None, resume_dir=root, mock=True,
            )
            self.assertEqual(seeds, [41, 42])
            self.assertEqual(_load_experiment_run_index(root)["a.yaml"],
                             [completed, root / "runs" / "41", root / "runs" / "42"])
            self.assertTrue((abandoned / "manifest.json").is_file())

    def test_multi_run_folder_resume_retries_only_missing_final_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.config(root, "a.yaml", model_name="one", model_path=root / "model.gguf")
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload.update(runs=3, random_seeds=[8])
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            run_dirs = [self.indexed_run(
                root / "runs" / str(slot), path, status="complete", mock=False,
                random_seed=8, final_test_complete=(slot == 0),
            ) for slot in range(3)]
            (root / "experiment.yaml").write_text(yaml.safe_dump({
                "schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION,
                "runs": {"a.yaml": [str(folder) for folder in run_dirs]},
            }), encoding="utf-8")
            tested = []

            def forbidden(*_args, **_kwargs):
                raise AssertionError("completed search started a new run or runtime")

            def final(argv):
                tested.append(Path(argv[-1]))
                return 0

            ExperimentOrchestrator(
                runtime_factory=forbidden, search_runner=forbidden,
                resume_runner=lambda _config, run_dir, **_kwargs: SearchResult(run_dir, [], None),
                final_test_runner=final,
            ).run(config_path=None, resume_dir=root)
            self.assertEqual(tested, run_dirs[1:])
            self.assertEqual(_load_experiment_run_index(root)["a.yaml"], run_dirs)

    def test_runs_must_be_positive(self):
        config = ExperimentConfig.from_mapping({"runs": 0})
        with self.assertRaisesRegex(ValueError, "runs must be at least 1"):
            config.validate()

    def test_normal_sequence_and_final_test(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            path = self.config(root, "experiment.yaml", model_name="model-a", model_path=model)
            events: list[str] = []
            self.orchestrator(events, root / "run").run(config_path=path)
            self.assertEqual(events, [
                "manager:init", "start:model.gguf", "health:model.gguf",
                "ea:model-a", f"final:{root / 'run'}", "stop:model.gguf",
            ])

    def test_same_runtime_restarts_for_each_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "shared.gguf"
            model.write_bytes(b"model")
            for name in ("a.yaml", "b.yaml", "c.yaml"):
                self.config(root, name, model_name="shared", model_path=model)
            events: list[str] = []
            self.orchestrator(events, root / "run").run(
                config_path=root,
                skip_final_test=True,
            )
            self.assertEqual(events.count("manager:init"), 1)
            self.assertEqual(events.count("start:shared.gguf"), 3)
            self.assertEqual(events.count("reuse:shared.gguf"), 0)
            self.assertEqual(events.count("stop:shared.gguf"), 3)
            self.assertEqual(events.count("ea:shared"), 3)

    def test_distinct_generation_model_does_not_switch_primary_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reflection_model = root / "ministral.gguf"
            generation_model = root / "qwen.gguf"
            reflection_model.write_bytes(b"reflection")
            generation_model.write_bytes(b"generation")
            path = self.config(
                root,
                "dual.yaml",
                model_name="ministral",
                model_path=reflection_model,
            )
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["generation_model"] = {
                **payload["model"],
                "name": "qwen3.5-9b",
                "path": str(generation_model),
                "port": 18081,
            }
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            events: list[str] = []

            self.orchestrator(events, root / "run").run(
                config_path=path,
                skip_final_test=True,
            )

            lifecycle = [
                item for item in events
                if item.startswith(("start:", "reuse:", "stop:"))
            ]
            self.assertEqual(lifecycle, [
                "start:ministral.gguf",
                "stop:ministral.gguf",
            ])

    def test_external_primary_endpoint_does_not_construct_runtime_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.config(
                root,
                "external.yaml",
                model_name="external-model",
                model_path=root / "unused.gguf",
                port=1234,
            )
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            payload["model"].pop("path")
            payload["model"].pop("llama_server")
            payload["model"]["host"] = "llm.example.test"
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            observed = []

            def search(config, **_kwargs):
                observed.append(config.model.base_url)
                return SearchResult(root / "run", [], None)

            ExperimentOrchestrator(
                runtime_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("external endpoint constructed a runtime manager")
                ),
                search_runner=search,
            ).run(config_path=path, skip_final_test=True)

            self.assertEqual(observed, ["http://llm.example.test:1234"])

    def test_managed_runtime_stops_before_external_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            managed_model = root / "managed.gguf"
            managed_model.write_bytes(b"managed")
            self.config(
                root,
                "01_managed.yaml",
                model_name="managed",
                model_path=managed_model,
            )
            external = self.config(
                root,
                "02_external.yaml",
                model_name="external",
                model_path=root / "unused.gguf",
                port=1234,
            )
            payload = yaml.safe_load(external.read_text(encoding="utf-8"))
            payload["model"].pop("path")
            payload["model"].pop("llama_server")
            payload["model"]["host"] = "llm.example.test"
            external.write_text(yaml.safe_dump(payload), encoding="utf-8")
            events: list[str] = []

            self.orchestrator(events, root / "run").run(
                config_path=root,
                skip_final_test=True,
            )

            lifecycle = [
                item for item in events
                if item.startswith(("start:", "reuse:", "stop:"))
            ]
            self.assertEqual(lifecycle, ["start:managed.gguf", "stop:managed.gguf"])
            self.assertEqual(events.count("ea:managed"), 1)
            self.assertEqual(events.count("ea:external"), 1)

    def test_runtime_sequence_a_a_b_b_a(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_a = root / "a.gguf"
            model_b = root / "b.gguf"
            model_a.write_bytes(b"a")
            model_b.write_bytes(b"b")
            self.config(root, "01_a.yaml", model_name="a", model_path=model_a)
            self.config(root, "02_a.yaml", model_name="a", model_path=model_a)
            self.config(root, "03_b.yaml", model_name="b", model_path=model_b)
            self.config(root, "04_b.yaml", model_name="b", model_path=model_b)
            self.config(root, "05_a.yaml", model_name="a", model_path=model_a)
            events: list[str] = []
            self.orchestrator(events, root / "run").run(
                config_path=root,
                skip_final_test=True,
            )
            lifecycle = [
                item for item in events
                if item.startswith(("start:", "reuse:", "stop:"))
            ]
            self.assertEqual(lifecycle, [
                "start:a.gguf", "stop:a.gguf",
                "start:a.gguf", "stop:a.gguf",
                "start:b.gguf", "stop:b.gguf",
                "start:b.gguf", "stop:b.gguf",
                "start:a.gguf", "stop:a.gguf",
            ])

    def test_failure_in_second_config_stops_runtime_and_aborts_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "shared.gguf"
            model.write_bytes(b"model")
            for name in ("a.yaml", "b.yaml", "c.yaml"):
                self.config(root, name, model_name="shared", model_path=model)
            events: list[str] = []
            with self.assertRaisesRegex(RuntimeError, "EA failed"):
                self.orchestrator(events, root / "run", fail_on_ea_call=2).run(
                    config_path=root,
                    skip_final_test=True,
                )
            self.assertEqual(events.count("ea:shared"), 2)
            self.assertEqual(events[-1], "stop:shared.gguf")

    def test_final_test_failure_and_keyboard_interrupt_both_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            path = self.config(root, "a.yaml", model_name="a", model_path=model)
            events: list[str] = []
            with self.assertRaisesRegex(RuntimeError, "Final test failed"):
                self.orchestrator(events, root / "run", final_status=7).run(config_path=path)
            self.assertEqual(events[-1], "stop:model.gguf")

            events.clear()
            orchestrator = self.orchestrator(events, root / "run")

            def interrupted(_config, **_kwargs):
                raise KeyboardInterrupt

            orchestrator.search_runner = interrupted
            with self.assertRaises(KeyboardInterrupt):
                orchestrator.run(config_path=path, skip_final_test=True)
            self.assertEqual(events[-1], "stop:model.gguf")

    def test_mock_batch_never_constructs_runtime_or_runs_final_test(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_model = root / "missing.gguf"
            self.config(root, "b.yaml", model_name="b", model_path=missing_model)
            self.config(root, "a.yaml", model_name="a", model_path=missing_model)
            (root / "experiment.yaml").write_text(
                yaml.safe_dump({"removed.yaml": "/old/run"}),
                encoding="utf-8",
            )
            observed: list[str] = []

            def forbidden_runtime():
                raise AssertionError("mock mode touched runtime or port ownership")

            def search(config, **kwargs):
                observed.append(config.model.name)
                return SearchResult(root / config.model.name, [], None)

            def forbidden_final(_argv):
                raise AssertionError("mock mode ran the real final test")

            with patch(
                "eagle.runtime.processes.port_occupied", return_value=True
            ) as port_check:
                result = ExperimentOrchestrator(
                    runtime_factory=forbidden_runtime,
                    search_runner=search,
                    final_test_runner=forbidden_final,
                ).run(config_path=root, mock=True, skip_final_test=True)
            self.assertEqual(observed, ["a", "b"])
            self.assertEqual(result.run_dir, root / "b")
            port_check.assert_not_called()

            index = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], EXPERIMENT_INDEX_SCHEMA_VERSION)
            self.assertEqual(index["runs"], {
                "a.yaml": [str((root / "a").resolve())],
                "b.yaml": [str((root / "b").resolve())],
            })

    def test_run_index_keeps_created_run_when_search_later_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            self.config(root, "a.yaml", model_name="a", model_path=model)
            created_run = root / "runs" / "partial"

            def failing_search(_config, **kwargs):
                kwargs["on_run_created"](created_run)
                raise RuntimeError("EA failed after run creation")

            orchestrator = self.orchestrator([], root / "unused")
            orchestrator.search_runner = failing_search
            with self.assertRaisesRegex(RuntimeError, "after run creation"):
                orchestrator.run(config_path=root, mock=True, skip_final_test=True)

            index = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8"))
            self.assertEqual(index["runs"], {"a.yaml": [str(created_run.resolve())]})

    def test_existing_experiment_config_is_never_overwritten_by_run_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_model = root / "missing.gguf"
            config_path = self.config(
                root, "experiment.yaml", model_name="only", model_path=missing_model
            )
            original = config_path.read_text(encoding="utf-8")

            def search(_config, **_kwargs):
                return SearchResult(root / "run", [], None)

            ExperimentOrchestrator(search_runner=search).run(
                config_path=root,
                mock=True,
                skip_final_test=True,
            )
            self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_experiment_state_is_fresh_while_runtime_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "shared.gguf"
            model.write_bytes(b"model")
            for name in ("a.yaml", "b.yaml"):
                self.config(
                    root, name, model_name="shared", model_path=model,
                    reflection_mode="aos_opponent",
                )
            controllers = []

            def search(config, **kwargs):
                controllers.append(build_reflection_operator_controller(config))
                return SearchResult(root / f"run-{len(controllers)}", [], None)

            events: list[str] = []
            orchestrator = self.orchestrator(events, root / "unused")
            orchestrator.search_runner = search
            orchestrator.run(config_path=root, skip_final_test=True)
            self.assertEqual(len(controllers), 2)
            self.assertIsNot(controllers[0], controllers[1])
            self.assertEqual(
                controllers[0].updater.state_dict(),
                controllers[1].updater.state_dict(),
            )

    def test_resume_uses_run_local_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            source = self.config(root, "source.yaml", model_name="resume-model", model_path=model)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "config.yaml").write_text(yaml.safe_dump(ExperimentConfig.from_file(source).to_mapping()), encoding="utf-8")
            observed: list[str] = []

            class Manager:
                def __init__(self):
                    self.current_spec = None

                def ensure(self, runtime):
                    self.current_spec = runtime.spec
                    observed.append(runtime.llm.model_path.name)
                    return SimpleNamespace(state="healthy", detail="ok")

                def stop_owned(self):
                    observed.append("stopped")

            def resume(config, **kwargs):
                self.assertIsNone(config)
                observed.append("resumed")
                return SearchResult(run_dir, [], None)

            ExperimentOrchestrator(
                runtime_factory=Manager,
                resume_runner=resume,
            ).run(config_path=None, resume_dir=run_dir, skip_final_test=True)
            self.assertEqual(observed, ["model.gguf", "resumed", "stopped"])

    def test_resume_external_primary_does_not_construct_runtime_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "run"
            run_dir.mkdir()
            config = ExperimentConfig.from_mapping({
                "runs_dir": str(root / "runs"),
                "model": {
                    "name": "external-model",
                    "host": "llm.example.test",
                    "port": 1234,
                },
            })
            (run_dir / "config.yaml").write_text(
                yaml.safe_dump(config.to_mapping()),
                encoding="utf-8",
            )

            ExperimentOrchestrator(
                runtime_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("external endpoint constructed a runtime manager")
                ),
                resume_runner=lambda _config, **_kwargs: SearchResult(
                    run_dir, [], None
                ),
            ).run(config_path=None, resume_dir=run_dir, skip_final_test=True)

    def test_folder_resume_prioritizes_interrupted_run_then_remaining_configs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            configs = {
                name: self.config(root, f"{name}.yaml", model_name=name, model_path=model)
                for name in ("a", "b", "c")
            }
            completed = self.indexed_run(
                root / "runs" / "a",
                configs["a"],
                status="complete",
                mock=True,
            )
            interrupted = self.indexed_run(
                root / "runs" / "b",
                configs["b"],
                status="interrupted",
                mock=True,
            )
            (root / "experiment.yaml").write_text(
                yaml.safe_dump({
                    "a.yaml": str(completed.resolve()),
                    "b.yaml": str(interrupted.resolve()),
                }),
                encoding="utf-8",
            )
            events: list[str] = []

            def resume(config, *, run_dir, **_kwargs):
                self.assertIsNone(config)
                events.append(f"resume:{run_dir.name}")
                return SearchResult(run_dir, [], None, completed_generation=3)

            def search(config, **_kwargs):
                events.append(f"search:{config.model.name}")
                return SearchResult(root / "runs" / config.model.name, [], None)

            result = ExperimentOrchestrator(
                runtime_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("mock folder resume constructed a runtime")
                ),
                search_runner=search,
                resume_runner=resume,
            ).run(
                config_path=None,
                resume_dir=root,
                mock=True,
                skip_final_test=True,
            )

            self.assertEqual(events, ["resume:b", "search:c"])
            self.assertEqual(result.run_dir, root / "runs" / "c")
            index = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], EXPERIMENT_INDEX_SCHEMA_VERSION)
            self.assertEqual(index["runs"], {
                "a.yaml": [str(completed.resolve())],
                "b.yaml": [str(interrupted.resolve())],
                "c.yaml": [str((root / "runs" / "c").resolve())],
            })

    def test_folder_resume_retries_missing_final_test_without_starting_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            config_path = self.config(root, "a.yaml", model_name="a", model_path=model)
            run_dir = self.indexed_run(
                root / "runs" / "a",
                config_path,
                status="complete",
                mock=False,
            )
            (root / "experiment.yaml").write_text(
                yaml.safe_dump({"a.yaml": str(run_dir.resolve())}),
                encoding="utf-8",
            )
            events: list[str] = []

            def resume(_config, **_kwargs):
                events.append("resume")
                return SearchResult(run_dir, [], None, completed_generation=3)

            def final(argv):
                events.append(f"final:{Path(argv[-1]).name}")
                return 0

            ExperimentOrchestrator(
                runtime_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("final-test-only resume started the LLM runtime")
                ),
                resume_runner=resume,
                final_test_runner=final,
            ).run(config_path=None, resume_dir=root)

            self.assertEqual(events, ["resume", "final:a"])

    def test_folder_resume_restarts_indexed_run_without_generation_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.write_bytes(b"model")
            config_path = self.config(root, "a.yaml", model_name="a", model_path=model)
            abandoned = self.indexed_run(
                root / "runs" / "abandoned",
                config_path,
                status="interrupted",
                mock=True,
                latest_generation=None,
            )
            replacement = root / "runs" / "replacement"
            (root / "experiment.yaml").write_text(
                yaml.safe_dump({"a.yaml": str(abandoned.resolve())}),
                encoding="utf-8",
            )

            def search(_config, **_kwargs):
                return SearchResult(replacement, [], None)

            result = ExperimentOrchestrator(
                search_runner=search,
                resume_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("run without generation checkpoint was resumed")
                ),
            ).run(
                config_path=None,
                resume_dir=root,
                mock=True,
                skip_final_test=True,
            )

            self.assertEqual(result.run_dir, replacement)
            index = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8"))
            self.assertEqual(index["runs"], {"a.yaml": [str(replacement.resolve())]})

    def test_folder_resume_reuses_frozen_framework_before_generation_zero(self):
        from eagle.run_artifacts import initialize_run_manifest
        from tests.test_framework_slots_artifacts import bundle_payload

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_bundle = root / "source_bundle.json"
            source_bundle.write_text(json.dumps(bundle_payload()), encoding="utf-8")
            source = ExperimentConfig.from_mapping({
                "schema_version": "experiment-v2",
                "experiment_name": "framework_resume",
                "java_materialization_mode": "framework_slots",
                "candidate_java_mode": "generated_phenotype",
                "parent_evaluation_mode": "reuse_cached",
                "reflection_operator_mode": "static",
                "framework": {"bundle_path": str(source_bundle)},
                "population_size": 2,
                "generations": 1,
                "evaluation": {"mode": "self_play"},
            })
            config_path = root / "a.yaml"
            config_path.write_text(
                yaml.safe_dump(source.to_mapping(), sort_keys=False), encoding="utf-8"
            )

            run_dir = root / "runs" / "framework-checkpoint"
            frozen_bundle = run_dir / "framework" / "bundle.json"
            frozen_bundle.parent.mkdir(parents=True)
            frozen_bundle.write_bytes(source_bundle.read_bytes())
            frozen = replace(source, framework_bundle_path=frozen_bundle.resolve())
            (run_dir / "config.yaml").write_text(
                yaml.safe_dump(frozen.to_mapping(mock=True), sort_keys=False),
                encoding="utf-8",
            )
            initialize_run_manifest(run_dir, config=frozen)
            manifest_path = run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(status="interrupted", latest_generation=None)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "experiment.yaml").write_text(
                yaml.safe_dump({
                    "schema_version": EXPERIMENT_INDEX_SCHEMA_VERSION,
                    "runs": {"a.yaml": [str(run_dir.resolve())]},
                }),
                encoding="utf-8",
            )
            resumed: list[Path] = []

            def resume(_config, *, run_dir, **_kwargs):
                resumed.append(run_dir)
                return SearchResult(run_dir, [], None)

            result = ExperimentOrchestrator(
                search_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("frozen framework checkpoint created a replacement run")
                ),
                resume_runner=resume,
            ).run(
                config_path=None,
                resume_dir=root,
                mock=True,
                skip_final_test=True,
            )

            self.assertEqual(result.run_dir, run_dir)
            self.assertEqual(resumed, [run_dir])
            self.assertEqual(
                _load_experiment_run_index(root)["a.yaml"], [run_dir]
            )


if __name__ == "__main__":
    unittest.main()
