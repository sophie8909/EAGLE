# Failure classification and objective sentinels

The evaluation pipeline records the first terminal stage and retains all
earlier evidence. Any candidate that fails generation, extraction,
validation, compilation, integration, runtime execution, timeout handling, or
the expected complete batch receives the same objective sentinel:

| Objective | Failure value | Direction |
| --- | ---: | --- |
| `game_performance` | `-1000` | maximize |
| `code_quality` | `-1000` | maximize |

`evaluation/code_quality.py::failure_code_quality` deliberately
returns `-1000` for every supported failure stage. It no longer ranks failures
by progress. `failure_stage`, `failure_category`, `failure_reason`, compiler
diagnostics, validation diagnostics, integration results, retained matches,
and any diagnostic complexity metrics remain available in artifacts and
reflection context.

Valid losses and draws are not failures when the complete expected match batch
is present. A partial, missing, invalid, unparseable, timed-out, or runtime-
failed batch is incomplete and receives both sentinels.
