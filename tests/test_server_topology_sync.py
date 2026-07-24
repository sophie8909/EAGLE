import json
import tempfile
import unittest
from pathlib import Path

from eagle.runtime.server_manager import ServerSpec
from eagle_ui.controllers.llm_controller import LLMConfigController


class ServerTopologySyncTests(unittest.TestCase):
    def test_server_settings_become_role_topology_for_ea(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            topology = root / "experiment_env" / "config" / "llm_topology.json"
            topology.parent.mkdir(parents=True)
            topology.write_text(json.dumps({"version": 1, "servers": {}, "roles": {}}), encoding="utf-8")
            controller = LLMConfigController(root)
            spec = ServerSpec(
                server_id="local-llm",
                model_path=root / "model.gguf",
                server_path="llama-server",
                model_id="qwen3.5-local",
                host="127.0.0.1",
                port=8080,
                roles=("reflector", "rewriter", "generator"),
            )
            controller._sync_server_topology(spec)
            payload = json.loads(topology.read_text(encoding="utf-8"))
            self.assertEqual(payload["servers"]["local-llm"]["model_id"], "qwen3.5-local")
            self.assertEqual(payload["servers"]["local-llm"]["base_url"], "http://127.0.0.1:8080/v1")
            self.assertEqual(payload["roles"]["generator"]["server_id"], "local-llm")


if __name__ == "__main__":
    unittest.main()
