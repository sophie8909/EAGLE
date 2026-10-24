# EAGLE evolutionary flow

In framework `reflection` self-play, completed interval boundaries trigger whole
framework reflection alongside opponent refresh (interval 5: G6 uses G5, then
G11 uses G10). G1 only initializes the opponent snapshot. Every preceding
survivor contributes its description, complete genome, and fitness. A separate
strategy-reflection stage revises descriptions before a following batch Coach
fills complete genomes from them under the new framework. Generation zero uses
ten distinct authored descriptions, including WorkerRush, and Coach fills its
initial genomes. Local offspring inherit parent A's description.
Accepted versions create fresh parent replicas and reevaluate them under the new opponent context before
ordinary local mating/mutation. Failed reflection keeps the old framework.
The [framework contract](framework_slots.md) owns the precise activation rules.

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
6. Each child immediately materializes after its own diagnosis/reflection/rewrite
   through the permanently bound generation client. Corrective Java bypasses
   Generator overwrite. Validation/compilation and matches overlap later source
   gates, crossover and mutation. Compile repair remains bounded and diagnostic;
   source gates receive no AOS credit.

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

Self-play mating chooses parent B with minimum compatible behavioral distance
to parent A within the highest fitness tier. It excludes parent A when another
tier member exists; a singleton tier reuses its member. Missing/incompatible
signatures use seeded fallback. Survivor boundary selection retains max-min
semantic diversity. Fixed-roster lexicase selection is unchanged.

## Bounded execution

Independent source gates run in two bounded workers and release plans in canonical
input order. Crossover and AOS assignment remain serial and seeded. Two preparation
workers execute each child's mutation, corrective revision or generation, validation
and compilation. One evaluation consumer starts any ready child's Integration,
semantic probes and matches while later children continue source gating, crossover
or preparation. Results retain canonical candidate order and original ordinals/seeds;
bounded completed-work buffering applies backpressure.

Role clients permanently bind initialization/reflection/rewrite to `model` and
Java generation/corrective revision/compile repair to optional `generation_model`.
Different models use separately running server hosts/ports; EAGLE never switches
models between phases. Omit `generation_model` to share the model concurrently.
Each profile retains zero or one ordered unmanaged `additional_endpoints`.
Canonical task index selects the route; retries stay sticky with no failover.
All roles share two active requests per normalized server origin; different
origins can proceed independently.

Every endpoint passes fail-closed bounded chat preflight before candidate work.
A primary with both local runtime paths is managed; omitting both paths uses
an externally started primary without lifecycle ownership; a distinct generation server
is externally started and unmanaged. GPU preflight and full offload checks remain.
Failure/interruption cancels queued work and drains active producers/workers.
One candidate match matrix runs at a time, retaining ten match workers. Self-play
opponents remain immutable; an actual dependency on this batch's unprepared
candidates retains a preparation barrier. Parent fitness refresh precedes
reproduction because parent selection needs those scores. Rewards, survivor
selection, pool updates, atomic persistence and trace cleanup wait for dependent
evaluations. Initialization uniqueness retries retain their canonical order.

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
