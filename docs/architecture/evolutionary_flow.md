# EAGLE evolutionary flow

This document describes the active implementation. Fixed-roster evaluation
uses ten opponent cases. Self-play uses scalar Game Performance plus exact
behavior signatures only when scalar fitness is tied.

Unless a step is marked otherwise, the population lifecycle below describes
`java_materialization_mode: llm`; deterministic DSL and framework-slot behavior
are specified in their own sections.

## Population lifecycle

1. In default `generated_phenotype` mode, create one candidate per configured
   seed policy and load the callable no-op Java phenotype without an LLM call.
   In inherited `configured_seeds` mode, require one seed policy, copy it to
   `population_size`, and give every copy the same inherited Java input. In
   inherited `llm_generated_policies` mode, keep the configured policy in slot
   one and fill every other slot through bounded policy-only LLM calls. These
   calls receive the immutable closed-world MicroRTS gameplay contract and a
   stable slot-specific strategy identity from `initial_policy_variants.txt`.
   First-wave policy requests use the same configured-seed snapshot and distinct
   task seeds. This keeps candidate requests distinct in deterministic runs. Policy
   transport is stateless; Java-generation request context is
   thread-local.
   Results are collected in candidate order; duplicates are resolved and retried
   in that order against already accepted policies. Every attempt retains its
   bounded artifacts and timing. For a valid duplicate, the attempt remains
   successful and unselected; its `result.json` may record `population_decision`
   as `{status: rejected_duplicate, reason, duplicate_of_candidate_id}`. Its
   timing and request event remain successful. Retries continue within
   `initial_policy_max_attempts`; exhausting the bound can fail initialization
   even when the duplicate responses themselves were valid.
2. In inherited `configured_seeds` and `llm_generated_policies` modes, call the
   Generator independently for every generation-zero candidate. These independent
   candidate calls use the bounded LLM pool and results return in candidate order.
   In the latter, WorkerRush Java is inherited prompt context rather than the
   phenotype. Later children in both modes independently inherit policy,
   generation prompt, and Java provenance before the same final Generator
   boundary.
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
   have size
`, it is the requested `(n + n)` form. The canonical default
   `parent_evaluation_mode: reuse_cached` uses the existing evaluated parents.
   The explicitly non-canonical diagnostic treatment
   `regenerate_same_genotype` is restricted to `inherited_genotype` plus
   `reflection_operator_mode: static`: it evaluates one new-ID parent replica
   per old parent, with the same complete genotype and component provenance,
   then selects from replicas plus offspring only. It never overwrites or
   reuses the old parent as a survivor candidate.
8. In `self_play`, the maintained pool is updated after generation zero and
    every completed offspring evaluation. New eligible entries join while
    capacity remains; once full, each entrant challenges one seeded sampled
    nonprotected incumbent in an 18-match duel and replaces it only with
    strictly more wins than losses. The four protected top-tier baselines never
    enter these tournaments. Generation zero evaluates all ten built-in
    sources in fixed slots: the protected four use their actual case IDs and
    the other six use `self_play_000`…`self_play_005`. Generation one and each
    configured refresh boundary keep the protected case IDs and sample six
    nonprotected members into those diagnostic slots. Context rows identify
    built-ins with `source_opponent_id` and null candidate/generation fields.
    Context changes trigger
    phenotype-preserving parent refresh before selection. Pool state is
    checkpointed and restored before resume replay. See the
    [canonical self-play contract](../eagle_architecture_spec.md#9-evolution-evaluation)
    for capacity, artifact, compatibility, and failure details.

The shared generation implementation is in `eagle/evolution/generation.py` and `eagle/evolution/offspring.py`; selection is in `eagle/operators/selection.py`, with evaluation in
`eagle/evaluation/pipeline.py`.

## Bounded execution

`eagle/execution.py` fixes GPU layers to `999`, model threads to `8`, LLM
workers to `2`, and match workers to `10`; the managed local llama-server uses
two slots. Each phase uses its local primary plus zero or one ordered
`additional_endpoints` entry. `parallel_map` binds canonical input index to the
corresponding endpoint slot modulo the endpoint count, allowing the two workers
to issue local and remote requests concurrently without making routing depend
on completion order. Results are still consumed in candidate/assignment order.
Dependent calls and retries for one task stay on their assigned endpoint, and
transport failure does not trigger cross-endpoint failover.

Independent candidate work runs in the LLM pool within its phase: source Code
gates, reflection/rewrite, corrective Code revision, and Java generation,
decoding, and compilation. Each candidate's dependent calls retain their
required order. Every configured endpoint must pass a chat-completion preflight
before phase work starts. On failure or interruption, queued tasks are cancelled
and active requests finish before the phase returns; results are consumed in
candidate/assignment order. The reflection/rewrite phase completes before
switching to `generation_model`. Only the managed local primary participates in
that process switch; additional endpoints remain unmanaged.
AOS selection and reward calculation/application remain serial and keep their
existing formulas. Match dispatch uses the fixed ten-worker pool. Match traces
remain available through dependent candidate construction and are retired at
their existing cleanup boundary.

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


## Deterministic Java materialization

When `java_materialization_mode` is `deterministic_dsl`, only `strategy_prompt`
is active genotype. Whole-policy copy/crossover and Strategy mutation remain
available; rule-level crossover, Prompt Reflection, Code Reflection/source
repair, Java generation, and compile-repair LLM requests are disabled. Compiler
output follows the existing validation, javac, Integration, semantic-probe, and
evaluation path. A deterministic compiler or javac failure does not fall back to
LLM. Resolved protocol/compiler versions are `eagle-dsl-compiler-v1` and
`eagle-dsl-java-v1`.

## Framework-slot evolution

On fresh startup, EAGLE validates an explicit external bundle or bootstraps one
from `framework.design_brief` into the run-owned `framework/` directory. It
freezes the bundle before search. Resume uses only the frozen bundle and never
runs bootstrap again. See the [framework-slot contract](framework_slots.md).
Generation zero samples one complete valid `control_genome` per population slot
with independent derived RNG streams.
From generation one, ordinary selection remains unchanged. Reproduction uses
local uniform crossover independently for every framework slot, records the
selected source candidate in `slot_parent_ids`, and may mutate at most one slot
to a different member of its finite domain. Integer and number controls stay on
their declared lattices. Formula controls select a declared `choice_id`; their
Java expressions are immutable bundle data. No policy, prompt, Java body, or
free-form formula is generated during evolution.

Each child is rendered locally from the run-frozen template and complete
control genome, then enters the existing validation, one `javac`, Integration,
semantic probe, and 180-match fixed-roster evaluation (or the configured
unchanged self-play path). In `local`, genome selection and variation use seeded
EA operators and no LLM. In `llm_coach`, the experiment model selects each
initial complete genome and Strategy mutation uses the existing one-worst-match
Commentator→Coach evidence path to return a complete genome. Both modes preserve
parent-plus-offspring survivor selection and objective formulas. Prompt and Code
Reflection, source gating, Java Generation, and compile repair remain disabled;
render/validation/compiler failure has no LLM fallback.
