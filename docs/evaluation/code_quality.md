# Code-quality diagnostics

`evaluation/code_quality.py` calculates deterministic simplicity and retains
compiler, validation, function-capability, and strategy-alignment evidence.
The resulting `code_quality` value is diagnostic only. It is not in
`Candidate.objective_vector()` and is not used by lexicase or survivor
selection.

For a valid candidate, the current simplicity calculation remains:

```text
complexity_penalty =
    40 * normalized_cyclomatic
  + 25 * normalized_nesting
  + 20 * normalized_logical_loc
  + 15 * normalized_longest_function

code_quality = 100 - complexity_penalty
```

The detailed breakdown is persisted in
`candidates/<id>/evaluation/code_quality.json`. Generation, validation,
compilation, integration, runtime, and incomplete-evaluation failures retain
their diagnostics and receive `-1000.0` for each opponent fitness case.

Reflection can inspect these diagnostics through `CodeDiagnostics` in
`eagle/reflection_context.py`, but no diagnostic is silently converted into an
evolutionary objective.
