# EAGLE evolutionary flow

This document describes the active implementation. The ten opponent cases are
the evolutionary fitness dimensions; the weighted aggregate is reporting-only.

## Population lifecycle

1. In default `generated_phenotype` mode, create one candidate per configured
   seed policy and load the callable no-op Java phenotype without an LLM call.
   In inherited `configured_seeds` mode, require one seed policy, copy it to
   `population_size`, and give every copy the same inherited Java input. In
   inherited `llm_generated_policies` mode, keep the configured policy in slot
   one and fill every other slot through one policy-only LLM call. Each such
   call receives the immutable closed-world MicroRTS gameplay contract.
2. In inherited `configured_seeds` mode, call the Generator independently for
   every generation-zero candidate. In `llm_generated_policies` mode, directly
   validate, compile, integrate, and evaluate the same fixed Java seed for all
   generation-zero candidates. Later children in both modes independently
   inherit policy, generation prompt, and Java provenance before the same final
   Generator boundary.
3. Store one score for each fixed opponent case: `passive`, `random`,
   `randombias`, `lightrush`, `heavyrush`, `workerrush`, `allinbot`, `mayari`,
   `coac`, and `tma`.
4. Select parents with seeded lexicase selection. A random case order is drawn
   from the EA `random.Random` instance, and candidates are filtered to the
   best score for each case until one remains.
5. Apply crossover/copy to every active genotype component and let the
   configured reflection-operator controller choose Strategy Reflection,
   Generate-Code Reflection, or Prompt Compliance Reflection. Strategy and Code
   mutate one owned prompt; Prompt Compliance audits the active prompt pair and
   rewrites only issue-bearing genes, committing atomically when both need
   repair. It receives no W/D/L, match, Java, compiler, or fitness evidence.
   None directly edits inherited Java.
6. Decode each child with its configured compile-guided attempt bound, using
   structured validation/javac evidence only after a complete source fails;
   promote the first validation+compilation success, then evaluate that single
   promoted phenotype through the complete pipeline. Integration/runtime
   failure never re-enters the decoder. `static` performs no credit update;
   `aos_opponent` reuses the ten normal opponent summaries;
   `aos_head2head` runs the configured direct matrix against the recorded
   mutation-evidence parent. Both adaptive modes feed one shared
   generation-level EMA updater.
7. From generation 1 onward, combine evaluated parents and offspring and fill
   the fixed population with seeded lexicase selection without replacement.
   This is the `(mu + lambda)` environmental-selection model; when both sets
   have size `n`, it is the requested `(n + n)` form.
8. Persist the surviving population and generation metrics.

The implementation is in `eagle/search.py`, `eagle/selection.py`, and
`eagle/evaluation.py`.

## Objective contract

`Candidate.objective_vector()` in `eagle/candidate.py` contains exactly the ten
opponent cases. All are maximized. Missing or failed cases use `-1000.0` from
`eagle/opponent_cases.py`.

`code_quality` is retained in `Candidate.code_quality_result` as a diagnostic
and failure/implementation signal. It is not an evolutionary objective and is
not consulted by lexicase, survivor selection, or the opponent archive.

The weighted Game Performance aggregate is calculated with the fixed weights
in `eagle/opponent_cases.py` (weight sum `12.5`). It is used for reporting and
the convenient final representative only; it does not replace the ten cases.

## Evaluation matrix

Each candidate runs all ten opponents over three maps, three rounds, and both
player positions: `10 × 3 × 3 × 2 = 180` matches. There is no previous-generation
EAGLE opponent or dynamic opponent weight.

The generation-level `expected_match_count` and `completed_match_count` are sums
over every candidate in that generation, including zero completed matches for a
candidate blocked before runtime.

Only `aos_head2head` runs the separate `3 × 3 × 2 = 18` parent-vs-offspring
matrix for each runnable mutated child. It reuses the configured maps, round
indices, sides, and compiled classes. These matches never enter fitness, the
opponent archive, lexicase, weighted Game Performance, or final testing.
`aos_opponent` instead compares the existing ten normal opponent records;
`static` performs neither form of credit assignment.

Both adaptive modes use the mutation context's evidence parent as the
comparison parent. Strategy uses `strategy_parent_id`; default-mode Code and
Prompt Compliance use `generation_prompt_parent_id`; inherited-mode Code and
Prompt Compliance use
`java_parent_id`. Therefore component-wise crossover may select either direct
parent without silently assigning AOS credit to the other one.

## Archive and analysis

`runs/<run>/archives/opponents.json` keeps one best valid representative per
opponent case. Each generation JSON stores objective statistics for all
ten cases and `opponent_scores.by_opponent` stores reporting summaries. The
offline analysis writes `opponent_game_performance.csv` and one
`game_performance_by_generation_<opponent>.png` per opponent. It also writes
per-agent, per-opponent win-rate rows/plots and `match_game_performance.csv` for the
small, semi-transparent single-match violin distributions on aggregate
Game Performance plots. It also writes `aos_operator_statistics.csv` and an
AOS probability plot.

See [`../opponent-wise-lexicase.md`](../opponent-wise-lexicase.md) for
the complete data and artifact contract.
