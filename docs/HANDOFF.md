# Handoff

## Current State

The active repo is a minimal prompt-to-Java-agent architecture. It no longer launches an LLM-controlled Java agent during MicroRTS matches.

The runnable path is:

```bash
python -m scripts.run_minimal_experiment --config configs/minimal_experiment.json
```

The default config is a dry run. It writes generated Java source under `agents/generated/` and reports compile and match commands without invoking `javac` or MicroRTS.

## What Works

- Candidate prompts are represented by `eagle.candidate.CandidatePrompt`.
- A small population loop evaluates candidates and mutates selected prompts.
- The `template` generation backend emits compilable-looking Java source that extends `RandomBiasedAI`.
- Generated Java source is written into the `ai.generated` package workspace.
- Evaluation produces explicit compile and match command plans.
- Unit tests cover source generation, parsing, workspace output, and the minimal dry-run experiment.

## What Is Stubbed

- The real LLM generation backend is not wired.
- Java compilation is planned but not run when `dry_run=true`.
- MicroRTS match execution is planned but not run when `dry_run=true`.
- Fitness is `0.0` in dry-run mode.
- Selection and mutation are intentionally simple smoke-path implementations.

## Next Steps

1. Add a real generation backend that turns candidate prompts into Java source.
2. Tighten Java validation beyond token checks.
3. Compile generated sources into a deterministic build directory.
4. Add a real MicroRTS match runner and confirm the correct Java main class for batch evaluation.
5. Parse real match results into fitness.
6. Replace the smoke mutation operator with prompt-aware mutation and crossover.
7. Add run artifact logging after the compile and match paths are real.

## Archive Notes

Old runtime LLM-agent control code lives in `archive/legacy_runtime/`. Treat it as reference material only. Do not reintroduce runtime LLM calls into the Java match agent unless the architecture direction changes again.
