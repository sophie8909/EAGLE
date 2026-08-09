# `code_quality` / simplicity

`code_quality` is a maximized objective. The active scorer is
`evaluation/canonical_code_quality.py`; `evaluation/code_quality.py` supplies
the deterministic static metrics used by it.

## Valid candidates

For a candidate that passes generation, extraction, validation, compilation,
integration, and the complete match batch:

```text
complexity_penalty =
    40 * normalized_cyclomatic
  + 25 * normalized_nesting
  + 20 * normalized_logical_loc
  + 15 * normalized_longest_function

code_quality = 100 - complexity_penalty
```

The current metric version (`1`) normalizes
cyclomatic complexity after the baseline value 1 over 39 points, maximum
nesting depth after the method-body baseline 1 over 9 points, logical LOC
after the first executable line over 299 points, and longest function LOC
after the first line over 119 points. Each normalized value is clamped to `[0, 1]`; the four penalty fields and
the final score are rounded to six decimal places.

The measured source is the candidate's generated methods under the
`candidate_generated_methods` label. `logical_loc` is the count of nonblank,
non-brace executable lines after comments and literals are stripped. The
longest-function metric is a lexical Java-method estimate.

Every valid score persists `code_quality_details` with:

```json
{
  "complexity_penalty": 32.187179,
  "cyclomatic_complexity": 20,
  "maximum_nesting_depth": 3,
  "logical_loc": 48,
  "longest_function_loc": 16,
  "cyclomatic_penalty": 19.487179,
  "nesting_penalty": 7.5,
  "logical_loc_penalty": 3.2,
  "longest_function_penalty": 2.0,
  "metric_version": "1",
  "measured_source": "candidate_generated_methods"
}
```

Compiler warnings, compiler errors, function capability, missing/invalid
functions, validation diagnostics, runtime diagnostics, and Strategy
Alignment remain persisted diagnostic evidence. They do not contribute to a
valid simplicity score. Strategy Alignment is not an optimizer objective.

## Failed candidates

Generation, extraction, validation, compilation, integration, runtime,
timeout, and incomplete evaluations receive `-1000` for both
`game_performance` and `code_quality`. The failure stage and all available
complexity/diagnostic evidence are retained separately.

## Objective ownership

`evaluation/nsga2_objectives.py` exposes exactly two maximized objectives:
`game_performance` and `code_quality`. Selection, Pareto sorting, tournament
comparison, crowding, parent/child replacement, best-candidate reporting, and
analysis use those directions. There is no active AOS implementation in the
repository.
