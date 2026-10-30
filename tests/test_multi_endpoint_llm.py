from __future__ import annotations

import json
import threading
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from eagle.config import ExperimentConfig
from eagle.evolution.runtime import build_search_runtime, preflight_llm_endpoint
from eagle.evolution.resume import validate_resume_config
from eagle.execution import LLM_WORKERS, current_llm_worker_slot, parallel_map
from eagle.llm import LLMClient, LLMEndpoint


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class MultiEndpointConfigTests(unittest.TestCase):
    @staticmethod
    def _remote_model_payload() -> dict[str, object]:
        return {
            "name": "remote-primary-model",
            "host": "remote.example.test",
            "port": 1234,
            "additional_endpoints": [
                {
                    "base_url": "http://remote-backup.example.test:1235",
                    "model": "remote-backup-model",
                }
            ],
        }

    def test_remote_primary_model_becomes_active_for_all_llm_properties(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "local-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                },
                "use_remote_llm": True,
                "remote_model": self._remote_model_payload(),
            }
        )

        config.validate()

        self.assertEqual(config.active_primary_model.name, "remote-primary-model")
        self.assertEqual(config.llm_base_url, "http://remote.example.test:1234")
        self.assertEqual(config.llm_model, "remote-primary-model")
        self.assertIsNone(config.llm_model_path)
        self.assertIs(config.resolved_generation_model, config.remote_model)
        self.assertIs(config.model_for_phase("reflection"), config.remote_model)
        self.assertIs(config.model_for_phase("generation"), config.remote_model)
        self.assertFalse(config.needs_managed_runtime)

    def test_inactive_remote_definition_round_trips_without_replacing_local_model(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "local-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                },
                "use_remote_llm": False,
                "remote_model": self._remote_model_payload(),
            }
        )

        config.validate()
        restored = ExperimentConfig.from_mapping(config.to_mapping())

        self.assertFalse(restored.use_remote_llm)
        self.assertEqual(restored.remote_model, config.remote_model)
        self.assertEqual(restored.active_primary_model, restored.model)
        self.assertEqual(restored.llm_base_url, "http://127.0.0.1:18080")
        self.assertEqual(restored.llm_model, "local-model")
        self.assertIs(restored.resolved_generation_model, restored.model)

    def test_remote_primary_selection_requires_a_strict_boolean_and_model(self) -> None:
        for value in ("true", 1, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "boolean"):
                ExperimentConfig.from_mapping({"use_remote_llm": value})

        config = ExperimentConfig.from_mapping({"use_remote_llm": True})
        with self.assertRaisesRegex(ValueError, "requires remote_model"):
            config.validate()

    def test_remote_model_cannot_be_managed_by_eagle(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "remote_model": {
                    "name": "incorrectly-managed-remote",
                    "path": "models/remote.gguf",
                    "llama_server": "bin/llama-server",
                }
            }
        )

        with self.assertRaisesRegex(ValueError, "already-running endpoint"):
            config.validate()

    def test_remote_primary_selector_is_resume_fenced(self) -> None:
        persisted = ExperimentConfig.from_mapping(
            {
                "model": {"name": "local-model", "port": 18080},
                "use_remote_llm": False,
                "remote_model": self._remote_model_payload(),
            }
        )
        requested = replace(persisted, use_remote_llm=True)

        with self.assertRaisesRegex(ValueError, "use_remote_llm"):
            validate_resume_config(requested, persisted)

    def test_additional_endpoint_parses_and_round_trips_in_order(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "local-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                    "additional_endpoints": [
                        {
                            "base_url": "http://192.168.1.136:1234",
                            "model": "remote-model",
                        }
                    ],
                }
            }
        )

        self.assertEqual(
            config.model.additional_endpoints,
            (
                LLMEndpoint(
                    base_url="http://192.168.1.136:1234",
                    model="remote-model",
                ),
            ),
        )
        self.assertEqual(
            config.to_mapping()["model"]["additional_endpoints"],
            [
                {
                    "base_url": "http://192.168.1.136:1234",
                    "model": "remote-model",
                }
            ],
        )

    def test_legacy_single_endpoint_config_remains_valid(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "local-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                }
            }
        )

        self.assertEqual(config.model.additional_endpoints, ())
        self.assertNotIn("additional_endpoints", config.to_mapping()["model"])

    def test_additional_endpoint_rejects_invalid_url(self) -> None:
        for base_url in ("not-an-http-url", "http://secret@remote.example:1234"):
            with self.subTest(base_url=base_url), self.assertRaises(ValueError):
                ExperimentConfig.from_mapping(
                    {
                        "model": {
                            "name": "local-model",
                            "additional_endpoints": [
                                {"base_url": base_url, "model": "remote-model"}
                            ],
                        }
                    }
                )

    def test_endpoint_count_cannot_exceed_llm_worker_count(self) -> None:
        self.assertEqual(LLM_WORKERS, 2)
        with self.assertRaises(ValueError):
            ExperimentConfig.from_mapping(
                {
                    "model": {
                        "name": "local-model",
                        "additional_endpoints": [
                            {
                                "base_url": "http://192.168.1.136:1234",
                                "model": "remote-a",
                            },
                            {
                                "base_url": "http://192.168.1.137:1234",
                                "model": "remote-b",
                            },
                        ],
                    }
                }
            )


