from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from eagle.aos import build_reflection_operator_controller
from eagle.config import ExperimentConfig
from eagle.experiment import ExperimentOrchestrator, resolve_experiment_configs
from eagle.search import SearchResult


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
    ) -> Path:
        run_dir.mkdir(parents=True)
        config = ExperimentConfig.from_file(source_config)
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
                json.dumps({"schema_version": "eagle-final-test-v1"}),
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

    def test_same_runtime_starts_once_reuses_and_stops_once(self):
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
            self.assertEqual(events.count("start:shared.gguf"), 1)
            self.assertEqual(events.count("reuse:shared.gguf"), 2)
            self.assertEqual(events.count("stop:shared.gguf"), 1)
            self.assertEqual(events.count("ea:shared"), 3)

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
                "start:a.gguf", "reuse:a.gguf", "stop:a.gguf",
                "start:b.gguf", "reuse:b.gguf", "stop:b.gguf",
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
            self.assertEqual(index, {
                "a.yaml": str((root / "a").resolve()),
                "b.yaml": str((root / "b").resolve()),
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
            self.assertEqual(index, {"a.yaml": str(created_run.resolve())})

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
            (run_dir / "config.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
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
            self.assertEqual(index, {
                "a.yaml": str(completed.resolve()),
                "b.yaml": str(interrupted.resolve()),
                "c.yaml": str((root / "runs" / "c").resolve()),
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
            self.assertEqual(index, {"a.yaml": str(replacement.resolve())})


if __name__ == "__main__":
    unittest.main()
