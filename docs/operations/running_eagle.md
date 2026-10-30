# Running EAGLE

## Local experiment GUI

On Ubuntu, run the launcher from the checkout:

```bash
cd /path/to/EAGLE
./gui.sh
```

On native Windows, double-click `gui.cmd` or run it from a terminal. Ubuntu
prefers `.venv/bin/python`, Windows prefers `.venv\Scripts\python.exe`; otherwise
they use `python3` or `python` from the current environment. Install the project
dependencies in that environment first (`python -m pip install -e .`). Each
launcher accepts GUI arguments, for example `./gui.sh --port 8878` or
`gui.cmd --port 8878`. The equivalent direct command on either platform is
`python -m eagle gui --open`.

`gui-wsl.cmd` is the optional Windows-to-WSL launcher. It uses the WSL `.venv`
and WSLg. Native Ubuntu/Windows observation uses that OS's desktop directly.
For migration, configure `model.path`, `model.llama_server`, optional
`generation_model`, and any absolute paths for the destination OS. Windows
requires a Windows `llama-server.exe` build with the desired GPU backend;
Linux binaries cannot be reused. Both systems require `java` and `javac` on
PATH. Keep portable config paths repository-relative where possible. Existing
resolved Run configs contain absolute paths and are not automatically rewritten
for cross-OS resume.

Open `http://127.0.0.1:8877`. Use `--port PORT` if occupied and
`--runs-root PATH` for a different initial run root. The server deliberately
binds only to loopback and accepts control requests only from its own page.
Config files stay under `configs/`; generated batch indices are excluded.

1. Select and load a YAML config. Edit scalar fields in the form; fixed enums
   and booleans use dropdowns, arrays use JSON, and the complete YAML editor
   exposes every setting. Unspecified fields remain inherited instead of
   claiming context-independent defaults. Supported legacy reflection
   probabilities are displayed with their equivalent current meanings.
   Unknown fields are retained. Form edits reserialize YAML, so use the YAML
   editor to preserve comments and formatting.
2. Validate, save, or save as a new config path. Validation uses the existing
   `ExperimentConfig` rules; runtime files, GPU availability, and opponent
   dependencies are checked by the normal experiment startup.
3. Start the current editor contents. The GUI writes an independent input
   snapshot and log under `logs/gui/<id>/`, then invokes the experiment CLI.
   Further editor changes cannot alter the active experiment. Mock and
   skip-final-test controls use existing CLI flags. One experiment job and
   one observation job may run concurrently.
4. Choose a Run and completed generation to inspect its exact survivor
   population. The separate other-candidates entry includes candidates not
   referenced by a survivor snapshot, including eliminated individuals; it
   does not claim they survived. Lists refresh every three seconds, so a
   materialized candidate may be observed during an active run.
5. Select a candidate, opponent, map, tick cap, interval, and side, then open
   the match. `scripts/run_gui_match.py` recompiles and integration-checks the
   persisted source in a temporary directory before launching MicroRTS.
   Observation never writes evolutionary fitness or run artifacts. WSL
   requires WSLg for the game window. External opponents require their setup
   scripts; AlliBot runtime LLM remains disabled by default.

Stop requests use SIGTERM on Ubuntu and an owned console group's Ctrl+Break on
Windows, letting the experiment CLI clean up its owned model runtime. Keep the
Windows launcher terminal open while using the GUI. Closing
the browser leaves jobs running; Ctrl+C in the GUI server terminal requests
job cleanup and stops the server. The selected Run can resume with its own
saved config through existing compatibility checks. Historical runtime config
fields do not prevent observation; they can still prevent resume.

The shell interface is `./experiment.sh CONFIG_TARGET [OPTIONS...]`. The normal batch command is:

```bash
./experiment.sh configs/experiments/static --mock --skip-final-test
```

A directory contributes only its top-level `.yaml` and `.yml` files, sorted by filename. Empty directories fail clearly. A YAML target runs exactly once:

```bash
./experiment.sh configs/experiments/static/ministral3_8b_static.yaml --mock --skip-final-test
```

The equivalent Python interface uses one target option for both forms:

```bash
conda run --no-capture-output -n eagle \
  python -m eagle experiment \
  --config-dir configs/experiments/static \
  --mock --skip-final-test
```

## Framework startup

