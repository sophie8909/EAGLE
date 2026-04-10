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
  - policy-compiled surrogate games (`policy`)
  - sampled historical Dynamic Prompt replay (`game_round`)

---

## Repository Focus

If you are working on EAGLE, the main code lives in:

- `eagle/algorithm`
- `eagle/eval`
- `eagle/operator`
- `eagle/tools`

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

- `eagle/config.py`

Important settings:

- `algorithm`
- `population_size`
- `num_generations`
- `reproduction_operator_probs`
- `enable_reflection_operator`
- `reflection_max_components_to_rewrite`
- `crossover_mode`
- `steady_state_surrogate_offspring_count`
- `steady_state_surrogate_selection_metric`
- `real_eval_rate`
- `surrogate_version`
- `resource_advantage_alpha`
- `resource_advantage_weights`

### 3. Start an evolutionary run

From the repository root:

```bash
py -3 -m eagle.main
```

This will:

1. load prompt components from `eagle/prompts/components.json`
2. initialize a population
3. evolve prompts with GA, NSGA-II, or Steady-State NSGA-II
4. run real and surrogate evaluations
5. log generation results under `eagle/logs/<timestamp>`

---

## Core Workflow

### Prompt Representation

Each individual is represented by:

- `game_rule`
- `strategy: dict[str, int]`

The indices point into the component pool loaded from:

- `eagle/prompts/components.json`

Rendering happens in:

- `eagle/eval/evaluate.py`

### Evolutionary Algorithms

Supported algorithms:

- `GA`
- `NSGA2`
- `SteadyStateNSGA2`

Implemented in:

- `eagle/algorithm/ga.py`
- `eagle/algorithm/nsga2.py`
- `eagle/algorithm/steady_state_nsga2.py`

### NSGA-II vs Steady-State NSGA-II

- `NSGA2` uses generational replacement: it builds a full offspring population, then performs one environmental selection step over parents plus offspring.
- `SteadyStateNSGA2` keeps the same NSGA-II ranking logic, tournament policy, and crowding-based survivor selection, but each generation first generates multiple candidate children, surrogate-ranks them by `game_round_score`, then sends only the best candidate to full real evaluation and immediate replacement.
- Both variants still use the same three-objective fitness vector and the same real/surrogate evaluation pipeline.

### Steady-State Reproduction Flow

Steady-state NSGA-II now uses an operator-first offspring pipeline:

1. sample one reproduction operator
2. generate exactly one child with that operator
3. surrogate-evaluate the child
4. keep candidate metadata in `operator_profile`

Supported first-class reproduction operators:

- `crossover`: 2 parents, existing NSGA-II parent selection, current uniform crossover preserved
- `mutation`: 1 parent, standalone mutation operator
- `reflection`: 1 parent, conservative feedback-guided rewrite of a small number of strategy components

The steady-state selection pipeline after child creation is unchanged:

- generate a candidate batch
- surrogate-rank by `game_round_score`
- real-evaluate only the best candidate
- run standard NSGA-II survivor selection

### Operators

- parent selection: `eagle/operator/parent_selection.py`
- crossover: `eagle/operator/crossover.py`
- mutation: `eagle/operator/mutation.py`
- reflection: `eagle/operator/reflection.py`

### Reproduction Configuration

Steady-state operator sampling is controlled by:

```python
reproduction_operator_probs = {
    "crossover": 0.45,
    "mutation": 0.45,
    "reflection": 0.10,
}
enable_reflection_operator = True
reflection_max_components_to_rewrite = 1
crossover_mode = "uniform"
```

Rules:

- all three operator probabilities are configurable
- probability `0` means the operator is never sampled
- probabilities must sum to `1.0` within tolerance
- if `enable_reflection_operator` is `False`, reflection is excluded automatically and the remaining weights are renormalized
- invalid operator config fails during startup validation

Backward-compatible fallback for older saved configs that do not contain `reproduction_operator_probs`:

```python
{
    "crossover": 0.5,
    "mutation": 0.5,
    "reflection": 0.0,
}
```

### Reflection Operator

The first reflection scaffold is intentionally conservative:

- it uses one parent only
- it rewrites only a small subset of strategy components
- it prefers changing 1-2 components, not the whole prompt
- it uses compact summarized real-evaluation feedback instead of full raw logs or full raw LLM responses
- if no reflection context is available, it falls back safely to mutation and logs that fallback

### Evaluation

Evaluation orchestration:

- `eagle/eval/evaluate.py`

Supporting modules:

- real game launch and log retrieval: `eagle/tools/simulation_runner.py`
- fitness computation: `eagle/tools/fitness_calculator.py`
- single-round move validation: `eagle/tools/move_validator.py`
- surrogate logic: `eagle/surrogate/eval/evaluator.py`

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
surrogate_version = "policy"
```

or

```python
surrogate_version = "game_round"
```

### `policy`

Compiles the prompt into a fixed policy-style surrogate spec, renders the surrogate agent, and scores it through surrogate games.

### `game_round`

Samples Dynamic Prompt blocks from recent logs, combines them with the candidate prompt, asks the LLM for moves, validates those moves against the sampled round state, and uses the resulting score as the surrogate signal.

Relevant settings in `eagle/config.py`:

- `surrogate_recent_log_window`
- `surrogate_game_round_samples`
- `surrogate_log_dir`

---

## Logs and Outputs

Each run creates a log directory under:

- `eagle/logs/<timestamp>`

Typical contents:

- `config.json`
- `component_pool.json`
- `generation_<n>_mo.txt`
- `run_state.json`
- `checkpoints.jsonl`
- `profiles.jsonl`
- `generation_profiles.jsonl`

`run_state.json` keeps the latest resumable snapshot. `checkpoints.jsonl` appends one full checkpoint after each individual evaluation, so an interrupted run can continue from the middle of a generation instead of restarting that generation.

Resume commands:

```bash
py -3 -m eagle.main --resume-latest
```

or

```bash
py -3 -m eagle.main --resume-log-dir eagle/logs/20260405_123456
```

### Parsing and Reuse

Game log parsing:

- `eagle/tools/log_parse.py`

EA generation log parsing:

- `eagle/tools/ea_log_parse.py`

---

## Final Evaluation

To replay a saved final generation against the configured benchmark opponents, EAGLE uses:

- `eagle/eval/final_evaluation.py`

The `NSGA2` and `SteadyStateNSGA2` main flows already call final test at the end of a run.

---

## Result Test for One Generation

For ad hoc replay of a specific saved generation, use:

- `eagle/eval/result_test.py`

Example:

```bash
py -3 -m eagle.eval.result_test --log-dir eagle/logs/20260405_123456 --generation 10
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
eagle/
|- main.py                         # main run entry and algorithm dispatch
|- config.py                       # canonical EA configuration module
|- algorithm/
|  |- main.py                      # compatibility wrapper for older imports
|  |- basic_ea.py                  # shared EA runtime scaffold
|  |- ga.py                        # single-objective GA
|  |- nsga2.py                     # multi-objective NSGA-II
|  |- steady_state_nsga2.py        # steady-state multi-objective NSGA-II
|  `- test_steady_state_nsga2.py   # focused steady-state regression checks
|- eval/
|  |- evaluate.py                  # evaluation orchestrator
|  |- final_evaluation.py          # final replay evaluation
|  `- result_test.py               # replay a specific generation on demand
|- operator/
|  |- crossover.py                 # crossover operators
|  |- mutation.py                  # mutation operators
|  |- reflection.py                # reflection operator scaffold
|  |- parent_selection.py          # parent selection
|  `- environment_selection.py     # survivor selection helpers
|- tools/
|  |- config.py                    # compatibility shim for older config imports
|  |- individual.py                # candidate prompt representation
|  |- component_pool.py            # prompt component storage
|  |- simulation_runner.py         # launches MicroRTS and collects logs
|  |- fitness_calculator.py        # fitness computation
|  |- move_validator.py            # round-level move legality checks
|  |- log_parse.py                 # MicroRTS game log parsing
|  |- ea_log_parse.py              # EA generation log parsing
|  |- checkpoint.py                # checkpoint serialization
|  |- fitness_recorder.py          # history and record management
|  `- profiler.py                  # JSONL profiling helpers
`- surrogate/
   |- compiler/
   `- eval/
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

1. define or update prompt components in `eagle/prompts/components.json`
2. configure EA settings in `eagle/config.py`
3. run `py -3 -m eagle.main`
4. inspect generation logs and JSONL profiles
5. replay strong generations with `eagle/eval/result_test.py`
6. compare Pareto-front prompts and final replay outcomes

---

## Notes

- `llm_crossover` in `eagle/operator/crossover.py` is currently a documented placeholder and falls back to uniform crossover.
- `crossover_mode` is still the user-facing crossover switch, and the current stable implementation is `uniform`.
- reflection currently uses compact summary feedback from the parent's latest real evaluation instead of a full trajectory-level analysis.
- The current pipeline is organized so that `Evaluator` stays mostly orchestration, while parsing, surrogate scoring, and simulation launching live in separate modules.

---

## MicroRTS Attribution

MicroRTS originates from the research environment created by Santiago Ontanon.

If you use this repository in research, please cite the original MicroRTS work as well as your EAGLE-specific work or repository snapshot.
