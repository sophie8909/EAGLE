# EAGLE

**Evolutionary Agent Generation through LLM-guided Exploration**

*Strategy, Prompt, and Code Reflection for Evolving Game-Playing Agents*

EAGLE evolves versioned JSON DSL policies and reusable translation prompts that
generate complete Java MicroRTS agents. The DSL is validated offline and compiled
through Java generation; matches use no DSL runtime interpreter.

Every selected reproduction source passes independent Code Reflection before
crossover or mutation. Defects create one-parent corrective Java children with
unchanged genes; healthy sources undergo Strategy/Prompt variation. Code gating
is independent of adaptive mutation credit and permits no cosmetic simplification.

New policies use canonical `eagle-strategy-dsl-v1` JSON. Historical natural-language
artifacts remain read-only; incompatible old runs cannot resume through silent conversion.
See the [implementation plan](docs/implementation/dsl_pre_crossover_reflection_plan.md).

EAGLE also provides `framework_slots` mode. Fresh experiments bootstrap a
complete Java framework inline from `framework.design_brief` when no external
bundle path is supplied. Set `GROQ_API_KEY` in the environment; the default
bootstrap model is `openai/gpt-oss-120b`. An explicit `framework.bundle_path`
reuses a prepared framework across replicates, and the standalone
`python -m eagle framework` command remains available for compatibility.
`framework.evolution_mode` defaults to `local`; opt-in `llm_coach` uses the
experiment model for complete initial genome selection and the existing
worst-match Commentator/Coach Strategy path. Both policies render Java locally
and disable Java Generation and repair calls. See the canonical
[framework-slot contract](docs/architecture/framework_slots.md).

## Canonical workflow

For the local experiment GUI, run `./gui.sh` on Ubuntu, or double-click
`gui.cmd` for native Windows. `gui-wsl.cmd` retains the Windows-to-WSL entry.
All launchers use the local Python environment and open
`http://127.0.0.1:8877` to edit a config, start or stop an experiment, and select
a run, generation, candidate, opponent, map, and side for a visual match. See
[GUI operation](docs/operations/running_eagle.md#local-experiment-gui).

Each experiment folder owns its EA, reflection, evaluation, model, endpoint, and llama.cpp launch settings:

```bash
./experiment.sh configs/experiments/qwen3_5_9b/
./analyze.sh --latest
```

`experiment.sh` is a thin wrapper for `python -m eagle experiment`. The Python orchestrator validates the selected GGUF and llama-server, checks port ownership, starts the configured model, waits for health and a chat-completion preflight, runs the EA and production final test, then stops only the process it started. Cleanup also runs after EA/final-test failure and Ctrl+C.

Offspring creation reports mutation progress as `[gen G cand I/N]`, including started, completed, failed, and skipped states. Blocking LLM requests also print start/completion messages and a waiting heartbeat every 30 seconds. Set `EAGLE_LLM_PROGRESS=0` to suppress successful-request LLM progress while retaining candidate progress and failure messages.

`random_seed` controls all EA-owned stochastic streams, including LLM request
and MicroRTS match seeds. Controllable execution is always deterministic;
parallel match workers use stable task seeds and result ordering. External LLM,
GPU/backend, private opponent RNG, and timing effects can still vary. See the
[reproducibility contract](docs/eagle_architecture_spec.md#4-reproducibility).

Resume does not require the original experiment folder:

```bash
./experiment.sh --resume runs/<run_id>
```

It reloads `runs/<run_id>/config.yaml`, including the exact model and reflection
mode, and requires `evolution_protocol: eagle-dsl-pre-crossover-v1` plus
`strategy_policy_format: eagle-strategy-dsl-v1`. Incompatible historical runs
remain inspectable but cannot resume under the changed algorithm.

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

To run one resident read-only status endpoint for all experiments under `runs/`, run:

```bash
python -m eagle monitor --runs-root runs --host 0.0.0.0 --port 8765
```

New runs created by `python -m eagle experiment` are discovered automatically.
The compact JSON snapshot is updated at `runs/monitor_status.json`; the HTTP
URL is `http://<experiment-host>:8765/status.json`. The detailed diagnostic
payload remains available at `/status`.

Token protection remains available by adding `--token`, but is optional when
the monitor is restricted to a trusted private network.

See [`docs/operations/monitoring_experiment.md`](docs/operations/monitoring_experiment.md)
for the endpoint contract and network-safety requirements.