class MultiEndpointExecutionTests(unittest.TestCase):
    def test_active_remote_model_routes_both_search_clients_to_remote_endpoints(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "local-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                },
                "use_remote_llm": True,
                "remote_model": MultiEndpointConfigTests._remote_model_payload(),
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = build_search_runtime(
                config,
                mock=True,
                run_dir=root,
                candidates_dir=root / "candidates",
            )

        expected = (
            LLMEndpoint("http://remote.example.test:1234", "remote-primary-model"),
            LLMEndpoint(
                "http://remote-backup.example.test:1235",
                "remote-backup-model",
            ),
        )
        self.assertEqual(runtime.client.endpoints, expected)
        self.assertEqual(runtime.generation_client.endpoints, expected)

    def test_parallel_map_assigns_a_stable_slot_from_input_order(self) -> None:
        barrier = threading.Barrier(LLM_WORKERS, timeout=3)

        def observe(index: int) -> tuple[int, int]:
            if index < LLM_WORKERS:
                barrier.wait()
            return index, current_llm_worker_slot()

        observed = parallel_map(observe, range(6))

        self.assertEqual(
            observed,
            [(index, index % LLM_WORKERS) for index in range(6)],
        )

    def test_shared_backends_select_endpoint_and_model_from_worker_slot(self) -> None:
        client = LLMClient(
            "http://127.0.0.1:18080",
            "local-model",
            additional_endpoints=(
                LLMEndpoint(
                    base_url="http://192.168.1.136:1234/v1",
                    model="remote-model",
                ),
            ),
        )
        generation = client.generation_backend()
        reflection = client.prompt_backend(operation="reflection")

        selected = parallel_map(
            lambda _index: (
                generation.base_url,
                generation.model,
                generation.chat_completions_url,
                reflection.base_url,
                reflection.model,
                reflection.chat_completions_url,
            ),
            range(2),
        )

        self.assertEqual(
            selected,
            [
                (
                    "http://127.0.0.1:18080",
                    "local-model",
                    "http://127.0.0.1:18080/v1/chat/completions",
                    "http://127.0.0.1:18080",
                    "local-model",
                    "http://127.0.0.1:18080/v1/chat/completions",
                ),
                (
                    "http://192.168.1.136:1234/v1",
                    "remote-model",
                    "http://192.168.1.136:1234/v1/chat/completions",
                    "http://192.168.1.136:1234/v1",
                    "remote-model",
                    "http://192.168.1.136:1234/v1/chat/completions",
                ),
            ],
        )

    def test_parallel_requests_overlap_and_use_both_endpoint_routes(self) -> None:
        client = LLMClient(
            "http://127.0.0.1:18080",
            "local-model",
            additional_endpoints=(
                LLMEndpoint("http://192.168.1.136:1234", "remote-model"),
            ),
        )
        backend = client.prompt_backend(operation="reflection")
        barrier = threading.Barrier(2, timeout=3)
        observed: list[tuple[str, str]] = []

        def respond(request, *, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            observed.append((request.full_url, payload["model"]))
            barrier.wait()
            return _Response({"choices": [{"message": {"content": "{}"}}]})

        with patch(
            "eagle.operators.reflection.urllib.request.urlopen",
            side_effect=respond,
        ):
            results = parallel_map(
                lambda index: backend.generate_seeded("request", index),
                range(2),
            )

        self.assertEqual(results, ["{}", "{}"])
        self.assertCountEqual(
            observed,
            [
                (
                    "http://127.0.0.1:18080/v1/chat/completions",
                    "local-model",
                ),
                (
                    "http://192.168.1.136:1234/v1/chat/completions",
                    "remote-model",
                ),
            ],
        )

    def test_search_runtime_propagates_configured_endpoints_to_both_clients(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "local-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                    "additional_endpoints": [
                        {
                            "base_url": "http://192.168.1.136:1234",
                            "model": "remote-model",
                        }
                    ],
                }
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = build_search_runtime(
                config,
                mock=True,
                run_dir=root,
                candidates_dir=root / "candidates",
            )

        expected = (
            LLMEndpoint("http://127.0.0.1:18080", "local-model"),
            LLMEndpoint("http://192.168.1.136:1234", "remote-model"),
        )
        self.assertEqual(runtime.client.endpoints, expected)
        self.assertEqual(runtime.generation_client.endpoints, expected)

    def test_search_runtime_preflights_and_binds_distinct_functional_clients(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "reflection-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                },
                "generation_model": {
                    "name": "generation-model",
                    "host": "127.0.0.1",
                    "port": 18081,
                },
            }
        )

        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.evolution.runtime.preflight_llm_endpoint"
        ) as preflight:
            root = Path(directory)
            runtime = build_search_runtime(
                config,
                mock=False,
                run_dir=root,
                candidates_dir=root / "candidates",
            )

        self.assertEqual(preflight.call_count, 2)
        self.assertIs(preflight.call_args_list[0].args[0], runtime.client)
        self.assertIs(preflight.call_args_list[1].args[0], runtime.generation_client)
        self.assertEqual(runtime.client.endpoints[0].base_url, "http://127.0.0.1:18080")
        self.assertEqual(runtime.generation_backend.base_url, "http://127.0.0.1:18081")
        self.assertEqual(runtime.generation_backend.model, "generation-model")

    def test_shared_functional_endpoint_is_preflighted_once(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "shared-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                },
                "generation_model": {
                    "name": "shared-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                },
            }
        )

        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.evolution.runtime.preflight_llm_endpoint"
        ) as preflight:
            root = Path(directory)
            build_search_runtime(
                config,
                mock=False,
                run_dir=root,
                candidates_dir=root / "candidates",
            )

        preflight.assert_called_once()

    def test_inactive_generation_endpoint_is_not_preflighted(self) -> None:
        config = ExperimentConfig.from_mapping(
            {
                "model": {
                    "name": "reflection-model",
                    "host": "127.0.0.1",
                    "port": 18080,
                },
                "generation_model": {
                    "name": "inactive-generation-model",
                    "host": "127.0.0.1",
                    "port": 18081,
                },
                "java_materialization_mode": "deterministic_dsl",
            }
        )

        with tempfile.TemporaryDirectory() as directory, patch(
            "eagle.evolution.runtime.preflight_llm_endpoint"
        ) as preflight:
            root = Path(directory)
            runtime = build_search_runtime(
                config,
                mock=False,
                run_dir=root,
                candidates_dir=root / "candidates",
            )

        preflight.assert_called_once_with(runtime.client)

    def test_preflight_checks_every_endpoint_with_its_model(self) -> None:
        client = LLMClient(
            "http://127.0.0.1:18080",
            "local-model",
            additional_endpoints=(
                LLMEndpoint(
                    base_url="http://192.168.1.136:1234",
                    model="remote-model",
                ),
            ),
            seed=17,
        )

        with patch(
            "eagle.evolution.runtime.urllib.request.urlopen",
            side_effect=[
                _Response({"choices": [{"message": {"content": "local"}}]}),
                _Response({"choices": [{"message": {"content": "remote"}}]}),
            ],
        ) as urlopen:
            preflight_llm_endpoint(client)

        self.assertEqual(urlopen.call_count, 2)
        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual(
            [request.full_url for request in requests],
            [
                "http://127.0.0.1:18080/v1/chat/completions",
                "http://192.168.1.136:1234/v1/chat/completions",
            ],
        )
        self.assertEqual(
            [json.loads(request.data.decode("utf-8"))["model"] for request in requests],
            ["local-model", "remote-model"],
        )


if __name__ == "__main__":
    unittest.main()
