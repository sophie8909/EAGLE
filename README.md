![EAGLE header](docs/assets/eagle-header.svg)

# EAGLE on MicroRTS

This repository is centered on **EAGLE**, an evolutionary prompt optimization pipeline built on top of **MicroRTS**.

EAGLE evolves prompt components for an LLM-based MicroRTS agent, evaluates them with both real game outcomes and surrogate estimators, and logs each generation for later replay and analysis.

---

## What EAGLE Does

EAGLE treats an agent prompt as a structured combination of:

- one stable `game_rule` component
- multiple evolvable `strategy` components

These components are recombined and mutated through evolutionary search, then scored with a multi-objective fitness function:

1. `win_score`
2. `resource_advantage_score`
3. `game_round_score`

The system supports both:

- real evaluation by launching actual MicroRTS games
- surrogate evaluation using either:
  - prompt-only LLM scoring (`llm`)
  - sampled historical Dynamic Prompt replay (`game_round`)

---

## Repository Focus

If you are working on EAGLE, the main code lives in:

- `eagle/ea`

The Java MicroRTS engine and LLM agents remain in the repository as the execution backend, but this README is organized around the EAGLE workflow first.

---

## Quick Start

### 1. Prepare the backend

EAGLE depends on the local MicroRTS runtime and your local LLM endpoint.

You should have:

- Java / MicroRTS build ready
- Ollama available at `http://localhost:11434`
- a model such as `llama3.1:8b` already pulled

Typical Ollama startup:

```bash
ollama serve
```

If you use the Java side LLM game agent directly, make sure the MicroRTS runner scripts and `resources/config.properties` are configured correctly.

### 2. Configure EAGLE

Main configuration lives in:

- `eagle/ea/config.py`

Important settings:

- `algorithm`
- `population_size`
- `num_generations`
- `real_eval_rate`
- `surrogate_version`
- `resource_advantage_alpha`
- `resource_advantage_weights`

### 3. Start an evolutionary run

From the repository root:

```bash
py -3 -m eagle.ea.main
```

This will:

1. load prompt components from `prompts/components.json`
2. initialize a population
3. evolve prompts with GA or NSGA-II
4. run real and surrogate evaluations
5. log generation results under `logs/<timestamp>`

---

## Core Workflow

### Prompt Representation

Each individual is represented by:

- `game_rule`
- `strategy: dict[str, int]`

The indices point into the component pool loaded from:

- `prompts/components.json`

Rendering happens in:

- `eagle/ea/evaluate.py`

### Evolutionary Algorithms

Supported algorithms:

- `GA`
- `NSGA2`

Implemented in:

- `eagle/ea/ga.py`
- `eagle/ea/nsga2.py`

### Operators

- parent selection: `eagle/ea/parent_selection.py`
- crossover: `eagle/ea/crossover.py`
- mutation: `eagle/ea/mutation.py`

### Evaluation

Evaluation orchestration:

- `eagle/ea/evaluate.py`

Supporting modules:

- real game launch and log retrieval: `eagle/ea/simulation_runner.py`
- fitness computation: `eagle/ea/fitness_calculator.py`
- single-round move validation: `eagle/ea/move_validator.py`
- surrogate logic: `eagle/ea/surrogate_evaluator.py`

---

## Fitness Design

EAGLE uses a three-objective fitness vector:

```python
[win_score, resource_advantage_score, game_round_score]
```

### 1. Win Score

Derived from the final winner in the game log.

### 2. Resource Advantage Score

Computed from the `Feature locations` section inside Dynamic Prompt blocks.

Per turn, EAGLE summarizes:

- `base`
- `worker`
- `light`
- `heavy`
- `ranged`
- `resource`

Then it applies a late-game-weighted normalized difference, keeping the score in `[-1, 1]`.

### 3. Game Round Score

Measures how valid and executable the LLM's per-round move outputs are.

This is used both:

- in real game log analysis
- in the `game_round` surrogate mode

---

## Surrogate Modes

Configure with:

