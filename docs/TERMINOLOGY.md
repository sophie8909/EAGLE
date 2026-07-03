# Terminology

- Candidate prompt: The evolved text that asks a generation backend to produce Java MicroRTS agent source code.
- Generated Java agent: A Java class produced from a candidate prompt and intended to run inside MicroRTS.
- Evaluator: The Python component that compiles a generated Java agent, runs MicroRTS matches, and returns fitness.
- Fitness: The numeric score assigned to a candidate after evaluating its generated Java agent.
- Generation backend: The component that converts a candidate prompt into Java source code. The current `mock` backend is deterministic for local smoke runs.
- MicroRTS match: A game execution where a generated Java agent plays against a configured opponent in the MicroRTS engine.
- Archive code: Old implementation code retained under `archive/legacy_runtime/` for reference, but not part of the active architecture.
