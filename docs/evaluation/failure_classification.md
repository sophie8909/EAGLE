# Failure classification and failure-stage fitness

This is the canonical owner of terminal pipeline stages and their failure `code_quality` values. Normative source: specification sections 14.1 and 16.

## Global failure objective

Every candidate that does not complete a valid 10-match evaluation receives:

```text
game_performance = -1000
```

Retain all partial evidence. `code_quality` distinguishes how far the candidate progressed.

## Stage order and scores

| `failure_stage` | Typical conditions | `code_quality` |
| --- | --- | --- |
| `generation` | backend unavailable, HTTP failure, empty/invalid response, no extractable Java | `-1000` |
| `validation` | wrong package/class/superclass, missing runtime contract, forbidden API, invalid source contract | `-950` |
| `compilation` | `javac` failure | `-800 - min(error_count * 5, 100)`; range `[-900, -800]` |
| `integration` | compiled but class cannot load/construct/initialize/invoke required method | `-600 + round(integration_pass_ratio * 100)`; range `[-600, -500]` |
| `runtime` | exception, illegal action, deadlock/timeout, crash, invalid/missing result, partial matches | `-400 + round((completed_matches / 10) * 199)`; range `[-400, -201]` |
| none | complete 10-match execution | successful formula in [`code_quality.md`](code_quality.md) |

Required ordering:

```text
generation/validation < compilation < integration < runtime < success
```

Validation and generation are distinct even though both precede compilation.

## Classification rules

- Use the first terminal stage whose required success output is absent.
- Backend transport and extraction failures are `generation`; structurally extracted but invalid source is `validation`.
- Compilation success followed by class loading, constructor, superclass, signature, initialization, or initial `getAction` failure is `integration`.
- A class that integrated and started matches but fails before 10 valid results is `runtime`.
- A valid loss/draw is not a failure.
- Artifact persistence failure must be reported separately; it must not be mislabeled as a gameplay loss. Whether persistence failure terminates evaluation is unresolved unless the specification states it.

## Required fields

Persist at least:

- `status`, `failure_stage`, `failure_category`, `failure_reason`;
- last successful stage;
- stage-specific counts (`error_count`, integration checks, `completed_matches`);
- both objective values;
- every retained request, response, source, diagnostic, match, and timing record.

## Integration checks

Persist these seven ordered results:

1. candidate class loads from the candidate classpath;
2. class is a valid MicroRTS `AI` extending `AbstractionLayerAI`;
3. both required constructors instantiate successfully;
4. `reset()` succeeds;
5. `clone()` returns a non-null valid `AI`;
6. `getAction()` is callable with a minimal valid `GameState`;
7. `getAction()` returns a non-null valid `PlayerAction`.

Each result is `passed`, `failed`, or `blocked`. A blocked check is not passed. Compute:

```text
integration_pass_ratio = passed_check_count / 7
```

Integration starts no evaluation match. All seven checks must pass before match execution.

## Tests

- One fixture for every listed failure condition and boundary score.
- Error-count cap and integration-ratio endpoints.
- Runtime progress at 0, 5, and 9 completed matches.
- Later stages always outrank earlier stages.
- Completed loss/draw remains a successful execution.
- Partial matches retain artifacts but return failure objectives.
- Classification stays stable across artifact serialization/deserialization.

