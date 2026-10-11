# EAGLE evolutionary flow

This document describes the active implementation. Fixed-roster evaluation
uses ten opponent cases. Self-play uses scalar Game Performance plus exact
behavior signatures only when scalar fitness is tied.

## Population lifecycle

1. In default `generated_phenotype` mode, create one candidate per configured
   seed policy and load the callable no-op Java phenotype without an LLM call.
   In inherited `configured_seeds` mode, require one seed policy, copy it to
   `population_size`, and give every copy the same inherited Java input. In
   inherited `llm_generated_policies` mode, keep the configured policy in slot
   one and fill every other slot through one policy-only LLM call. Each such
   call receives the immutable closed-world MicroRTS gameplay contract and a
   stable slot-specific strategy identity from `initial_policy_variants.txt`.
   This keeps deterministic runs reproducible while preventing every slot from
   receiving the same effective generation request.
2. In inherited `configured_seeds` and `llm_generated_policies` modes, call the
   Generator independently for every generation-zero candidate. In the latter,
   WorkerRush Java is inherited prompt context rather than the phenotype. Later
   children in both modes independently
   inherit policy, generation prompt, and Java provenance before the same final
   Generator boundary.
3. In default `fixed_roster` evaluation, store one score for each opponent case: `passive`, `random`,
   `randombias`, `lightrush`, `heavyrush`, `workerrush`, `allinbot`, `mayari`,
   `coac`, and `tma`.
4. Select reproduction sources and independently gate each against its own DSL
   policy and exact Java before actual crossover/mutation. Every contributing
   source must pass. A defect creates a one-parent corrective child with unchanged
   genes; diagnosis failure creates no healthy source and cannot enter variation.
   Healthy-check LLM time is retained under `pre_crossover_code_checks_llm` with
   check IDs and full diagnosis timing; a defective child retains its own
   diagnosis/revision timing separately. Generation aggregates include all three
   streams without double-counting.
5. For healthy sources, assign normal component crossover/copy and Strategy,
   Prompt, or no mutation. Strategy changes only canonical DSL policy; Prompt
   changes only reusable generation rules. Corrective children skip both.
6. After all diagnosis/reflection/rewrite work, switch to the optional
   `generation_model` boundary and materialize ordinary children or corrective
   Java children. Corrective Java bypasses ordinary Generator overwrite; all
   candidates enter validation, compilation, integration, and evaluation.
   Compile repair remains bounded and diagnostic-only. AOS credit covers normal
   Strategy/Prompt mutation only; the independent gate earns no reward.

7. From generation 1 onward, combine parents and offspring and fill the fixed
   population with mode-specific selection without replacement. Failed
   offspring remain in the joint input for diagnostics, but are excluded from
   survivor choice when completed parents/offspring can fill the population;
   therefore an all-failed offspring batch leaves valid parents in place.
   Selection fails explicitly if fewer than the configured population size
   completed candidates remain.
   This is the `(mu + lambda)` environmental-selection model; when both sets
   have size `n`, it is the requested `(n + n)` form. The canonical default
   `parent_evaluation_mode: reuse_cached` uses the existing evaluated parents.
   The explicitly non-canonical diagnostic treatment
   `regenerate_same_genotype` is restricted to `inherited_genotype` plus
   `reflection_operator_mode: static`: it evaluates one new-ID parent replica
   per old parent, with the same complete genotype and component provenance,
   then selects from replicas plus offspring only. It never overwrites or
   reuses the old parent as a survivor candidate.
8. In `self_play` evaluation, maintain a persisted opponent library and one
   immutable ten-slot active context. Seed and update the library only at each
   configured refresh generation (five generations in the minimal protocol),
   merge newly runnable candidates, collapse exact semantic probe/action-vector
   duplicates, and deterministically select the next active context from the
   library. Between refreshes, keep the context unchanged. At
   refresh, phenotype-preserving fresh-ID parent replicas are re-evaluated
   before reflection; the same migration is also performed if generation-zero
   semantic deduplication changes the context before the first offspring
   generation. Only those replicas and offspring evaluated against that same
   context enter selection. Persist the library, active context, refresh
   audit sidecar, surviving population, and metrics. The sole objective is
   aggregate `game_performance`. Scores whose difference from the current tier
   maximum is at most `1.0` are tied; tiers are never formed by chained
   pairwise comparisons. Parent B and a cut survivor tier prefer the greatest
   compatible Hamming distance across the nine action hashes.

The shared generation implementation is in `eagle/evolution/generation.py` and `eagle/evolution/offspring.py`; selection is in `eagle/operators/selection.py`, with evaluation in
`eagle/evaluation/pipeline.py`.

## Objective contract

In fixed-roster mode, `Candidate.objective_vector()` contains exactly the ten
static-opponent fitness cases and selection is seeded lexicase. In self-play,
`Candidate.fitness_objectives` contains only `game_performance`; the ten
`self_play_*` slot scores remain diagnostics in `game_eval_result`. Failed
candidates use `-1000.0`.

`code_quality` is retained in `Candidate.code_quality_result` as a diagnostic
and failure/implementation signal. It is not an evolutionary objective and is
not consulted by lexicase, survivor selection, or the opponent archive.

Fixed-roster weighted Game Performance is calculated with the fixed weights
in `eagle/opponent_cases.py` (weight sum `12.5`). It is used for reporting and
the convenient final representative only; it does not replace the ten cases.
Self-play uses its unweighted aggregate as the single objective.

## Evaluation matrix

Each candidate runs all ten active cases over three maps, three rounds, and both
player positions: `10 × 3 × 3 × 2 = 180` matches. Fixed-roster mode resolves the
ten bundled opponents. Self-play mode cycles the selected runnable entries from
the immutable opponent-library context into ten equally weighted slots; five
selected candidates therefore appear twice.

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
comparison parent. Strategy uses `strategy_parent_id`; default-mode Prompt uses `generation_prompt_parent_id`; inherited-mode Prompt uses
`java_parent_id`. Therefore component-wise crossover may select either direct
parent without silently assigning AOS credit to the other one.

## Archive and analysis

For `regenerate_same_genotype`,
`generations/generation_<nnnn>_parent_rematerialization.json` is the compact
source-parent-to-replica audit sidecar. It records component genotype hashes,
old and newly generated Java hashes, the replica fitness/status, and whether
the replica survived. Generation archives, error memory, timing aggregation,
and retired-trace cleanup use the actual replica-plus-offspring selection pool.

New search runs do not write `runs/<run>/archives/opponents.json`. The explicit `eagle analyze` command derives `analysis/opponent_representatives.json` from all evaluated candidates, including nonsurvivors. Each generation JSON stores objective statistics for all
ten cases and `opponent_scores.by_opponent` stores reporting summaries. Representatives use fixed-roster case IDs; self-play slot identities
are snapshot-scoped.
`python -m eagle analyze --semantics --run-dir <run>` reads existing wrapper and
cache artifacts without executing agents, and writes candidate/probe tables,
global/map/phase uniqueness statistics, and exact equivalence classes.
offline analysis writes `opponent_game_performance.csv` and one
`game_performance_by_generation_<opponent>.png` per opponent. It also writes
per-agent, per-opponent win-rate rows/plots and `match_game_performance.csv` for the
small, semi-transparent single-match violin distributions on aggregate
Game Performance plots. It also writes `aos_operator_statistics.csv` and an
AOS probability plot.

See [`../opponent-wise-lexicase.md`](../opponent-wise-lexicase.md) for
the complete data and artifact contract.