Fresh framework-slot runs bootstrap inline from `framework.design_brief` unless
an external `framework.bundle_path` is provided. Set
`framework.bootstrap_backend: local` to use the configured local llama-server
without an API key, `groq` to use the default Groq API path, `mistral` to use
Mistral, `gpt` to use OpenAI directly, or `codex` to try `codex exec` before
falling back to OpenAI. For Groq, set `GROQ_API_KEY` in the process
environment; for Mistral, store the key in `api_key/mistral`; for GPT, store it
in `api_key/gpt`. Do not put credentials in YAML, CLI
arguments, shell history, or artifacts. `framework.model` defaults to
`openai/gpt-oss-120b`; use `mistral-small-latest` with Mistral or `gpt-6.1-sol`
with GPT or Codex fallback. The `codex` route uses the existing Codex login and
does not read the GPT key unless Codex is missing, times out, exits unsuccessfully,
or returns an invalid bundle. The GPT credential and endpoint are used only
during initial framework bootstrap. Later `reflection` stages use the top-level local model. The standalone
`python -m eagle framework` command remains available for preparing a bundle to
reuse across runs or replicate seeds.

The bootstrap uses conservative free-plan protection in code: 30 requests per
minute, 1,000 requests per day, 8,000 tokens per minute, and 200,000 tokens
per day. Because Groq's TPM accounting includes the rendered input prompt,
framework output defaults to 6,400 completion tokens, reserving 1,600 tokens
for that prompt under the 8,000-token ceiling. The cap can be overridden for a
higher provider tier. If Groq's best-effort JSON Schema pass returns its
`json_validate_failed` error, EAGLE retains that raw response and retries once
using JSON Object Mode; local bundle validation remains authoritative. Retries—
including schema-validation retries—wait one rolling
minute before sending another request. HTTP 429 responses additionally honor
the provider's `Retry-After` value. These limits apply only to Groq framework
bootstrap calls; the local backend uses the configured Qwen llama-server and is
not rate-limited by Groq.
The local backend may report `finish_reason: length` when its output budget is
exhausted; EAGLE accepts that response only if the JSON and complete framework
bundle pass local validation. Groq continues to require `finish_reason: stop`.
Local bootstrap also disables Qwen thinking with
`chat_template_kwargs.enable_thinking: false`; the framework JSON must be
returned in the normal `message.content` field. Its bootstrap completion budget
is at least 12,288 tokens, independently of the candidate-call budget.

Use this inline form in an ordinary experiment config:

```yaml
schema_version: experiment-v2
java_materialization_mode: framework_slots
candidate_java_mode: generated_phenotype
parent_evaluation_mode: reuse_cached
reflection_operator_mode: static
framework:
  bootstrap_backend: gpt  # direct API; codex, groq, mistral, and local are also supported
  design_brief: "Design a complete CandidateAgent framework with a rich finite control surface."
  model: gpt-6.1-sol
  evolution_mode: reflection
```

Set the top-level `model` profile for the experiment runtime as usual. Omit
`evolution_mode` for the local EA. To reuse a prepared bundle instead, replace
`design_brief` and `model` with `bundle_path: path/to/bundle.json`; optional
`bundle_version` and `bundle_sha256` fences may be used with that external file.

For a fixed-initialization framework run, use the checked-in real bundle and
config directly:

```bash
./experiment.sh configs/framework_coach_mock.yaml --skip-final-test
```

`configs/framework_coach_mock.yaml` points at
`configs/framework_bundles/fixed_worker_combat/bundle.json`. The bundle is a
complete compilable MicroRTS `CandidateAgent` framework with finite worker and
combat controls; because `bundle_path` is explicit, startup skips only the
framework bootstrap. The config keeps normal `openai`-compatible EA execution:
the managed local llama-server and the configured unmanaged additional endpoint
are both used for `llm_coach` initialization/mutation requests. Java rendering,
validation, `javac`, Integration, semantic probes, and MicroRTS evaluation stay
local and unchanged.

For a single-machine run using the same fixed initial framework, use:

```bash
./experiment.sh configs/framework_coach_single_machine.yaml --skip-final-test
```

