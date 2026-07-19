# Dual-host LLM deployment

This is the initial experiment assignment. EAGLE depends on logical profiles, so replacing either model later requires rerunning the launcher and updating endpoint metadata rather than changing Python stage code.

| Stage | Logical profile | Initial model alias | Host |
| --- | --- | --- | --- |
| Reflection | `general` | `qwen3.5-9b` | Machine B, local |
| Rewrite | `general` | `qwen3.5-9b` | Machine B, local |
| Generation | `coder` | `qwen2.5-coder-7b` | Machine A over private LAN |

Machine A runs only the coder llama.cpp service. Machine B runs the general service and the main EAGLE process. The general service defaults to `127.0.0.1:8080`; the coder service binds llama.cpp to `0.0.0.0:8081` but publishes Machine A's detected private LAN address in the client URL. The context size defaults to `32768` for both profiles and remains configurable.

## Setup workflow

The repository provides `scripts/llama_launcher.py`. It never downloads a model or rebuilds llama.cpp. It asks for the actual `.gguf` path unless `--model-path` is supplied, accepts `--alias`, `--port`, `--context-size`, and `--server-path` overrides, starts the existing `llama-server`, waits for `/health`, and atomically updates only the selected section of `config/llm_endpoints.toml`.

Machine A:

```bash
git pull
python3 scripts/llama_launcher.py --profile coder --alias qwen2.5-coder-7b --port 8081
git add config/llm_endpoints.toml
git commit -m "chore(config): update coder LLM endpoint"
git push
```

Machine B:

```bash
git pull
python3 scripts/llama_launcher.py --profile general --alias qwen3.5-9b --port 8080
python3 scripts/run_eagle.py --config configs/eagle_10x50.yaml
```

The committed endpoint file contains only profile, base URL, port, and configured alias. GGUF paths, llama-server paths, GPU settings, and secrets are stored in `~/.config/eagle-llm/<profile>.env` with mode `600` where supported. A coder endpoint with a placeholder host, `0.0.0.0`, or loopback is rejected for dual-host execution. Tests may explicitly set `allow_coder_loopback: true` for two services on one machine.

The launcher prints the detected coder LAN address and asks for correction when multiple private interfaces exist. Machine A must remain powered on, and its firewall must allow Machine B to reach the coder port. If DHCP changes the address, rerun the coder launcher and push the non-sensitive endpoint update. The two aliases and ports may differ; EAGLE sends the explicitly configured alias and does not infer identity from `/v1/models` or a GGUF filename.

Run artifacts record `llm_profile` and the configured alias for each Reflection, Rewrite, and Generation stage. The resolved run configuration records the centralized stage routing. No API key is written to endpoint config, artifacts, logs, or Git.
