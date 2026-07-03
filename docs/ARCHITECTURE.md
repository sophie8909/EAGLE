# Architecture

EAGLE now treats prompts as source-code generators, not as runtime controllers.

## Pipeline

1. `eagle` creates a population of candidate prompts.
2. `generation` sends each prompt to a generation backend and receives Java source code.
3. `generation.validation` checks the source for the minimum expected Java agent structure.
4. `agents` writes the source into a generated Java workspace.
5. `evaluation` builds the Java compile plan, runs MicroRTS when `dry_run=false`, parses match output, and returns fitness.
6. `eagle` selects and mutates candidate prompts using fitness scores.

## Module Ownership

- `eagle/`: candidate representation, experiment config, population loop, selection, mutation, and orchestration.
- `generation/`: prompt-to-Java generation backend interface, template smoke backend, fenced-code parsing, and generated-source validation.
- `agents/`: filesystem workspace for generated Java agents.
- `evaluation/`: Java compile command construction, MicroRTS match command construction, match-score parsing, and fitness conversion.
- `configs/`: experiment config files for the active architecture.
- `scripts/`: runnable entry points. `scripts/run_minimal_experiment.py` is the active smoke runner.
- `docs/`: architecture and handoff documentation for future coding models.
- `archive/`: old runtime LLM-agent control code and previous framework surfaces.

## Data Flow

```text
candidate prompt
  -> generation backend
  -> Java source code
  -> source validation
  -> agents/generated/src/ai/generated/*.java
  -> javac compile plan
  -> MicroRTS match plan
  -> match score
  -> fitness
  -> selection and mutation
```

## Removed Or Archived Design

The previous design kept an LLM in the match loop. Java classes under `ai.eagle` loaded a prompt, called a llama.cpp-compatible endpoint during gameplay, parsed JSON moves, and applied actions in real time. That path is no longer active.

Old Python plugin, GUI, surrogate, round-evaluation, LLM-call logging, and compatibility layers were moved to `archive/legacy_runtime/`. The old Java runtime LLM agent sources were also moved there. The vendored MicroRTS engine remains under `third_party/microrts/`.
