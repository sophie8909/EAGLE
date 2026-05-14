# EAGLE

EAGLE is the main project in this repository. MicroRTS is treated as a vendored third-party environment under `third_party/microrts`, while the Python-side research workflow lives under `eagle/`.


## GUI Usage

The GUI is a native local desktop window implemented with Python `tkinter`. It does not run through a browser or a web server.

Start it from the repository root with either command:

```bash
./run.sh
```

```bash
python -m eagle_gui.app
```

On Windows, this also works after activating the environment:

```powershell
py -3 -m eagle_gui.app
```

Main GUI functions:

- `Components`: edit prompt components, choose candidates, preview the rendered prompt, and mark components as static.
- `Algorithm`: choose algorithm settings such as GA/NSGA-II, population size, generations, surrogate mode, tick/LLM-call limits, and quick-run options.
- `Objectives`: choose objective scoring and target opponents.
- `Operators`: choose crossover and mutation operators, including weighted mutation modes.
- `Run`: save the generated config, start or stop an experiment, and view process output.
- `Live Analysis`: watch run progress from `logs/eagle/`.
- `Prompts`: inspect prompts saved in generation logs and checkpoints.

Pressing `Save generated config` writes the current settings to:

```text
configs/experiments/<config_name>.json
```

Pressing `Start experiment` saves that config and launches EAGLE with the selected algorithm, evaluator, and surrogate settings.
The GUI includes a `Time Analysis` tab that reads the selected run's timing artifacts and profile rows.
Round evaluation defaults to 8 samples with up to 8 parallel workers for fresh round evaluations.

```bash
python -m eagle.main --config configs/experiments/<config_name>.json --algorithm <algorithm> --evaluator <evaluator>
```

The run writes normal EAGLE artifacts under `logs/eagle/<timestamp>/`.

Notes:

- Run the GUI from the repository root so relative config, log, component, and MicroRTS paths resolve correctly.
- The desktop GUI uses `tkinter`, which is bundled with normal Python installations. If your Python distribution omits Tk support, install the Tk package for that distribution.
- Java-backed MicroRTS validation still requires `java` and `javac` on `PATH`.
- LLM-backed mutation, reflection, and evaluation paths still require Ollama to be reachable from the environment that starts the desktop GUI.


## Repository Structure

```text
EAGLE/
|- README.md
|- requirements.txt
|- environment.yml
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
|  |- eval/
|  |  |- base.py
|  |  `- microrts/
|  |     |- full_game_evaluator.py
|  |     |- round_evaluator.py
|  |     |- final_test_runner.py
|  |     |- generation_replay.py
|  |     `- surrogate_validation.py
|  |- operators/
|  |  `- component/
|  |- reflection/
|  |  `- microrts/
|  |- surrogate/
|  |- prompts/
|  |- analysis/
|  |- experiment/
|  |- domains/
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
|  |- analyze_evolution_results.py
|  |- export_final_prompt.py
|  `- organize_microrts_logs.py
|- eagle_gui/
|  |- app.py
|  `- desktop_app.py
|- third_party/
|  `- microrts/
|- logs/
|  |- eagle/
|  `- microrts/
|     `- round_evol/
|- results/
|- responses/
|- history/
`- tests/
```

## EAGLE and MicroRTS

