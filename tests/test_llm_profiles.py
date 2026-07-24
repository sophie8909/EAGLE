import tempfile
import unittest
from pathlib import Path

from eagle.llm_profiles import EndpointConfigError, LLMProfile, load_role_profiles, save_role_profiles
from eagle.mutation import build_reflection_backend
from generation.backend import build_generation_backend


class LLMProfileTests(unittest.TestCase):
    def _topology(self, path: Path) -> None:
        path.write_text(
            '{"version": 1, "servers": {"server": {"base_url": "http://127.0.0.1:8080/v1", "model_id": "qwen3-8b"}}, '
            '"roles": {"reflector": {"server_id": "server"}, "rewriter": {"server_id": "server"}, "generator": {"server_id": "server"}}}\n',
            encoding="utf-8",
        )

    def test_role_topology_resolves_all_semantic_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_topology.json"
            self._topology(path)
            profiles = load_role_profiles(path)
        self.assertEqual(set(profiles), {"reflector", "rewriter", "generator"})
        self.assertEqual(profiles["generator"].model, "qwen3-8b")

    def test_role_topology_save_round_trip_updates_server_values(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_topology.json"
            self._topology(path)
            profiles = load_role_profiles(path)
            updated = {
                role: LLMProfile(
                    profile=role,
                    base_url=profile.base_url,
                    model="qwen3.5-9b",
                    server_profile=profile.server_profile,
                    server_label="local",
                )
                for role, profile in profiles.items()
            }
            save_role_profiles(path, updated)
            reloaded = load_role_profiles(path)
        self.assertEqual(reloaded["rewriter"].model, "qwen3.5-9b")
        self.assertEqual(reloaded["generator"].server_label, "local")

    def test_missing_role_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "llm_topology.json"
            path.write_text('{"servers": {}, "roles": {}}', encoding="utf-8")
            with self.assertRaisesRegex(EndpointConfigError, "no assignment"):
                load_role_profiles(path)

    def test_stage_backends_keep_canonical_role_identity(self):
        reflector = build_reflection_backend("openai", base_url="http://127.0.0.1:8080/v1", model="reflector", llm_profile="reflector")
        generator = build_generation_backend("openai", base_url="http://127.0.0.1:8081/v1", model="generator", llm_profile="generator")
        self.assertEqual(reflector.llm_profile, "reflector")
        self.assertEqual(generator.llm_profile, "generator")


if __name__ == "__main__":
    unittest.main()