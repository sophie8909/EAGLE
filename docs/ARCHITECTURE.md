# Architecture

EAGLE now treats prompts as source-code generators, not as runtime controllers.

## Pipeline

1. `eagle` creates a population of candidate prompts.
2. `generation` sends each prompt to a generation backend and receives Java source code.
3. `generation.java_agent` extracts Java code, checks the minimum expected Java agent structure, and writes it into the run workspace.
4. `evaluation.compiler` compiles the generated source, or returns a structured mock compile result when `--mock` is used.
5. `evaluation.microrts_runner` runs MicroRTS matches, or returns structured mock match scores when `--mock` is used.
6. `eagle` selects and mutates candidate prompts using fitness scores.

## Module Ownership

- `eagle/`: candidate representation, experiment config, search loop, selection, mutation, and orchestration.
- `generation/`: prompt-to-Java generation backend interface, mock backend, OpenAI-compatible backend, fenced-code parsing, and generated-source validation.
- `agents/`: filesystem workspace for generated Java agents.
- `evaluation/`: Java compilation, MicroRTS match adapter, match-score parsing, and fitness conversion.
- `configs/`: experiment config files for the active architecture.
- `scripts/`: runnable entry points. `scripts/run_eagle.py` is the active runner.
- `docs/`: architecture and handoff documentation for future coding models.
- `archive/`: old runtime LLM-agent control code and previous framework surfaces.

## Data Flow

```text
candidate prompt
  -> generation backend
  -> Java source code
  -> source validation
  -> runs/<run_id>/generated_agents/<candidate_id>/src/ai/generated/*.java
  -> javac compile result
  -> MicroRTS match result
  -> match score
  -> fitness
  -> selection and mutation
```

## Run Artifacts

```text
runs/<run_id>/
  config.yaml
  candidates/
  generated_agents/
  results.jsonl
  summary.json
```

## Removed Or Archived Design

The previous design kept an LLM in the match loop. Java classes under `ai.eagle` loaded a prompt, called a llama.cpp-compatible endpoint during gameplay, parsed JSON moves, and applied actions in real time. That path is no longer active.

Old Python plugin, GUI, surrogate, round-evaluation, LLM-call logging, and compatibility layers were moved to `archive/legacy_runtime/`. The old Java runtime LLM agent sources were also moved there. The vendored MicroRTS engine remains under `third_party/microrts/`.
