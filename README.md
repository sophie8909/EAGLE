![EAGLE header](docs/assets/eagle-header.svg)

# EAGLE

EAGLE is the main project in this repository. MicroRTS is treated as a vendored third-party environment under `third_party/microrts`, while the Python-side research workflow lives under `eagle/`.

## Repository Structure

```text
EAGLE/
|- README.md
|- requirements.txt
|- pyproject.toml
|- configs/
|  |- evolution/
|  |- evaluation/
|  `- experiments/
|- eagle/
|  |- __init__.py
|  |- config.py
|  |- main.py
|  |- project.py
|  |- evolution/
|  |- evaluation/
|  |- surrogate/
|  |- prompts/
|  |- analysis/
|  |- utils/
|  `- envs/
|     `- microrts/
|        |- adapter.py
|        |- compiler.py
|        |- parser.py
|        `- runner.py
|- scripts/
|  |- run_evolution.py
|  |- run_surrogate_validation.py
|  |- run_prompt_eval.py
|  |- analyze_results.py
|  `- legacy/
|- third_party/
|  `- microrts/
|- logs/
|  |- eagle/
|  `- microrts/
|- results/
|- responses/
|- history/
`- tests/
```

## EAGLE and MicroRTS

- `eagle/` contains the Python research code: EA search, evaluation, surrogate tooling, analysis, and shared utilities.
- `third_party/microrts/` contains the Java RTS environment, maps, resources, jars, and Java-side EAGLE agent code.
- `eagle/envs/microrts/` is the adapter layer that centralizes MicroRTS root discovery, Java compilation, runtime execution, and log parsing.
- New Python code should call the adapter layer instead of hardcoding MicroRTS paths.

Important EAGLE-specific Java classes are still kept inside the vendored MicroRTS tree for compatibility:

- `third_party/microrts/src/ai/abstraction/EAGLE.java`
- `third_party/microrts/src/ai/abstraction/EAGLESurrogate.java`

## Configs

`configs/` is now part of the active workflow rather than just a placeholder.

- `configs/evolution/default.json`
  Base config used by `scripts.run_evolution` when `--config` is not provided.
- `configs/evaluation/surrogate_validation.json`
  Base config used by `scripts.run_surrogate_validation` when `--config` is not provided.
- `configs/evaluation/final_test.json`
  Replay/final-test override config used by `scripts.run_prompt_eval` and final benchmark replays.
- `configs/experiments/`
  Experiment-specific artifacts and reference materials.

Current behavior:

- `scripts.run_evolution` loads `configs/evolution/default.json` by default.
- `scripts.run_surrogate_validation` loads `configs/evaluation/surrogate_validation.json` by default.
- Saved run directories still keep their own `config.json`, and resume mode uses the saved run config first.

## Environment Setup

1. Create and activate a Python environment.
2. Install Python dependencies:

```bash
pip install -r requirements.txt
```

3. Make sure `java` and `javac` are available on `PATH`.
4. If you use the LLM-backed agents, make sure Ollama is reachable from the environment where you run EAGLE.
5. Run all commands from the repository root.

## Compile MicroRTS

The preferred compile path is now the Python adapter, which targets `third_party/microrts`.

```python
from eagle.envs.microrts import compile_microrts

compile_microrts()
```

This compiles Java sources from `third_party/microrts/src` and writes classes into `third_party/microrts/bin`.

## Main Scripts

The primary user-facing entrypoints are under `scripts/`.

### 1. `scripts.run_evolution`

Run the main EA workflow:

```bash
python -m scripts.run_evolution
```

Useful examples:

```bash
python -m scripts.run_evolution --quick-run --timeout-sec 60 --skip-final-test
python -m scripts.run_evolution --config configs/evolution/default.json
python -m scripts.run_evolution --algorithm steady_state_nsga2
python -m scripts.run_evolution --resume-latest
python -m scripts.run_evolution --resume-log-dir logs/<run_dir>
python -m scripts.run_evolution --opponent ai.PassiveAI
```

Key options:

- `--config`: load one base config JSON file
- `--quick-run`: run a minimal end-to-end EA benchmark
- `--timeout-sec`: override per-game timeout
- `--skip-final-test`: skip the extra final replay stage
- `--resume-latest`: resume the newest run under `logs/`
- `--resume-log-dir`: resume a specific log directory
- `--opponent`: use one specific opponent class

