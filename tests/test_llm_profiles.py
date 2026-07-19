import tempfile
import unittest
from pathlib import Path

from eagle.llm_profiles import EndpointConfigError, LLMProfile, load_endpoint_profiles, update_endpoint_profile
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


if __name__ == "__main__":
    unittest.main()
