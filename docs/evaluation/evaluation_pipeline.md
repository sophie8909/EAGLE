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
| Match execution | integrated class set | 180 valid fixed-roster results in generation 0; 198 including `eagle_previous_best` in later generations | completed evidence and runtime failure |
| Objective aggregation | all required evidence | `game_performance`, `code_quality` | failure values for the terminal stage |

No stage may erase artifacts from an earlier stage.

## Integration contract

Integration is a distinct pre-match stage. It loads `ai.generated.CandidateAgent`, verifies the MicroRTS `AI`/`AbstractionLayerAI` type contract, invokes both required constructors, calls `reset()`, validates the non-null `AI` returned by `clone()`, calls `getAction()` with a minimal valid `GameState`, and validates the non-null `PlayerAction` result.

Persist all seven ordered check results. A failed prerequisite marks downstream checks `blocked`; `integration_pass_ratio` is `passed_check_count / 7`. Integration starts no evaluation match. Only a candidate passing all seven checks proceeds to the expected 180/198-match batch.

## MicroRTS protocol

- Candidate: generated Java, always evaluated as the configured candidate player.
- Opponents: weighted `passive`, `random`, `randombias`, `lightrush`, `heavyrush`,
  `workerrush`, `allibot`, `mayari`, `coac`, and `tma` (fixed weight sum 12.5).
  `workerrush` is provided by a run-local `ai.abstraction.WorkerRush` adapter
  because the vendored runtime has no class with that name.
  From generation 1 onward, append one frozen previous-generation champion under
  `eagle_previous_best` with the configured quadratic weight schedule.
- Match count: exactly 180 in generation 0 and 198 thereafter; each opponent has three maps × three rounds × both candidate sides.
- Compilation count: once per generated source.
- Java generation count during evaluation: zero.
- Source/class set: identical across the candidate's fixed matches; the optional
  dynamic opponent uses one separately compiled, persisted alias class set shared
  by every candidate in that generation.
- Seeds: distinct where MicroRTS supports them and persisted in resolved configuration and match metadata.
- Each match has a separate artifact directory.

Any candidate with fewer than the expected 180 or 198 valid completed matches has failed evaluation. Preserve completed match evidence and assign failure objectives through the canonical failure contract.

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

- Aggregate each opponent's 18 results first, then apply its weight; aggregate only after all expected 180 or 198 matches are valid.
- A draw, loss, or tick-limit result that satisfies the match result contract is not automatically a runtime failure.
- Invalid/missing/unparseable results, process failures, exceptions, deadlocks, or partial batches are runtime failures.
- Run valid simplicity scoring only after complete 180/198-match execution. Function Capability and Strategy Alignment still persist as diagnostics, but neither contributes to valid `code_quality`.
- Keep `strategy_alignment` out of the optimizer; NSGA-II receives only maximized `game_performance` and `code_quality`.

## Module responsibility target

- `eagle/evaluation.py`: stage orchestration and terminal routing only.
- `generation/`: generation and source validation.
- `evaluation/compiler.py`: compilation and diagnostic capture.
- `evaluation/microrts_runner.py`: integration and per-match process execution.
- `evaluation/game_performance.py`: canonical gameplay formula.
- `evaluation/code_quality.py` and `evaluation/canonical_code_quality.py`: deterministic simplicity metrics and score assembly.
- `evaluation/nsga2_objectives.py`: two-objective assembly and failure constants.
- `eagle/artifacts.py`: serialization only.

The active implementation follows these stage boundaries; older gap notes in `architecture_gaps.md` describe superseded protocols and are not runtime authority.

## Tests

- Verify the stage order and that downstream stages do not run after terminal failure.
- Verify exactly one compile and 180/198 match calls per successful candidate depending on generation.
- Verify the same source hash and class directory are used for all matches.
- Verify the ten-opponent roster and distinct match directories/seeds.
- Verify a nine-match partial batch fails while retaining all nine results.
- Verify each pipeline stage maps to the correct failure classification.