- `eagle/` contains the Python research code: EA search, evaluation, surrogate tooling, analysis, and shared utilities.
- `third_party/<app>/` is reserved for vendored or local third-party applications. MicroRTS currently lives at `third_party/microrts/`.
- `eagle/domains/<app>/` is the application adapter layer. It exposes the application root, compile/setup hooks, and domain registration.
- `eagle/envs/<app>/` centralizes low-level runtime helpers such as process launch, compilation, and log parsing.
- `eagle/eval/base.py` contains the shared evaluator contract. `eagle/eval/<app>/` contains application-specific evaluation code. MicroRTS full-game, round-state, replay, final-test, and surrogate-validation flows live in `eagle/eval/microrts/`.
- `eagle/reflection/` contains the shared reflection contracts, while `eagle/reflection/<app>/` provides application-specific reflection context.
- `eagle/evolution/component/` contains the application-neutral component GA/NSGA-II framework, component individuals, selection, and generation-log parsing.
- `eagle/operators/component/` contains reusable component-level mutation and crossover operators.
- New Python code should call the adapter/eval/reflection layers instead of hardcoding MicroRTS paths.
- The vendored MicroRTS tree has been trimmed to the EAGLE runtime and the five opponent agents used by the EAGLE workflow: `ai.PassiveAI`, `ai.RandomAI`, `ai.RandomBiasedAI`, `ai.abstraction.HeavyRush`, and `ai.abstraction.LightRush`.

Important EAGLE-specific Java classes are still kept inside the vendored MicroRTS tree:

- `third_party/microrts/src/ai/abstraction/EAGLE.java`
- `third_party/microrts/src/ai/abstraction/eaglePolicy.java`

Surrogate Java paths use explicit names:

- `eaglePolicy.java`: reusable fixed-template policy path. Python compiles a prompt into a small policy schema, converts it into Java constants, and repeatedly injects those constants plus the prompt into the stable `third_party/microrts/src/ai/abstraction/eaglePolicy.java` template.
- `eagleJava.java`: direct Java-generation path. Python compiles the same fixed policy spec, renders a standalone `eagleJava.java` class with the same concrete behavior as `eaglePolicy.java`, compiles it as `ai.abstraction.eagleJava`, and runs that generated agent.

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

The recommended setup is Conda because real MicroRTS matches require both Python packages and a JDK with `java`/`javac`.

```bash
conda env create -f environment.yml
conda activate eagle
```

`requirements.txt`, `pyproject.toml`, and `environment.yml` are kept aligned for the Python package set. `environment.yml` additionally installs the JDK needed by MicroRTS.

Python dependencies:

- Python `>=3.10,<3.13`
- `matplotlib` for analysis plots
- `Pillow` for GIF generation in evolution-result analysis
- `PyYAML` for YAML experiment configs
- `requests` for Ollama and local HTTP calls

Conda-only runtime dependency:

- `openjdk>=17` for MicroRTS compilation and runtime

If you are not using Conda, install Python dependencies with pip and install a JDK separately:

```bash
pip install -r requirements.txt
```

Then make sure `java` and `javac` are available on `PATH`.

If you use LLM-backed mutation, reflection, or evaluation paths, make sure Ollama is reachable from the environment where you run EAGLE. Run all commands from the repository root.

## Quick Start with `run.sh`

`run.sh` opens the native EAGLE desktop GUI from the repository root.

If your environment is already ready:

```bash
./run.sh
```

If you want the script to check or create the Conda environment first:

```bash
./run.sh --setup
```

If you also want to reinstall Python packages:

```bash
./run.sh --setup --install
```

Notes:

