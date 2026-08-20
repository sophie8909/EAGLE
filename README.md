# EAGLE

EAGLE (Evolutionary Algorithm for Game-playing with LLM-Enabled Agents) evolves prompts that generate complete Java MicroRTS agents.

## Canonical workflow

Each experiment folder owns its EA, reflection, evaluation, model, endpoint, and llama.cpp launch settings:

```bash
./experiment.sh configs/experiments/qwen3_5_9b/
./analyze.sh --latest
```

`experiment.sh` is a thin wrapper for `python -m eagle experiment`. The Python orchestrator validates the selected GGUF and llama-server, checks port ownership, starts the configured model, waits for health and a chat-completion preflight, runs the EA and production final test, then stops only the process it started. Cleanup also runs after EA/final-test failure and Ctrl+C.

Resume does not require the original experiment folder:

```bash
./experiment.sh --resume runs/<run_id>
```

It reloads `runs/<run_id>/config.yaml`, including the exact model and reflection mode.

New runs use one resolved config snapshot and a compact root:

```text
runs/<run_id>/
├── manifest.json
├── config.yaml
├── summary.json
├── timing.jsonl
├── generations/
├── candidates/
├── generated_agents/
├── classes/
├── archives/
├── llm_logs/
└── final_test/
```

Only `eagle-run-v2` is supported by writers, resume, and offline analysis.

`watchdog.sh` remains an optional independent network-interface monitor. It does not manage the model server or experiment lifecycle.
