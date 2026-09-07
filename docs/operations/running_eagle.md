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

The resolved `model` section selects the GGUF, llama-server executable, host, port, context size, GPU layers, threads, batch size, parallel slots, and health/startup timeouts. The orchestrator validates runtime files only outside mock mode, starts one owned process, waits for `/health` or `/v1/models`, verifies a chat completion, runs search and the production final test, and stops its owned process in `finally`.

When a folder contains multiple YAML files, they run in filename order. Adjacent
configs with an identical resolved model runtime reuse the already-started
`llama-server`; the manager starts it only once, while each search still performs
its normal LLM endpoint preflight. A changed model or server profile stops the
owned runtime before starting the next one.

Generation 0 is initialization. `generations: 20` therefore records generation 0 and performs evolutionary generations 1 through 20.

The resolved config records `survivor_selection: mu_plus_lambda`. Parent and
offspring candidates jointly enter seeded lexicase survivor selection. A config
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

Slot 1 uses the configured Worker Rush policy. Slots 2–10 are nine independent
LLM policy samples from the “Generate one RTS strategy” prompt; they are not
`RandomAI` agents. All ten generation-zero candidates directly use the same
Worker Rush Java phenotype. `initial_policy_max_attempts` bounds invalid or
duplicate policy-output retries, and the role-specific temperature controls
sampling diversity without changing EA randomness. Generation 1 resumes the
normal inherited-Java Generator path.

## Resume

Resume can target one run and uses its immutable run-local configuration:

```bash
./experiment.sh --resume runs/20260811_120000_000000
```

It can also continue a whole config-folder batch:

```bash
./experiment.sh --resume configs/experiments/static_0820/
```

Folder resume reads that directory's generated `experiment.yaml` index. It
first resumes indexed runs whose search or required final test is incomplete,
skips fully completed entries, and then starts the remaining unindexed configs
in filename order. It preserves and extends the existing index rather than
starting a fresh batch index. If the interrupted run has no atomically recorded
generation yet, the config restarts in a replacement run and the index is
updated to that new run directory.

If a config folder is also supplied, it is compatibility-checked against the run. Model identity/path/endpoint, EA parameters, evaluation matrix, and reflection mode/probabilities cannot silently change. Missing persisted model assets fail clearly. Only the latest atomically recorded generation is resumed; incomplete candidate work is recomputed.

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
code_reflection_probability: 0.80
prompt_compliance_reflection_probability: 0.00
aos_minimum_probability: 0.10
```

Strategy/Code/Prompt Compliance probabilities must sum to 1.0; they are fixed
in `static` and initial in either AOS mode. Set Prompt Compliance above zero to
audit and repair both prompt genes against the immutable gameplay/API contracts;
it does not consume W/D/L or match evidence. Every YAML creates fresh population, RNG,
operator controller/AOS state, archives, IDs, and run directory; only a
compatible LLM process may be reused.

The legacy `balance_reflection_probability` config key is accepted only as an
input alias for starting a fresh run and is resolved to
`prompt_compliance_reflection_probability`. Because the operator's meaning and
persisted state changed, a run containing the removed `balance_reflection`
operator state cannot be resumed as Prompt Compliance; start a new run instead.

There are no separate `run` or `runtime` compatibility entrypoints. The
experiment orchestrator is the only model/search lifecycle owner.
