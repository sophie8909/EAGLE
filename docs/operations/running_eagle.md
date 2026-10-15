# Running EAGLE

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

## One-time Gemini framework bootstrap

Framework-slot runs use two explicit commands. First create a new bootstrap
directory; the API key is environment-only and must not be placed in YAML,
shell history as a CLI option, or tracked artifacts:

```bash
export GEMINI_API_KEY='...'
python -m eagle framework \
  --model YOUR_GEMINI_MODEL \
  --brief-file framework_design.txt \
  --output runs/framework_bootstrap/my_framework
```

`--brief` may replace `--brief-file`. Optional bounds are `--temperature`,
`--max-output-tokens`, `--max-attempts`, and `--timeout-seconds`. The command
uses native Gemini `generateContent` structured JSON, refuses a nonempty output
directory, retains every raw response before parsing, and exits `2` if its
bounded attempts do not publish a valid bundle. Review `bundle.json`,
`CandidateAgent.template.java`, `report.json`, and `bootstrap.json` before use.

Then select those exact bundle bytes in an ordinary experiment config:

```yaml
schema_version: experiment-v2
java_materialization_mode: framework_slots
candidate_java_mode: generated_phenotype
parent_evaluation_mode: reuse_cached
reflection_operator_mode: static
framework:
  bundle_path: runs/framework_bootstrap/my_framework/bundle.json
  # Optional input fences; config resolution always fills both in config.yaml.
  bundle_version: eagle-framework-bundle-v1
  bundle_sha256: <sha256-of-exact-bundle.json-bytes>
```

Keep the normal population, generation, evaluation-map, opponent, and runtime
settings. EAGLE validates the bundle at config load, copies it to
`runs/<run_id>/framework/bundle.json`, records the exact byte hash, and runs
without an LLM server. Generation zero samples finite slot values; later EA work
uses only seeded local per-slot crossover and one-slot mutation. Formula controls
are choice IDs for bundle-frozen Java expressions. Validation, javac,
Integration, semantic probing, and the configured 180-match fixed-roster matrix
remain unchanged. See [framework slots](../architecture/framework_slots.md).

The resolved `model` section selects the GGUF, llama-server executable, host,
port, per-request context size, batch size, and health/startup timeouts. An
optional `generation_model` section has the same shape and selects the model for
final Java generation, deferred Code Reflection revision, and compile-guided
repair. GPU layers (`999`), model threads (`8`), server parallel slots (`2`),
independent LLM workers (`2`), and match workers (`10`) are fixed by
`eagle/execution.py`; they are not config fields. The server allocates
`context_size × 2`, while each request keeps the configured context size.
Before starting llama.cpp, GPU-device preflight must succeed. Every fresh child
startup must also emit positive full `offloaded N/N layers to GPU` evidence for the
selected model. Missing, stale, malformed, or partial offload evidence shuts down
the owned process and fails the run; EAGLE never continues on CPU. These obsolete
keys are rejected, not migrated: `gpu_layers`, `threads`,
`parallel`, and `evaluation.match_workers`. The orchestrator validates runtime
files only outside mock mode, starts a fresh owned process per run, switches
models only at phase boundaries, waits for `/health` or `/v1/models`, verifies
a chat completion, runs search and the production final test, and stops its
owned process in `finally`.

```yaml
model:
  name: ministral3_8b
  path: experiment_env/model/ministral3-8b-instruct-q4-k-m/Ministral-3-8B-Instruct-2512-Q4_K_M.gguf
  llama_server: experiment_env/model/llama.cpp/llama.cpp/build-eagle/bin/llama-server
  port: 8080
generation_model:            # omit to use model for every phase
  name: qwen3.5_9b
  path: experiment_env/model/qwen3-5-9b-ud-q4-k-xl-q4-k-xl-bbcc0f54/model.gguf
  llama_server: experiment_env/model/llama.cpp/llama.cpp/build-eagle/bin/llama-server
  port: 8080
```

When a folder contains multiple YAML files, they run in filename order. Each
direct experiment run, including every `runs` replicate, stops the previous
owned `llama-server` and starts a fresh one from that run's resolved config
before search. A changed model or server profile also stops the owned runtime
before starting the replacement. Within a single dual-model experiment,
all offspring assignments are first fixed, all reflection/rewrite work runs on
`model`, and only then does the runtime switch to `generation_model` for final
materialization. It switches back before the next generation.

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

Match execution always uses ten bounded workers, with canonical results in
match_index order. Match worker count is fixed; resource tuning does not expose
a config override. match_timeout_seconds and match_artifact_mode remain
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
order or worker identity. LLM temperatures remain configurable.

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
```

The library is seeded at generation zero and admits runnable current parents at
each refresh boundary, retaining only one representative for each exact
semantic probe/action vector when the evidence is available. It deterministically
rotates the next active snapshot every five generations. Resume reloads the last
committed snapshot; older
self-play checkpoints that lack context metadata are migrated by re-evaluating
fresh-ID parent replicas against that snapshot before continuing.

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

If a config folder is also supplied, it is compatibility-checked against the run. Model identity/path/endpoint, EA parameters, evaluation matrix, and reflection mode/probabilities cannot silently change. Missing persisted model assets fail clearly. Only the latest atomically recorded generation is resumed; incomplete candidate work is recomputed.

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
