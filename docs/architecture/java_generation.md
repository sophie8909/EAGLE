# Java generation, validation, and compilation

## Normative source

See specification sections 11 through 13 and 23. Failure scoring is owned by [`../evaluation/failure_classification.md`](../evaluation/failure_classification.md).

## Generation input and output

Input is exactly the complete child genotype:

- `strategy_prompt`;
- `previous_code` (latest selected evaluated Java);
- `generation_prompt`.

Output is one complete `CandidateAgent.java` source file. Accept no patch, diff, JSON object, isolated method body, partial function set, or prose outside the source. Persist the raw response before extraction or normalization.

## Processing sequence

1. Persist the final generation request.
2. Call the Java Generation LLM with retry logging.
3. Persist every raw response before parsing.
4. Extract a single complete Java source.
5. Persist extracted and normalized forms separately.
6. Validate source structure, runtime compatibility, and prohibited capabilities.
7. Compile once with `javac` and explicit warning diagnostics.
8. Persist command, stdout, stderr, return code, errors, warnings, and compiled output location.
9. Perform a distinct MicroRTS load/initialization/invocation integration check.
10. Reuse that compiled result for all 10 matches.

## Runtime contract

Validation must enforce this external identity:

| Element | Required value |
| --- | --- |
| Package | `ai.generated` |
| Public class | `CandidateAgent` |
| Superclass | `AbstractionLayerAI` |
| Constructor 1 | `CandidateAgent(UnitTypeTable utt)` |
| Constructor 2 | `CandidateAgent(UnitTypeTable utt, AStarPathFinding pathFinding)` |
| Callable method | `PlayerAction getAction(int player, GameState gs)` |
| Callable method | `void reset()` |
| Callable method | `AI clone()` |

The specification does not require fixed helper names, a six-function design, a fixed strategy region, fixed internal classes, or a fixed code layout. Do not turn the repository template into an internal architecture mandate.

Validation also rejects network access, external process creation, unauthorized file I/O, runtime modification, and unavailable dependencies.

## Integration contract

After compilation, execute and persist these checks in order:

1. load `ai.generated.CandidateAgent` from the candidate classpath;
2. verify it is a valid MicroRTS `AI` extending `AbstractionLayerAI`;
3. instantiate it successfully through both required constructors;
4. call `reset()`;
5. call `clone()` and validate the non-null returned `AI` instance;
6. call `getAction()` with a minimal valid `GameState`;
7. validate the non-null returned `PlayerAction`.

Record `passed`, `failed`, or `blocked` plus a reason for every check. The integration stage starts no evaluation match. All seven checks must pass before the 10-match batch begins.

## Compilation contract

- Compile only after source validation succeeds.
- Use an isolated output directory per candidate.
- Include the MicroRTS classes and required libraries on the classpath.
- Enable explicit warnings such as `-Xlint`.
- Count structured compiler diagnostics, deduplicate repeats, and persist each warning/error.
- Never regenerate Java to repair a candidate inside the 10-match batch.

## Failure boundaries

Classify failures at the stage where progress stops: generation/backend, source validation, compilation, MicroRTS integration, or runtime. Do not collapse a load/constructor/signature failure into compilation or runtime. Retain partial artifacts at every boundary.

## Required tests

- Raw response is durable before extraction and remains available on every failure path.
- Complete source succeeds without relying on fixed internal helper names.
- Each prohibited capability is rejected.
- Package/class/superclass/constructor/method/load failures reach the correct stage.
- `javac` warnings are structured, deduplicated, counted, and capped by scoring policy.
- Compilation occurs once and the same class directory is passed to all 10 matches.
- No generation backend call occurs between match 0 and match 9.

