# Handoff

## Current State

The active repo is a minimal prompt-to-Java-agent architecture. It no longer launches an LLM-controlled Java agent during MicroRTS matches.

The runnable path is:

```bash
python scripts/run_eagle.py --config configs/eagle_minimal.yaml --mock
```

The mock path runs end to end without `javac` or MicroRTS. It writes run artifacts under `runs/<run_id>/`.

## What Works

- Candidate prompts are represented by `eagle.candidate.Candidate`.
- `eagle.search` runs initialization, generation, compile, match evaluation, elite selection, and mutation.
- The `mock` generation backend emits Java source that extends `RandomBiasedAI`.
- Generated Java source is written under each run's `generated_agents/` directory.
- Mock compile and match adapters produce structured results for local end-to-end runs.
- Unit tests cover config parsing, Java generation, and run artifact output.

## What Is Stubbed

- The OpenAI-compatible generation backend is implemented but not exercised by tests.
- Real Java compilation is implemented through `javac`, but the exact MicroRTS classpath may need adjustment in a real environment.
- The MicroRTS runner has an explicit TODO for the confirmed batch evaluation main class.
- Selection and mutation are intentionally simple.

## Next Steps

1. Confirm the MicroRTS batch evaluation main class and command-line contract.
2. Run one non-mock compile and match against the vendored MicroRTS tree.
3. Tighten Java validation beyond token checks.
4. Replace the simple mutation operator with prompt-aware mutation and crossover.
5. Add richer run artifact logging only after real match execution is stable.

## Archive Notes

Old runtime LLM-agent control code lives in `archive/legacy_runtime/`. Treat it as reference material only. Do not reintroduce runtime LLM calls into the Java match agent unless the architecture direction changes again.
