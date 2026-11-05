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
bundle path is supplied. Bootstrap can use Codex CLI with GPT API fallback,
Groq, Mistral, direct GPT/OpenAI, or the configured local server. The `codex`
route uses the existing Codex login first and reads `api_key/gpt` only if Codex
cannot produce a valid bundle. This one initial call can use `gpt-6.1-sol`;
later framework reflection remains on the top-level local experiment model. An explicit `framework.bundle_path`
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

Each experiment folder owns its EA, reflection, evaluation, model, endpoint, and optional llama.cpp launch settings. By default, `python -m eagle experiment` starts and owns the configured local primary for the duration of the experiment, including its runs and final test, then cleans up its process. The local endpoint defaults to loopback (`127.0.0.1`); remote selection and additional endpoints are opt-in.

```bash
# Start the experiment; it starts and cleans up its configured local primary.
./experiment.sh configs/experiments/1104_description_guided/experiment.yaml
./analyze.sh --latest
```

`--connect-only` skips local runtime file checks and lifecycle management, and connects to an already running endpoint. Use it on Windows when the local model service was started separately; the same YAML can retain local launch paths. A config that omits both `model.path` and `model.llama_server` also uses an external primary. The standalone `python -m eagle server --config CONFIG.yaml` command remains available for manual server management. The GUI offers the same connect-only choice.

For seed comparisons across two machines, use separate checkouts and output directories, preserve the same model version, inference settings, framework bundle hash, and other scientific parameters, and give each machine its own seed in `random_seeds` with `runs: 1`. Only the seed differs scientifically; `--connect-only` is an operational choice for the machine using a prestarted server. EAGLE does not coordinate or synchronize the two machines.

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
