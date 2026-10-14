# Failure classification and objective sentinels

The evaluation pipeline records the first terminal stage and retains all earlier evidence. A candidate that fails materialization, validation, compilation, integration, runtime execution, timeout handling, or the expected complete batch receives the same objective sentinel:

| Objective | Failure value | Direction |
| --- | ---: | --- |
| `game_performance` | `-1000` | maximize |
| `code_quality` | `-1000` | maximize |

`eagle/evaluation/code_quality.py::failure_code_quality` deliberately
returns `-1000` for every supported failure stage. It no longer ranks failures
by progress. `failure_stage`, `failure_category`, `failure_reason`, compiler
diagnostics, validation diagnostics, integration results, retained matches,
and any diagnostic complexity metrics remain available in artifacts and
reflection context.

LLM-mode bounded Java decoding retains each attempt's request, source, structured failure evidence, and repair-chain reference. A complete validation or javac failure may guide the next decoder attempt; extraction failure repeats the base request. The first successful validation and compilation proceeds to Integration. If the attempt budget is exhausted, the final attempt determines the terminal failure. Deterministic DSL materialization has no Java generation or compile-repair LLM: a compiler, validation, or javac failure is terminal and retains stage evidence.
The Integration boundary is not a decoder-repair input. It runs a real
populated 8×8 two-side probe with independent agent instances/states and checks
`PlayerAction` integrity, safe issuance, and one cycle; an exception or invalid
action there is an Integration failure with retained probe evidence, not a
validation/compilation retry.

Valid losses and draws are not failures when the complete expected match batch
is present. A partial, missing, invalid, unparseable, timed-out, or runtime-
failed batch is incomplete and receives both sentinels.

The pinned AllInBot upstream policy has a narrow fault-containment boundary.
Its reflection adapter catches only delegate `Exception` failures (never
`Throwable`/serious JVM errors), null actions, and integrity-invalid actions.
When it recovers a completed match, artifacts carry
`fault_scope="opponent"`, `opponent_fault_contained=true`,
`opponent_fault_recovered=true`, the one-time marker/reason, and
`scoring_neutralized=true`. The runner preserves the observed raw result but
uses a neutral zero-score draw for all candidate metrics and final-test W/L/D
reporting. Therefore this is neither a candidate runtime failure nor evidence
of a candidate win; an actual incomplete/failed process still follows the
normal failure sentinel path.