```python
surrogate_version = "llm"
```

or

```python
surrogate_version = "game_round"
```

### `llm`

Prompt-only surrogate scoring using the local LLM.

### `game_round`

Samples Dynamic Prompt blocks from recent logs, combines them with the candidate prompt, asks the LLM for moves, validates those moves against the sampled round state, and uses the resulting score as the surrogate signal.

Relevant settings in `eagle/ea/config.py`:

- `surrogate_recent_log_window`
- `surrogate_game_round_samples`
- `surrogate_log_dir`

---

## Logs and Outputs

Each run creates a log directory under:

- `logs/<timestamp>`

Typical contents:

- `config.json`
- `component_pool.json`
- `generation_<n>_mo.txt`
- `profiles.jsonl`
- `generation_profiles.jsonl`

### Parsing and Reuse

Game log parsing:

- `eagle/ea/log_parse.py`

EA generation log parsing:

- `eagle/ea/ea_log_parse.py`

---

## Final Evaluation

To replay a saved final generation against the configured benchmark opponents, EAGLE uses:

- `eagle/ea/final_evaluation.py`

The `NSGA2` main flow already calls final test at the end of a run.

---

## Result Test for One Generation

For ad hoc replay of a specific saved generation, use:

- `eagle/ea/result_test.py`

Example:

```bash
py -3 -m eagle.ea.result_test --log-dir logs/20260405_123456 --generation 10
```

Default behavior:

- replays only `Pareto Front 1`
- writes results to:

```text
generation_10_front_1_result_test.json
```

Useful options:

```bash
--individual-id ind-42
--opponent ai.RandomAI
--all-fronts
--only-winning-individuals
--output custom_result.json
```

---

## Project Structure

### EAGLE Python pipeline

```text
eagle/ea/
|- main.py                  # entry point for EA runs
|- config.py                # EA, fitness, and surrogate settings
|- basic_ea.py              # shared EA runtime scaffold
|- ga.py                    # single-objective GA
|- nsga2.py                 # multi-objective NSGA-II
|- individual.py            # candidate prompt representation
|- component_pool.py        # prompt component storage
|- crossover.py             # crossover operators
|- mutation.py              # mutation operators
|- parent_selection.py      # parent selection
|- environment_selection.py # survivor selection helpers
|- evaluate.py              # evaluation orchestrator
|- simulation_runner.py     # launches MicroRTS and collects logs
|- fitness_calculator.py    # fitness computation
|- move_validator.py        # round-level move legality checks
|- surrogate_evaluator.py   # surrogate evaluation logic
|- log_parse.py             # MicroRTS game log parsing
|- ea_log_parse.py          # EA generation log parsing
|- final_evaluation.py      # final replay evaluation
|- result_test.py           # replay a specific generation on demand
|- fitness_recorder.py      # history and record management
|- profiler.py              # JSONL profiling helpers
`- test_parse_fitness.py    # regression-style parser/fitness tests
```

### MicroRTS backend

Relevant backend locations:

- `src`
- `resources/config.properties`
- `RunLoop.sh`
- `RunLoop_5000.sh`
- `maps`

---

## Typical Research Loop

1. define or update prompt components in `prompts/components.json`
2. configure EA settings in `eagle/ea/config.py`
3. run `py -3 -m eagle.ea.main`
4. inspect generation logs and JSONL profiles
5. replay strong generations with `eagle/ea/result_test.py`
6. compare Pareto-front prompts and final replay outcomes

---

## Notes

- `llm_crossover` in `eagle/ea/crossover.py` is currently a documented placeholder and falls back to uniform crossover.
- `test.py` in `eagle/ea` is kept as a compatibility shim.
- The current pipeline is organized so that `Evaluator` stays mostly orchestration, while parsing, surrogate scoring, and simulation launching live in separate modules.

---

## MicroRTS Attribution

MicroRTS originates from the research environment created by Santiago Ontanon.

If you use this repository in research, please cite the original MicroRTS work as well as your EAGLE-specific work or repository snapshot.