This config keeps `execution_mode: openai` so the normal local llama-server is
started and used for Coach/Commentator calls, but sets
`model.additional_endpoints: []`. It therefore makes no request to the LAN
endpoint and does not read any API key. The fixed bundle still skips framework
bootstrap, while Java rendering, validation, `javac`, Integration, semantic
probes, and MicroRTS evaluation remain enabled locally.

EAGLE validates an explicit external bundle during config resolution. For inline
bootstrap, it initializes bootstrap evidence and the manifest first,
then writes the resolved frozen config on success or requested pending config
after failure. Successful bootstrap validates and freezes the bundle at
`runs/<run_id>/framework/bundle.json` before search. Resume reads only the
frozen bundle and compares the design brief, bootstrap backend/model, and evolution
mode; it never regenerates the framework. Each fresh replicate bootstraps a
separate framework unless the same explicit bundle path is shared. Mock mode
rejects inline bootstrap without an existing bundle, ensuring no provider request.
Failed attempts and a failed manifest remain; the pending config cannot resume
until a valid frozen bundle exists.

The `local` default samples finite slot values and uses seeded per-slot
crossover and one-slot mutation without candidate-time LLM requests. The sole
bounded exception is `framework.gpt_initial_candidates`: when positive, and
only with `framework_slots` plus `evolution_mode: local`, direct GPT reads
`api_key/gpt` and `framework.model` to select exactly the first N complete Gen-0
genomes. The remaining Gen-0 slots and all offspring stay local; the count
defaults to zero and is resume-fenced. Invalid GPT responses fail
initialization rather than falling back to random/default genomes. A bounded
Gen-0-only treatment may set `generations: 0`; other modes require at least one
evolutionary generation.
For a provider-free replay, set `framework.initial_genomes` to the ordered
list of complete mappings exported from treatment 1. It is mutually exclusive
with `gpt_initial_candidates`, uses the exact first-N prefix, and persists its
resolved list and manifest canonical hash/count. Reusing that list with
the same frozen bundle performs no GPT call and is portable across machines.
`llm_coach` asks the experiment model for initial complete genomes and uses the
existing one-worst-match Commentator/Coach path for Strategy mutation. Neither
mode calls a Java Generator or repair model; rendering, validation, javac,
Integration, semantic probing, and the configured fixed-roster matrix remain
unchanged. See [framework slots](../architecture/framework_slots.md).
The resolved `model` section selects the model name, host/port, optional managed
GGUF/llama-server paths, per-request context size, batch size and timeouts. An
optional `generation_model` section has the same shape and selects the model for
final Java generation, deferred Code Reflection revision, and compile-guided
repair. Each section may contain `additional_endpoints`, an ordered list with at
most one unmanaged OpenAI-compatible endpoint expressed as exactly
`{base_url, model}`. Each functional profile has one or two endpoints. GPU
layers (`999`), model threads (`8`), managed-local server parallel slots (`2`),
independent LLM workers (`2`) are fixed by `eagle/execution.py`. Match execution
uses ten workers by default; set `evaluation.match_execution: serial` to use one
worker for same-seed audits and reduced scheduling variance. The server allocates
`context_size × 2`, while each request keeps the configured context size.
Before starting llama.cpp, GPU-device preflight must succeed. Every fresh child
startup must also emit positive full `offloaded N/N layers to GPU` evidence for the
selected model. Missing, stale, malformed, or partial offload evidence shuts down
the owned process and fails the run; EAGLE never continues on CPU. These obsolete
keys are rejected, not migrated: `gpu_layers`, `threads`,
`parallel`, and `evaluation.match_workers`. The orchestrator validates runtime
files for managed primaries outside mock mode, starts their owned process per run,
keeps functional clients permanently bound, and requires a successful
bounded chat completion from the primary and every additional endpoint before
candidate work begins. Any endpoint failure is fail-closed. It runs search and the
production final test, then stops only its owned local process in `finally`;
external endpoints are never adopted, restarted, signalled, or stopped.

```yaml
model:
  name: ministral3_8b
  path: experiment_env/model/ministral3-8b-instruct-q4-k-m/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf
  llama_server: experiment_env/model/llama.cpp/llama.cpp/build-eagle/bin/llama-server
  port: 8080
  additional_endpoints:       # optional; zero or one entry
    - base_url: http://192.168.1.136:1234
      model: ministral3_8b     # exact model id accepted by that service
generation_model:            # omit to share model concurrently
  name: qwen3.5_9b
  host: 192.168.1.137         # independently started generation server
  port: 1234
```

