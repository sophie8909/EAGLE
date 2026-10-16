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

## Framework startup

Fresh framework-slot runs bootstrap inline from `framework.design_brief` unless
an external `framework.bundle_path` is provided. Set
`framework.bootstrap_backend: local` to use the configured local llama-server
without an API key, `groq` to use the default Groq API path, or `mistral` to use
Mistral. For Groq, set `GROQ_API_KEY` in the process environment; for Mistral,
store the key in `api_key/mistral`. Do not put credentials in YAML, CLI
arguments, shell history, or artifacts. `framework.model` defaults to
`openai/gpt-oss-120b`; use `mistral-large-latest` with the Mistral backend. The standalone
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
  bootstrap_backend: mistral  # groq, mistral, or local
  design_brief: "Design a complete CandidateAgent framework with a rich finite control surface."
  model: mistral-large-latest
  evolution_mode: llm_coach
```

Set the top-level `model` profile for the experiment runtime as usual. Omit
`evolution_mode` for the local EA. To reuse a prepared bundle instead, replace
`design_brief` and `model` with `bundle_path: path/to/bundle.json`; optional
`bundle_version` and `bundle_sha256` fences may be used with that external file.

EAGLE validates an explicit external bundle during config resolution. For inline
bootstrap, it initializes bootstrap evidence and the manifest first,
then writes the resolved frozen config on success or requested pending config
after failure. Successful bootstrap validates and freezes the bundle at
`runs/<run_id>/framework/bundle.json` before search. Resume reads only the
frozen bundle and compares the design brief, bootstrap backend/model, and evolution
mode; it never regenerates the framework. Each fresh replicate bootstraps a
separate framework unless the same explicit bundle path is shared. Mock mode
rejects inline bootstrap without an existing bundle, ensuring no Groq request.
Failed attempts and a failed manifest remain; the pending config cannot resume
until a valid frozen bundle exists.

The `local` default samples finite slot values and uses seeded per-slot
crossover and one-slot mutation without candidate-time LLM requests.
`llm_coach` asks the experiment model for initial complete genomes and uses the
existing one-worst-match Commentator/Coach path for Strategy mutation. Neither
mode calls a Java Generator or repair model; rendering, validation, javac,
Integration, semantic probing, and the configured fixed-roster matrix remain
unchanged. See [framework slots](../architecture/framework_slots.md).
The resolved `model` section selects the GGUF, llama-server executable, host,
port, per-request context size, batch size, and health/startup timeouts. An
optional `generation_model` section has the same shape and selects the model for
final Java generation, deferred Code Reflection revision, and compile-guided
repair. Each section may contain `additional_endpoints`, an ordered list with at
most one unmanaged OpenAI-compatible endpoint expressed as exactly
`{base_url, model}`. Together with the managed local primary, a phase therefore
has one or two endpoints. GPU layers (`999`), model threads (`8`), managed-local server parallel slots (`2`),
independent LLM workers (`2`), and match workers (`10`) are fixed by
`eagle/execution.py`; they are not config fields. The server allocates
`context_size × 2`, while each request keeps the configured context size.
Before starting llama.cpp, GPU-device preflight must succeed. Every fresh child
startup must also emit positive full `offloaded N/N layers to GPU` evidence for the
selected model. Missing, stale, malformed, or partial offload evidence shuts down
the owned process and fails the run; EAGLE never continues on CPU. These obsolete
keys are rejected, not migrated: `gpu_layers`, `threads`,
`parallel`, and `evaluation.match_workers`. The orchestrator validates runtime
files only outside mock mode, starts a fresh owned local process per run,
switches managed models only at phase boundaries, and requires a successful
bounded chat completion from the primary and every additional endpoint before
phase work begins. Any endpoint failure is fail-closed. It runs search and the
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
materialization. It switches back before the next generation. Only the managed
local primary switches; any additional endpoint belongs to its declared phase
but remains an unmanaged service.

Within a phase, canonical input index selects the ordered endpoint slot modulo
the endpoint count. With one additional endpoint, the two LLM workers can issue
one local and one remote request concurrently, while results are still returned
in input order. The selected route remains fixed for dependent retries. EAGLE
does not fail over a request to the other endpoint, and the request log/timing
record stores the actual endpoint and model used.

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
