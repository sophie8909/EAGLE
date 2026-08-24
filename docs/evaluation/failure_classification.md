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

Bounded Java decoding retains every attempt's request, source, structured
failure evidence, and repair-chain reference. A complete validation or javac
failure may guide the next decoder attempt; an extraction failure has no source
to repair and repeats the base request. The first validation+compilation success
ends decoding and proceeds to Integration. If the configured attempt budget is
exhausted, the final attempt determines the candidate's terminal generation,
validation, or compilation failure. Earlier failures remain diagnostic and do
not create extra fitness cases, and an exhausted source is not a canonical
phenotype.

Valid losses and draws are not failures when the complete expected match batch
is present. A partial, missing, invalid, unparseable, timed-out, or runtime-
failed batch is incomplete and receives both sentinels.