- Run the script from the repository root.
- The script expects a Bash-compatible shell such as Git Bash, WSL, or a Unix shell.
- `./run.sh` uses the current active `python`.
- Java-backed MicroRTS runs still need `java` and `javac` on `PATH`.

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
python -m scripts.run_evolution --quick-run --tick-limit 60 --skip-final-test
python -m scripts.run_evolution --config configs/evolution/default.json
python -m scripts.run_evolution --algorithm round_nsga2
python -m scripts.run_evolution --resume-latest
python -m scripts.run_evolution --resume-log-dir logs/<run_dir>
python -m scripts.run_evolution --opponent ai.PassiveAI
python -m scripts.run_evolution --precompile-python
```

Key options:

- `--config`: load one base config JSON file
- `--quick-run`: run a minimal end-to-end EA benchmark
- `--tick-limit`: override per-game MicroRTS ticks
- `--skip-final-test`: skip the extra final replay stage
- `--resume-latest`: resume the newest run under `logs/`
- `--resume-log-dir`: resume a specific log directory
- `--opponent`: use one specific opponent class
- `--precompile-python`: compile EAGLE Python modules to bytecode before launch; useful for startup/import overhead, not Java or LLM time

Outputs:

- per-run logs under `logs/eagle/<timestamp>/`
- generation summaries, profiles, checkpoints, and run state in the run directory
- timing events, `timing_summary.json`, and `timing_report.md` in the run directory

Fitness conventions:

- Raw single-match evaluation uses `match_score = [win_score, resource_score]`.
- `win_score` is the game outcome signal from one match.
- `resource_score` is the weighted final resource/material advantage from that same match.
- New result readers should treat `match_score` as the canonical raw single-match score field.
- EA-level search fitness used by `round_ga` and `round_nsga2` stores one scalar per configured objective slot.
- The slot order is read from `gameplay_opponents` in the run config.
- With the default config, EA-level fitness is `[LightRush_score, HeavyRush_score]`.
- With `surrogate=round`, each opponent score is `raw_resource_advantage_score`.
- With `surrogate=policy_agent` or `surrogate=java_agent`, each opponent score is `win_score`.
- `resource_advantage_alpha` remains the separate parameter used inside resource-advantage scoring.
- `win_bonus` is the win bonus weight inside the EA search objective.
- Gameplay evaluation always uses the full ordered `gameplay_opponents` list from config; it does not sample a random opponent.

### 2. `scripts.run_surrogate_validation`

Compare prompt-based EAGLE evaluation with `eaglePolicy` evaluation:

```bash
python -m scripts.run_surrogate_validation
```

Useful examples:

```bash
python -m scripts.run_surrogate_validation --smoke-test
python -m scripts.run_surrogate_validation --quick-run --tick-limit 60
python -m scripts.run_surrogate_validation --config configs/evaluation/surrogate_validation.json
python -m scripts.run_surrogate_validation --opponent ai.PassiveAI
python -m scripts.run_surrogate_validation --num-individuals 3
```

Key options:

- `--config`: load one surrogate-validation config JSON file
- `--smoke-test`: verify prompt/spec generation and MicroRTS wiring without launching games
- `--quick-run`: run one individual against one opponent using real matches
- `--tick-limit`: override per-game MicroRTS ticks
- `--opponent`: add one or more opponents
- `--num-individuals`: control how many sampled prompts are benchmarked

Outputs:

- run logs under `logs/eagle/surrogate_validation_<timestamp>/`
- alignment summary between EAGLE and `eaglePolicy` evaluation

### 3. `eagle.eval.microrts.run_round_evolution`

Run the round-level GA/NSGA-II workflow:

```bash
python -m eagle.eval.microrts.run_round_evolution
```

Useful examples:

```bash
python -m eagle.eval.microrts.run_round_evolution --quick-run
python -m eagle.eval.microrts.run_round_evolution --algorithm round_ga
python -m eagle.eval.microrts.run_round_evolution --algorithm round_nsga2 --model llama3.1:8b
python -m eagle.eval.microrts.run_round_evolution --config configs/evolution/microrts_round.json
```

Outputs:

- generation summaries under `logs/eagle/<timestamp>/`
- round prompt history under `logs/microrts/round_evol/history.jsonl`

### 4. `scripts.run_prompt_eval`

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
- `--config`: optional replay/final-test override JSON for `tick_limit`,
  `llm_call_limit`, and `llm_intervals`
- `--output`: write results to a custom JSON path

Outputs:

- a JSON result file in the run directory unless `--output` is provided

## Output Locations

- EAGLE run logs: `logs/eagle/<timestamp>/`
- Surrogate validation logs: `logs/eagle/surrogate_validation_<timestamp>/`
- MicroRTS runtime logs: `logs/microrts/<YYYY-MM-DD>/`
- Response CSV files: `responses/`
- Analysis outputs: `results/analysis/`
- Cross-run fitness history: `history/fitness_history.jsonl`
