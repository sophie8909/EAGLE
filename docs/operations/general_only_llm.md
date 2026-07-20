# Single-machine general-only deployment

Use this variant when Machine B should run the llama.cpp service and the complete EAGLE process, with no Machine A and no coder endpoint.

All LLM stages use the `general` logical profile:

| Stage | Profile | Initial alias |
| --- | --- | --- |
| Reflection | `general` | `qwen3.5-9b` |
| Rewrite | `general` | `qwen3.5-9b` |
| Generation | `general` | `qwen3.5-9b` |
| Strategy Alignment | `general` | `qwen3.5-9b` |

On Machine B:

```bash
cd /path/to/EAGLE
git pull

python3 scripts/llama_launcher.py \
  --profile general \
  --alias qwen3.5-9b \
  --port 8080 \
  --context-size 32768 \
  --model-path /path/to/actual-qwen-general.gguf \
  --server-path /path/to/llama-server

python3 scripts/run_eagle.py \
  --config configs/eagle_general_only.yaml
```

The launcher asks for paths interactively when the optional path arguments are omitted. It does not download models or rebuild llama.cpp. It writes only the `[general]` section of `config/llm_endpoints.toml`; `[coder]` is not required in this mode.

The resulting endpoint config needs only:

```toml
[general]
profile = "general"
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.5-9b"
```

The selected alias and endpoint are recorded in `resolved_config.json` and stage artifacts. To use another general model or port, rerun the launcher with `--alias` or `--port`; do not change Python pipeline code.