For a primary server you start on another machine, omit both `model.path` and
`model.llama_server`; only `name`, `host` and `port` are needed. EAGLE
preflights and calls that endpoint without constructing a RuntimeManager. To
retain automatic local startup, provide both local runtime paths. Providing only
one is invalid. Generation profiles are always external.

Different model names require different server hosts/ports. Start the generation
server yourself; EAGLE only preflights and calls it. Previous swap-in-place
configs using the same endpoint for two models must be updated for active runs.
Historical configs remain readable for final tests; the routing check applies
when starting active LLM work. With one model,
omit `generation_model`; concurrent roles share two request slots per server.
Each child's ready work progresses through source gate, crossover, mutation,
generation/compilation and matches without an all-candidate phase barrier.
One ten-worker match matrix overlaps preparation of later children.

When a folder contains multiple YAML files, they run in filename order. Each
direct experiment run, including every `runs` replicate, stops any previous
owned `llama-server`. Managed primaries start a fresh process from that run's
resolved config; external primaries are called directly. Within a run, clients stay permanently
bound to their configured servers; no phase switching occurs. Canonical task
index selects the ordered endpoint route, dependent retries stay there, and
request evidence records the actual endpoint/model. Generation and additional
servers remain unmanaged. Results retain canonical input order despite overlap.

Generation 0 is initialization. `generations: 20` therefore records generation 0 and performs evolutionary generations 1 through 20.

A direct config or folder batch may set `runs: 3` to execute three
independent replicates. Each replicate writes its own run directory and
uses an incremented `random_seed` (`random_seed`, then `random_seed + 1`, and
so on). To repeat
each of several explicit seeds, provide `random_seeds` and use `runs` as the
repeat count, for example `random_seeds: [7, 8, 9]` with `runs: 2` executes
`7, 7, 8, 8, 9, 9`. The default is `runs: 1`. Folder batches support
multiple replicates per config.
With `random_seeds: [8]` and `runs: 3`, the config receives seeds `8, 8, 8`.

Match execution uses ten bounded workers by default, with canonical results in
match_index order. `evaluation.match_execution: serial` switches the matrix to
one worker while preserving the same match identities and result ordering.
This reduces scheduling variance but cannot control external opponent wall-clock
budgets or private RNGs, so it is not a bitwise reproducibility guarantee.
match_timeout_seconds and match_artifact_mode remain
independent top-level settings because they control per-process timeout and
evidence retention rather than scheduling.

The resolved config records `survivor_selection: mu_plus_lambda`. Parent and
offspring candidates jointly enter the evaluation mode's survivor selection:
fixed roster uses seeded lexicase, while self-play uses scalar Game Performance
with the semantic tie-break. A config
with three seed policies and `population_size: 3` therefore performs exact
`3 + 3` environmental selection in every evolutionary generation.

`configs/experiments/static_0826_seed_variants/` is a three-config batch: blank,
Worker Rush, and deterministic pseudo-random. Each config has one seed policy
and `population_size: 10`. In `candidate_java_mode: inherited_genotype`, the
policy and callable no-op Java are copied into ten generation-zero genotypes,
then ten independent Generator calls may produce ten different Java agents.
Every later generation performs exact `10 + 10` environmental selection.

`configs/experiments/0903_llm_initial_population/` demonstrates mixed
generation-zero initialization:

```yaml
candidate_java_mode: inherited_genotype
initial_population_mode: llm_generated_policies
seed_prompt_files: [seeds/worker_rush_policy.txt]
initial_policy_generation_prompt_file: prompts/initial_policy_generation.txt
initial_java_seed_path: eagle/java_seeds/worker_rush/CandidateAgent.java
agent_template_path: eagle/java_seeds/CandidateAgent.java
population_size: 10
llm:
  initial_policy_temperature: 0.8
```

