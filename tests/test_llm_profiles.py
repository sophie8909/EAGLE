import tempfile
import unittest
from pathlib import Path

from eagle.llm_profiles import (
    EndpointConfigError,
    LLMProfile,
    load_effective_role_profiles,
    load_endpoint_profiles,
    load_role_profiles,
    update_endpoint_profile,
)
from eagle.mutation import build_reflection_backend
from generation.backend import build_generation_backend


class LLMProfileTests(unittest.TestCase):
    def test_profile_update_preserves_the_other_machine_section(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_endpoints.toml"
            update_endpoint_profile(path, LLMProfile("general", "http://127.0.0.1:8080/v1", "qwen3.5-9b"))
            update_endpoint_profile(path, LLMProfile("coder", "http://192.168.1.20:8081/v1", "qwen2.5-coder-7b"))
            update_endpoint_profile(path, LLMProfile("coder", "http://192.168.1.21:8081/v1", "qwen2.5-coder-7b-int4"))
            profiles = load_endpoint_profiles(path)
            self.assertEqual(profiles["general"].model, "qwen3.5-9b")
            self.assertEqual(profiles["coder"].base_url, "http://192.168.1.21:8081/v1")

    def test_loopback_coder_requires_explicit_single_machine_override(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_endpoints.toml"
            update_endpoint_profile(path, LLMProfile("general", "http://127.0.0.1:8080/v1", "qwen3.5-9b"))
            update_endpoint_profile(path, LLMProfile("coder", "http://127.0.0.1:8081/v1", "qwen2.5-coder-7b"))
            with self.assertRaises(EndpointConfigError):
                load_endpoint_profiles(path)
            profiles = load_endpoint_profiles(path, allow_coder_loopback=True)
            self.assertEqual(profiles["coder"].profile, "coder")

    def test_general_only_requires_and_returns_only_general_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_endpoints.toml"
            update_endpoint_profile(path, LLMProfile("general", "http://127.0.0.1:8080/v1", "qwen3.5-9b"))
            profiles = load_endpoint_profiles(path, required_profiles=("general",))
            self.assertEqual(set(profiles), {"general"})
            self.assertEqual(profiles["general"].model, "qwen3.5-9b")
    def test_stage_factories_use_logical_profiles_and_distinct_aliases(self):
        general = build_reflection_backend("llama_cpp", base_url="http://127.0.0.1:8080/v1", model="qwen3.5-9b", llm_profile="general")
        coder = build_generation_backend("llama_cpp", base_url="http://192.168.1.20:8081/v1", model="qwen2.5-coder-7b", llm_profile="coder")
        self.assertEqual(general.llm_profile, "general")
        self.assertEqual(general.model, "qwen3.5-9b")
        self.assertEqual(coder.llm_profile, "coder")
        self.assertEqual(coder.model, "qwen2.5-coder-7b")
    def test_placeholder_coder_host_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_endpoints.toml"
            path.write_text(
                '[general]\nprofile = "general"\nbase_url = "http://127.0.0.1:8080/v1"\nmodel = "qwen3.5-9b"\n\n'
                '[coder]\nprofile = "coder"\nbase_url = "http://<machine-a-private-ip>:8081/v1"\nmodel = "qwen2.5-coder-7b"\n',
                encoding="utf-8",
            )
            with self.assertRaises(EndpointConfigError):
                load_endpoint_profiles(path)

    def test_role_topology_resolves_semantic_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_topology.json"
            path.write_text(
                """
{
  "version": 1,
  "servers": {
    "general-server": {
      "base_url": "http://127.0.0.1:8080/v1",
      "model_id": "qwen3-8b",
      "roles": ["reflector", "rewriter"]
    },
    "coder-server": {
      "base_url": "http://192.168.1.20:8081/v1",
      "model_id": "qwen-coder-7b",
      "roles": ["generator"]
    }
  },
  "roles": {
    "reflector": {"server_id": "general-server"},
    "rewriter": {"server_id": "general-server"},
    "generator": {"server_id": "coder-server"}
  }
}
""",
                encoding="utf-8",
            )
            profiles = load_role_profiles(path)
            self.assertEqual(profiles["reflector"].model, "qwen3-8b")
            self.assertEqual(profiles["rewriter"].base_url, "http://127.0.0.1:8080/v1")
            self.assertEqual(profiles["generator"].model, "qwen-coder-7b")

    def test_empty_role_topology_falls_back_to_legacy_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            topology = Path(temp) / "llm_topology.json"
            endpoints = Path(temp) / "llm_endpoints.toml"
            topology.write_text('{"version": 1, "servers": {}, "roles": {}}\n', encoding="utf-8")
            update_endpoint_profile(endpoints, LLMProfile("general", "http://127.0.0.1:8080/v1", "qwen3.5-9b"))
            profiles, routing = load_effective_role_profiles(
                role_topology_path=topology,
                endpoint_config_path=endpoints,
                llm_topology="general_only",
            )
            self.assertEqual(profiles["reflector"].model, "qwen3.5-9b")
            self.assertEqual(profiles["rewriter"].model, "qwen3.5-9b")
            self.assertEqual(profiles["generator"].model, "qwen3.5-9b")
            self.assertEqual(routing["generation"], "generator")


if __name__ == "__main__":
    unittest.main()
