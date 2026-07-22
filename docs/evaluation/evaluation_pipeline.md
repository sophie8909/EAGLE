# Evaluation pipeline

## Normative source

See specification sections 13, 19, and 26. Objective formulas are owned by [`game_performance.md`](game_performance.md), [`code_quality.md`](code_quality.md), and [`failure_classification.md`](failure_classification.md).

## Stage contract

| Stage | Input | Success output | Terminal evidence on failure |
| --- | --- | --- | --- |
| Java generation | complete child genotype | raw, extracted, and normalized full Java | backend/extraction failure |
| Source validation | normalized source | validated runtime contract | validation result and reason |
| Compilation | validated source | one isolated class set | command and diagnostics |
| Integration | compiled classes | loadable/constructible/callable MicroRTS AI | failed checks and ratio |
| Match execution | integrated class set | 10 valid match results | completed evidence and runtime failure |
| Objective aggregation | all required evidence | `game_performance`, `code_quality` | failure values for the terminal stage |

No stage may erase artifacts from an earlier stage.

## Integration contract

Integration is a distinct pre-match stage. It loads `ai.generated.CandidateAgent`, verifies the MicroRTS `AI`/`AbstractionLayerAI` type contract, invokes both required constructors, calls `reset()`, validates the non-null `AI` returned by `clone()`, calls `getAction()` with a minimal valid `GameState`, and validates the non-null `PlayerAction` result.

Persist all seven ordered check results. A failed prerequisite marks downstream checks `blocked`; `integration_pass_ratio` is `passed_check_count / 7`. Integration starts no evaluation match. Only a candidate passing all seven checks proceeds to the 10-match batch.

## MicroRTS protocol

- Candidate: generated Java, always evaluated as the configured candidate player.
- Opponent: `ai.abstraction.LightRush`.
- Match count: exactly 10.
- Compilation count: once per generated source.
- Java generation count during evaluation: zero.
- Source/class set: identical across all 10 matches.
- Seeds: distinct where MicroRTS supports them and persisted in resolved configuration and match metadata.
- Each match has a separate artifact directory.

Any candidate with fewer than 10 valid completed matches has failed evaluation. Preserve completed match evidence and assign failure objectives through the canonical failure contract.

## Match result requirements

Each match must make the following available for aggregation and mutation feedback:

- result and winner;
- candidate/opponent identity and player side;
- map, seed, `max_cycles`, and final tick;
- final player/enemy resources;
- per-tick material traces and configured unit values;
- survival evidence;
- replay, round state, stdout, stderr, return code, duration, status, and failure reason.

## Aggregation invariants

- Aggregate only after all 10 matches are valid.
- A draw, loss, or tick-limit result that satisfies the match result contract is not automatically a runtime failure.
- Invalid/missing/unparseable results, process failures, exceptions, deadlocks, or partial batches are runtime failures.
- Run successful `code_quality` evaluation only after complete 10-match execution because strategy alignment may consume behavior evidence.
- Keep `strategy_alignment_score` inside `code_quality`; NSGA-II receives two values only.

## Module responsibility target

- `eagle/evaluation.py`: stage orchestration and terminal routing only.
- `generation/`: generation and source validation.
- `evaluation/compiler.py`: compilation and diagnostic capture.
- `evaluation/microrts_runner.py`: integration and per-match process execution.
- `evaluation/game_performance.py`: canonical gameplay formula.
- `evaluation/code_quality.py`: successful code-quality components.
- `evaluation/nsga2_objectives.py`: two-objective assembly and failure constants.
- `eagle/artifacts.py`: serialization only.

Current code does not yet respect these boundaries fully. See gaps `G-05` through `G-11` in [`../implementation/architecture_gaps.md`](../implementation/architecture_gaps.md).

## Tests

- Verify the stage order and that downstream stages do not run after terminal failure.
- Verify exactly one compile and 10 match calls per successful candidate.
- Verify the same source hash and class directory are used for all matches.
- Verify LightRush and distinct match directories/seeds.
- Verify a nine-match partial batch fails while retaining all nine results.
- Verify each pipeline stage maps to the correct failure classification.