Outputs:

- per-run logs under `logs/eagle/<timestamp>/`
- generation summaries, profiles, checkpoints, and run state in the run directory

Fitness conventions:

- Raw single-match evaluation uses `match_score = [win_score, resource_score]`.
- `win_score` is the game outcome signal from one match.
- `resource_score` is the weighted final resource/material advantage from that same match.
- Some result files still keep legacy `fitness` / `fitness_score` aliases for backward compatibility, but new code should treat these as `match_score`.
- EA-level search fitness used by `ga`, `nsga2`, and `steady_state_nsga2` stores one scalar per configured opponent slot.
- With the default config, EA-level fitness is `[LightRush_score, HeavyRush_score]`.
- Each opponent score is computed as `resource_score + resource_advantage_alpha * win_score`.
- `resource_advantage_alpha` therefore acts as the win bonus weight inside the EA search objective.

### 2. `scripts.run_surrogate_validation`

Compare prompt-based EAGLE evaluation with surrogate-Java evaluation:

```bash
python -m scripts.run_surrogate_validation
```

Useful examples:

```bash
python -m scripts.run_surrogate_validation --smoke-test
python -m scripts.run_surrogate_validation --quick-run --timeout-sec 60
python -m scripts.run_surrogate_validation --config configs/evaluation/surrogate_validation.json
python -m scripts.run_surrogate_validation --opponent ai.PassiveAI
python -m scripts.run_surrogate_validation --num-individuals 3
```

Key options:

- `--config`: load one surrogate-validation config JSON file
- `--smoke-test`: verify prompt/spec generation and MicroRTS wiring without launching games
- `--quick-run`: run one individual against one opponent using real matches
- `--timeout-sec`: override per-game timeout
- `--opponent`: add one or more opponents
- `--num-individuals`: control how many sampled prompts are benchmarked

Outputs:

- run logs under `logs/eagle/surrogate_validation_<timestamp>/`
- alignment summary between EAGLE and surrogate-Java evaluation

### 3. `scripts.run_prompt_eval`

Replay saved individuals from a previous EA run:

```bash
python -m scripts.run_prompt_eval --log-dir logs/<run_dir> --generation <N>
```

Useful examples:

```bash
python -m scripts.run_prompt_eval --log-dir logs/<run_dir> --generation 1
python -m scripts.run_prompt_eval --config configs/evaluation/final_test.json --log-dir logs/<run_dir> --generation 1
python -m scripts.run_prompt_eval --log-dir logs/<run_dir> --generation 1 --opponent ai.RandomAI
python -m scripts.run_prompt_eval --log-dir logs/<run_dir> --generation 1 --individual-id ind-3
python -m scripts.run_prompt_eval --log-dir logs/<run_dir> --generation 1 --max-front 3
python -m scripts.run_prompt_eval --log-dir logs/<run_dir> --generation 1 --all-fronts
```

Key options:

- `--log-dir`: path to one EA run directory
- `--generation`: saved generation number to replay
- `--opponent`: override the benchmark opponent list
- `--individual-id`: replay only one individual
- `--max-front`: replay Pareto Front 1 up to N
- `--all-fronts`: replay every saved individual in the generation
- `--config`: optional replay/final-test override JSON for `run_time_per_game_sec`
  and `llm_intervals`
- `--output`: write results to a custom JSON path

Outputs:

- a JSON result file in the run directory unless `--output` is provided

## Output Locations

- EAGLE run logs: `logs/eagle/<timestamp>/`
- Surrogate validation logs: `logs/eagle/surrogate_validation_<timestamp>/`
- MicroRTS runtime logs: `logs/microrts/*.log`
- Response CSV files: `responses/`
- Analysis outputs: `results/analysis/`
- Legacy archived files: `results/legacy_archive/`
- Cross-run fitness history: `history/fitness_history.jsonl`

## Notes

- `scripts/legacy/` contains older helper scripts that were kept for reference.
- Some result metadata still uses legacy field names such as `runner_script`, even though the actual runtime path is now the Python adapter.
- The active MicroRTS location is `third_party/microrts`. The old root-level MicroRTS copy has been removed.
