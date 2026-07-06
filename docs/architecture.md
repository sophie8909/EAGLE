# EAGLE Architecture

EAGLE is a small research pipeline that evolves text prompts. Each prompt is used to generate a Java MicroRTS agent, compile it, run matches, score the result, and select the next prompt population with NSGA-II.

## Current Flow

1. `scripts/run_eagle.py` parses CLI arguments, loads a config file, and calls `run_search()`.
2. `eagle/config.py` reads the YAML or JSON config and expands the seed prompt template.
3. `eagle/search.py` creates the run directory, initializes the first population, and runs the generation loop.
4. `eagle/evaluation.py` evaluates each candidate prompt.
5. `generation/java_agent_generator.py` asks the generation backend for Java, cleans/validates the source, and writes one Java file.
6. `evaluation/compiler.py` compiles the generated Java agent.
7. `evaluation/microrts_runner.py` runs MicroRTS matches, or returns deterministic mock results in mock mode.
8. `eagle/evaluation.py` computes game metrics, strategy alignment, and final objective values.
9. `eagle/offspring.py` creates child prompts through simple text crossover and mutation.
10. `eagle/selection.py` ranks candidates with Pareto sorting and crowding distance, then selects the next generation.
11. `eagle/artifacts.py` writes run summaries, per-candidate files, and JSONL results.

## Module Map

### `scripts/run_eagle.py`

Owns: CLI argument parsing and printing the final run directory/best candidate.

Should not own: search logic, config defaults, evaluation, or artifact formats.

Edit here when: adding a command-line flag or changing the final console output.

### `eagle/search.py`

Owns: the high-level experiment loop, run directory setup, population initialization, and wiring together evaluation, offspring, selection, and artifacts.

Should not own: candidate evaluation details, Java generation, NSGA-II internals, artifact JSON formats, or prompt mutation text.

Edit here when: changing the order of the experiment loop or adding a new top-level phase.

### `eagle/evaluation.py`

Owns: evaluating one candidate or one population: Java generation, compilation, MicroRTS match execution, alignment scoring, objective computation, and progress printing.

Should not own: population initialization, offspring creation, NSGA-II selection, or artifact schemas beyond calling artifact writers.

Edit here when: changing how candidates are scored, how compile failures are handled, or what happens during one candidate evaluation.

### `eagle/offspring.py`

Owns: simple prompt crossover, prompt mutation, and child `Candidate` creation.

Should not own: parent selection rules, objective comparison, or candidate evaluation.

Edit here when: changing mutation text, crossover text, or how child prompts are formed.

### `eagle/selection.py`

Owns: tournament parent selection, Pareto dominance, non-dominated sorting, crowding distance, best-candidate choice, and next-generation selection.

Should not own: prompt mutation/crossover, Java evaluation, or artifact writing.

Edit here when: changing NSGA-II behavior or how parents/survivors are chosen.

### `eagle/artifacts.py`

Owns: writing `results.jsonl`, generation manifests, summary JSON, and per-candidate artifact files.

Should not own: evaluation decisions, objective computation, or selection logic.

Edit here when: changing files under `runs/<run_id>/`.

### `eagle/candidate.py`

Owns: the `Candidate` dataclass and objective vector helper.

Should not own: evaluation, mutation, selection, or serialization policy beyond `to_json_dict()`.

Edit here when: adding or removing fields stored on each candidate.

### `eagle/config.py`

Owns: experiment config loading, defaults, minimal YAML parsing, and basic config validation.

Should not own: runtime behavior, CLI parsing, or generated artifact formats.

Edit here when: adding a config field or changing defaults.

### `generation/java_agent_generator.py`

Owns: turning backend output into a cleaned, validated Java source file.

Should not own: LLM HTTP transport, MicroRTS match running, or objective scoring.

Edit here when: changing generated Java cleanup, validation, source repair, or output paths.

### `evaluation/compiler.py`

Owns: building and running the `javac` command for one generated Java agent.

Should not own: source generation, match execution, or objective scoring.

Edit here when: changing Java classpaths, compiler flags, or mock compile behavior.

### `evaluation/microrts_runner.py`

Owns: building and running the MicroRTS match command, reading match result JSON, and deriving a raw match score.

Should not own: Java generation, compilation, aggregate metrics, or NSGA-II objective selection.

Edit here when: changing the MicroRTS command, map, result parsing, or mock match payload.

## Where Common Changes Go

- Change the run loop: `eagle/search.py`
- Change seed config or config defaults: `eagle/config.py`
- Change generated Java cleanup/validation: `generation/java_agent_generator.py`
- Change LLM generation transport or prompt wrapper: `generation/backend.py`
- Change match scoring inputs: `evaluation/microrts_runner.py` or `evaluation/game_metrics.py`
- Change objective values: `evaluation/nsga2_objectives.py`
- Change mutation/crossover text: `eagle/offspring.py`
- Change selection behavior: `eagle/selection.py`
- Change run output files: `eagle/artifacts.py`