Slot 1 uses the configured Worker Rush policy. Slots 2–10 are nine LLM policy
requests with stable, slot-specific strategy identities from
`prompts/initial_policy_variants.txt`; they are not `RandomAI` agents. This
produces different initial policy targets even with `temperature: 0`, while
keeping same-seed reruns reproducible. Every policy then receives an independent
Java Generator call; WorkerRush Java is inherited request context, not the
phenotype.
`initial_policy_max_attempts` bounds invalid or
duplicate policy-output retries. `random_seed` is the single EA root seed;
all LLM roles receive derived request seeds tied to task identity and attempt.
Controllable execution is always seeded. Concurrent LLM work and match workers
collect results in input order; stable task seeds do not depend on completion
order or worker identity. Endpoint assignment likewise depends on canonical
input index plus the persisted endpoint order, not worker identity or completion
order. LLM temperatures remain configurable.

Same inputs and root seed reproduce the EA when task outputs are stable.
External LLM services may ignore seeds; GPU/backend kernels, batching, private
opponent RNGs, and wall-clock timeouts may still vary. Compare request/response
hashes and match seeds when diagnosing divergence. See the
[reproducibility contract](../eagle_architecture_spec.md#4-reproducibility).

To test one exact prompt repeatedly against the configured endpoint, run:

```bash
python3 scripts/test_llm_stability.py \
  --config configs/experiments/your_config.yaml \
  --prompt-file prompts/your_prompt.txt \
  --repeats 3
```

The command writes `stability_report.json` and raw responses under
`runs/llm_stability/<UTC timestamp>/`. It returns exit code `0` when all hashes
match and `2` when at least one response differs.

To compare seeds while fully restarting the configured llama-server before
each seed, use:

```bash
python3 scripts/test_llm_seed_restarts.py \
  --config configs/experiments/0920_self_play/self_play_10x20.yaml \
  --prompt "Reply with exactly: STABILITY_OK" \
  --seeds 7,8,9 \
  --repeats 3
```

The script owns each server process, stops it after the seed's repetitions, and
starts a fresh process for the next seed. It writes one raw-response report per
seed plus `stability_matrix.json`, which separately reports
`same_seed_stable` and `cross_seed_changed`. Do not leave a manually started
server on the configured port; the runtime manager refuses to kill foreign
processes.

To enable managed opponent-library self-play explicitly:

```yaml
reflection_operator_mode: static
parent_evaluation_mode: reuse_cached
evaluation:
  mode: self_play
  self_play_refresh_interval: 5
  self_play_opponent_library_capacity: 50
  self_play_pool_policy: tournament-v1
```

The capacity includes four permanent protected built-ins and must be at least
10. Generation zero evaluates all ten built-in sources using the fixed slots:
the protected four keep their actual case IDs and the other six use
`self_play_000`…`self_play_005`. Generation one and each refresh boundary keep
the protected case IDs and use those six slots for sampled nonprotected pool
members. Context rows identify built-ins by `source_opponent_id`.
Novel eligible agents challenge a seeded sampled incumbent when the pool is
full. Only a complete 18-match duel with strictly more wins than losses can
replace an incumbent. Self-play requires the exact policy marker shown above;
older resolved configs without it are inspectable but cannot resume under the
new policy. See the [canonical evaluation contract](../eagle_architecture_spec.md#9-evolution-evaluation)
for artifacts and failure handling.

## Resume

Resume can target one run and uses its immutable run-local configuration:

```bash
./experiment.sh --resume runs/20260811_120000_000000
```

It can also continue a whole config-folder batch:

```bash
./experiment.sh --resume configs/experiments/static_0820/
```

Folder resume reads that directory's generated `experiment.yaml` index. Its
`eagle-experiment-index-v1` schema maps each exact config filename to an ordered
list of absolute run-directory paths. List positions are zero-based replicate
indices. Legacy filename-to-path mappings remain readable as one-item lists and
are upgraded atomically when a run is next recorded. Resume validates each run's
effective seed against its scheduled slot, skips completed slots, resumes
interrupted runs and missing required final tests first, then creates missing
replicates. A fresh launch starts a fresh index. If interruption happened before
generation zero was recorded, that slot is replaced by a new run; old evidence
remains on disk. An existing `experiment-v2` config named `experiment.yaml`
remains a config and is never overwritten by the index.

If a config folder is also supplied, it is compatibility-checked against the run. Model identity/path, the complete ordered primary-plus-additional endpoint list, EA parameters, evaluation matrix, and reflection mode/probabilities cannot silently change. Adding, removing, reordering, or retargeting an endpoint fails resume compatibility. Missing persisted model assets fail clearly. Only the latest atomically recorded generation is resumed; incomplete candidate work is recomputed.

For `framework_slots`, resume additionally reloads only the run-owned
`framework/bundle.json`, verifies its schema and exact SHA-256 against the
manifest/config, and checks every candidate genome and rendered-source hash. A
changed or missing external bootstrap directory cannot change a run; a changed,
missing, or unsupported run-frozen bundle makes resume fail explicitly.

`generation_max_attempts` controls bounded compile-guided Java decoding. Its
repository and legacy-config default is `1`; production configs that opt in
must persist the value explicitly. `static_0824` uses `5`. Attempt 1 uses the
authoritative active-genotype request. Extraction failures repeat that base request;
validation or javac failures produce a new repair request from the immediately
previous complete source and its structured diagnostics. Changing this field
changes resolved run identity and is not allowed during resume. Partial
candidate attempt artifacts are retained for audit but are never resumed or
overwritten; work restarts from the last atomically recorded generation.

## Mock and final test

```bash
./experiment.sh configs/experiments/static --mock --skip-final-test
python -m eagle experiment --config-dir configs/experiments/qwen3_5_9b/ --skip-final-test
```

Mock mode does not adapt or start llama.cpp, inspect the configured port, validate the GGUF for llama.cpp, or health-check an endpoint. It skips the production final test. Mock matches retain their canonical match artifacts but synthesize only the initial and final round snapshots. `--skip-final-test` is also available for focused production diagnostics and does not skip EA or analysis artifacts.

## Fixed cross-generation evaluation

```bash
python -m eagle.fixed_evaluation --run-dir runs/<run>
python -m eagle.fixed_evaluation --run-dir runs/<run> --generations 0 5 10 15 20 --seed 42
```

For the 1030 slot ablation, treatments 2 and 3 use one combined evaluation:

```bash
python -m eagle.fixed_evaluation --run-dir runs/<run> --generations 20 30 40 50 75 100
```

Treatment 1 is Gen-0-only and uses `--generations 0`. The combined command
does not create separate evolutionary runs.

The defaults are generations `0 5 10 15 20` and the run-config seed. The run must be complete and every requested snapshot must exist; missing generations fail without substitution. Frozen protocol and results go to a separate `fixed_evaluation/` directory by default. An explicit output directory must be new or empty; use another directory for each rerun to preserve prior evidence. Combined outputs are `fixed_evaluation_summary.json`, `fixed_evaluation_results.csv`, and `fixed_evaluation_results.md`. `mean_match_score` is the unweighted benchmark mean, separate from canonical search fitness. If a matrix is incomplete or has errors, its aggregate score and win rate are null and the command exits nonzero. This command leaves ordinary `eagle.final_test` behavior and search artifacts unchanged; see the evaluation and artifact contracts for selection and output details.

## Reflection modes

```yaml
reflection_operator_mode: aos_head2head # static | aos_opponent | aos_head2head
strategy_reflection_probability: 0.20
prompt_reflection_probability: 0.80
code_reflection_probability: 0.00
aos_minimum_probability: 0.10
```

Normal mutation/AOS has only Strategy and Prompt. Supplied legacy weights are
normalized over Strategy/Prompt with Code probability fixed at zero; all-zero
weights skip normal mutation. Independent Code Reflection still checks every
selected reproduction source before actual crossover/mutation, with each
contributor's own DSL policy and exact Java. Defective/failed checks emit
one-parent diagnosed children and skip normal variation. Corrective Java is
materialized at the generation-model boundary without Generator overwrite.

New policies must be canonical `eagle-strategy-dsl-v1` JSON. Resolved configs
record `strategy_policy_format: eagle-strategy-dsl-v1` and
`evolution_protocol: eagle-dsl-pre-crossover-v1`. Resume checks this protocol
before touching the run. Historical runs remain inspectable, but incompatible
policy/protocol or old controller state cannot resume; start a new run rather
than silently converting natural-language policies. Controller state is
`eagle-reflection-operator-v6`.

Every YAML creates fresh population, RNG, operator/AOS state, archives, IDs, and
run directory; only a compatible LLM process may be reused.

There are no separate `run` or `runtime` compatibility entrypoints. The
experiment orchestrator is the only model/search lifecycle owner.
