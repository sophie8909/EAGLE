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

## Resume

Resume uses the immutable run-local configuration, not the original folder:

```bash
./experiment.sh --resume runs/20260811_120000_000000
```

If a config folder is also supplied, it is compatibility-checked against the run. Model identity/path/endpoint, EA parameters, evaluation matrix, and reflection mode/probabilities cannot silently change. Missing persisted model assets fail clearly. Only the latest atomically recorded generation is resumed; incomplete candidate work is recomputed.

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
aos_minimum_probability: 0.10
```

Strategy/Code probabilities are fixed in `static` and initial in either AOS mode. Every YAML creates fresh population, RNG, operator controller/AOS state, archives, IDs, and run directory; only a compatible LLM process may be reused.

There are no separate `run` or `runtime` compatibility entrypoints. The
experiment orchestrator is the only model/search lifecycle owner.
