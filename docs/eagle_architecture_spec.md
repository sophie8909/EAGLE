# EAGLE architecture specification

Status: authoritative current contract, 2026-10-21.

This document describes executable EAGLE behavior. Unless stated otherwise, sections 2-14 describe `java_materialization_mode: llm`; section 15 specifies the deterministic override. Historical NSGA-II,
two-objective, seven-opponent, split-runtime, inline-prompt, and `eagle-run-v1`
contracts are intentionally absent; Git history is the archive for those designs.

## 1. System boundary

EAGLE evolves prompt-defined Java MicroRTS agents offline. An LLM may generate or
reflect on candidates before evaluation, but a running match never calls an LLM.
Each phenotype is one complete `ai.generated.CandidateAgent` Java source file.

EAGLE does not evolve patches, runtime LLM policies, or surrogate fitness
models. Evolution evaluation is explicitly configured as either the default
fixed roster or immutable-snapshot self-play.

## 2. Candidate model

In `java_materialization_mode: llm`, every candidate has two active evolving prompt values:

1. `strategy_prompt` — canonical versioned JSON DSL policy gene (`policy_prompt` conceptually)
2. `generation_prompt` — the reusable policy-to-Java translation gene (`code_generation_prompt` conceptually)

`candidate_java_mode` selects the Java state boundary independently of materialization mode. The default
`generated_phenotype` mode keeps Java as non-inherited phenotype/evidence.
The explicit `inherited_genotype` mode adds a third component: the complete
Java source selected from a parent or the configured generation-zero Java
seed. The Generator consumes that inherited source and produces the candidate's
new Java component and phenotype. Evaluation does not overwrite either prompt
gene or the persisted pre-generation Java input.

In `llm` materialization mode, Code checks and corrective children retain their exact source Java in
`inherited_java` with `java_parent_id` for repair provenance in either mode.
In default mode this is operator input/evidence; ordinary crossover still
inherits only the two active prompt genes in LLM materialization.

First-class candidate state includes identity, generation, direct parents,
operator, mutation type, component-source IDs, generated Java, validation and
compile status, active-mode fitness, executable semantic summary, diagnostics, failure state, artifact
references, and timing.

New candidate identities are generation-qualified as
`gen_<zero-padded-generation>_<deterministic-suffix>` so run artifacts remain
unique and easy to navigate. EA factories derive the suffix from the root seed
and stable lineage identity. `Candidate` never synthesizes an identity from
process randomness; every candidate must receive an explicit non-empty ID.
Persisted IDs are opaque references and are never renamed while loading or
resuming a run.

### Policy DSL and LLM-mode reproduction gate

`strategy_prompt` remains the policy gene, serialized as canonical versioned JSON
DSL (`version: "eagle-strategy-dsl-v1"`). Its ordered `rules` contain `actor`,
`when`, and `action`; `eagle/strategy_dsl.py` validates and normalizes the closed
vocabulary. Legal-action guards are intrinsic, and zero rules mean idle. The DSL
is translated into Java offline; there is no runtime interpreter. New runs reject
natural-language policies. Historical natural-language artifacts remain read-only;
incompatible old checkpoints fail resume clearly, without silent conversion.

In `llm` materialization mode, every selected reproduction source passes an independent Code Reflection gate
against its own policy and exact Java before actual crossover or mutation. All
contributors must be healthy. A diagnosed defect instead creates a one-parent
corrective Java child with unchanged policy/generation genes and source provenance,
skipping crossover and ordinary mutation. Failed/unusable diagnosis is never a
healthy pass and cannot enter crossover/mutation. Healthy sources follow normal
crossover and Strategy/Prompt mutation. Code gating has no adaptive probability
or AOS reward. Corrective revision runs at the `generation_model` boundary (or
primary model when absent) and bypasses ordinary Generator overwrite.

Code diagnosis schema `eagle-code-reflection-v6` has exactly two independent
dimensions: `strategy_fidelity` (`faithful`, `unfaithful`, `ambiguous_strategy`)
and `code_correctness` (`correct`, `incorrect`). Only failing dimensions may have
diagnosis entries, each with concrete evidence and a minimum required correction.
Correctness covers real compilation/runtime/control-flow defects and game/API
violations. Unknown fields, cosmetic/simplification dimensions, and extra
directives are rejected. Ambiguous strategy with correct Java needs no revision.
No win/loss optimization or cosmetic refactoring is allowed. Strategy Reflection
continues to use exactly one worst completed match; its Coach returns validated
DSL while changing only the policy gene.

## 3. Evolution lifecycle

In the default `generated_phenotype` mode, generation zero creates one candidate
per configured seed policy file, pairs each policy with the checked-in callable
no-op Java seed without calling the Generator, and does not replicate a seed to
fill `population_size`. In inherited `configured_seeds` mode, exactly one
configured seed policy is copied to `population_size`; every copy receives the
same Java component and independently calls the Generator before evaluation.

The explicit `initial_population_mode: llm_generated_policies` instead keeps
that one configured policy as the first candidate and independently asks the
LLM for one concrete RTS policy for every remaining population slot. Generation
zero persists those policy-only calls, then independently invokes the Java
Generator for every candidate. The configured Worker Rush Java is inherited
revision context in each request, not the generation-zero phenotype. Thus each
initial policy is materialized into its own validated and compiled Java agent.

Each later generation produces a fixed-size offspring population. The `llm` sequence below uses the Code gate and prompt operators; `deterministic_dsl` instead selects/copies whole policies, applies Strategy mutation only, and compiles the resulting policy.

1. select reproduction sources for every offspring slot;
2. gate each source against its own policy and exact Java before any actual
   crossover/mutation; retain one-parent corrective/failure children for sources
   that do not pass, and use only healthy contributors for normal crossover/copy
   and optional Strategy/Prompt mutation assignment;
3. In `llm`, each child completes its own reflection/rewrite before materialization:
   ordinary Java generation for healthy variation or evidence-guided corrective
   Java revision for defective-source children;

4. validation, compilation, integration, and evaluation;
5. optional AOS reward collection;
6. mode-specific survivor selection without replacement from the joint
   parent-plus-offspring (`mu_plus_lambda`) pool;
7. atomic generation persistence.

The fixed-size survivor population is selected from the joint parent and
offspring pool. Failed candidates remain in that pool for diagnostics, but are
not eligible to displace completed candidates; a failed offspring batch thus
leaves valid parents in place. Selection fails explicitly when fewer than the
configured population size completed candidates remain. Fixed roster compares
the same ten cases by lexicase.
Self-play compares scalar Game Performance and consults executable semantics
only inside an inclusive `1.0` fitness tier. Generation age never breaks ties.

The canonical `parent_evaluation_mode: reuse_cached` does not regenerate or
re-evaluate surviving parents. The explicitly non-canonical diagnostic mode
`regenerate_same_genotype` is restricted to `inherited_genotype` and static
reflection. After ordinary offspring evaluation, it creates a fresh-ID replica
of each parent with byte-identical prompt and inherited-Java genotype, clears
all phenotype/evaluation state, and runs the normal generation and evaluation
pipeline. Survivor selection then uses replicas plus offspring and excludes the
old parent identities. This mode measures the total effect of parent
rematerialization plus match resampling; it is not the production protocol.

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
One candidate match matrix runs at a time, using ten match workers by default.
An explicitly configured `evaluation.match_execution: serial` runs the same
matrix with one worker to reduce scheduling variance during same-seed audits.
Self-play
opponents remain immutable; an actual dependency on this batch's unprepared
candidates retains a preparation barrier. Parent fitness refresh precedes
reproduction because parent selection needs those scores. Rewards, survivor
selection, pool updates, atomic persistence and trace cleanup wait for dependent
evaluations. Initialization uniqueness retries retain their canonical order.

## 4. Reproducibility

`random_seed` is the EA-wide root seed. Execution always seeds controllable
randomness; there is no general deterministic/non-deterministic mode switch.
`evaluation.match_execution` defaults to `parallel` and may be set to `serial`
for ordered, one-worker match execution that reduces scheduling variance. This
does not control external opponent wall-clock budgets or private RNGs and thus
does not guarantee bitwise-identical match outputs. Legacy
`deterministic_mode` keys in saved configurations are ignored and omitted from
new resolved configurations. Stable task identities and named streams derive
seeds for candidate initialization/IDs, parent and survivor selection,
lexicase case ordering, operator choice, mutation, crossover, reflection
sampling, and LLM requests/retries. Streams do not depend on thread identity,
completion order, wall-clock time, or Python's randomized `hash()`. Compiler-based
LLM prompts retain filenames and diagnostic line numbers while removing
incidental absolute run paths; raw compiler artifacts retain original evidence.

Generated strategy code must use `rts.RandomSource.create` with stable namespaces
for stochastic choices and game cycles for timing. The shared strategy-contract
guard rejects standard entropy APIs and wall clocks; generation/repair prompts
state this rule. It is a source contract check, not a general Java sandbox.

Every normal, parent-offspring, and final-test match derives a positive JVM
seed from the root seed and immutable candidate/opponent/map/round/side/match
identity, passes `-Deagle.match.seed`, and records it in artifacts. Vendored
MicroRTS random sources consume this property. Parallel workers return results
in canonical matrix order, so seed assignment, fitness aggregation, and seeded
tie-breaking are independent of scheduling. LLM endpoint assignment is likewise
derived from canonical input index and the persisted endpoint order, not thread
or completion order. GPU layers (`999`), model threads (`8`), managed-local
server slots (`2`), and LLM workers (`2`) are fixed by `eagle/execution.py`;
match workers remain `10` by default and are reduced to
`1` by the persisted serial option. CUDA/GPU preflight is required before
managed local server startup; unavailable GPU support fails instead of falling
back to CPU.
Temperatures remain configurable. New generation checkpoints preserve
stagnation and bounded EA archive state; independent generation streams allow
same-version resumes to continue the same seeded trajectory. Uncommitted
candidate/decoder/class artifacts and their LLM logs are retained under
`archives/interrupted_work/attempt_<nnnn>` before replaying their stable IDs.
The controller resumes from the manifest's exact completed checkpoint.

Reproducibility requires the same code, inputs, configuration, and deterministic task outputs. Request seeds ask an external
LLM service to repeat its sampling; providers may ignore seeds or change
models. GPU kernels, backend batching, floating-point reductions, different
builds/hardware, external opponent binaries with private RNGs, and wall-clock
search/timeout budgets can still change outputs. A differing LLM response or
match result can change subsequent evolution. Persisted request/response
hashes and match seeds provide evidence; timings, process IDs, and run-directory
timestamps are operational metadata and are not bitwise reproducible.
Historical runs created before this seed-stream change retain their artifacts
but are not promised the same evolutionary trajectory when resumed.

For direct multi-run configs, omitting `random_seeds` preserves the legacy
schedule of `random_seed`, then `random_seed + 1`, and so on. When
`random_seeds` is provided, `runs` is the repeat count for each listed seed in
list order; for example, `[7, 8, 9]` with `runs: 2` schedules
`7, 7, 8, 8, 9, 9`. Each scheduled run still owns a separate run directory
and receives its effective seed in the request/artifact metadata.

## 5. Crossover and lineage

Uniform crossover independently selects `strategy_prompt` and
`generation_prompt` from the two parents. In `inherited_genotype` mode it also
independently selects the complete Java component. Lineage persists the direct
parent IDs and the source candidate ID for every active component, even when
component values are equal. Default-mode lineage has no Java parent.

## 6. Mutation

The reflection operator is chosen by exactly one configured mode:

- `static`: fixed Strategy/Prompt probabilities and no reward work;
- `aos_opponent`: execution-first ten-case rank-change reward against the
  recorded mutation-evidence parent;
- `aos_head2head`: configured mutation-evidence-parent versus offspring match
  matrix reward.

Both adaptive modes use the same alpha-`0.20` EMA and probability-matching
updater with the configured minimum probability floor. AOS never changes the
active fitness contract; adaptive modes apply to fixed-roster lexicase runs.

The adaptive comparison parent is the same evaluated candidate used to build
the mutation context: the policy-component parent for Strategy mutation; the
generation-prompt parent for Prompt mutation in default mode; and the
Java-component parent for Prompt mutation in inherited mode. Component
provenance, rather than direct-parent position or prompt-text equality, selects
this parent. Both reward providers consume the resulting
`comparison_parent_id`.

Strategy mutation resolves evidence through recorded `strategy_parent_id` and
selects exactly one worst completed match from that parent's evaluation. The
lowest finite numeric per-match `performance` is worst; if missing or
non-finite, use loss `-100`, draw `0`, win `100`. Ties use stable `match_id`
order independent of seed, and failed matches are excluded. One Match
Commentator diagnoses that match; the Coach receives the all-match global
evaluation summary and exactly that one diagnosis. If its trace is unavailable
or commentary exhausts retries, the existing failure path preserves the parent
policy without selecting a replacement match. Strategy mutation changes only
`strategy_prompt`, after which the normal final Generator decodes the child.
Initial policy generation, Match Commentator, Coach, the library
Strategy path, and Strategy Alignment receive the immutable closed-world
MicroRTS gameplay contract. The contract permits arbitrary legal strategy types.
Coach and its strategy-contract rewriter emit one compact JSONL record per
ordered strategy rule. Every record is field-targeted and its complete rule is
validated independently. Valid rules retain physical-line order; malformed
lines and whole semantically invalid rules are discarded and recorded. A
non-empty legal subset succeeds, and only zero legal rules fails the role. No
condition/action subtree is repaired inside a rejected rule. Legacy whole JSON
and full-fence responses remain readable under all-or-nothing validation, and a
whole echoed parent policy cannot match the child rule-record schema.

In `llm` mode, Prompt mutation is the former Code Reflection behavior. In default mode it
compares the source parent's policy with its Java phenotype. In inherited mode
it compares the child's independently selected policy with its inherited Java.
The Reviewer receives only the editable Java strategy region, the policy, the
immutable action/API guide, and source-matching validation/compiler diagnostics.
It never receives game performance, opponent scores, W/D/L summaries, match
results, traces, logs, aggregate fitness, or other gameplay evidence. The Prompt
Rewriter then returns one validated reusable-rule delta and changes only
`generation_prompt`; the normal final Generator decodes the child from the
updated prompt gene.

In `llm` mode, Code Reflection is the independent pre-crossover source gate described above,
not an ordinary mutation or AOS action. It permits only evidenced defect and
policy/Java mismatch correction. Its two-stage diagnostic/revision artifacts
preserve raw responses and both prompt genes.

In `llm` mode, normal mutation probabilities and adaptive credit cover only
`strategy_reflection` and `prompt_reflection`. Operator state is `eagle-reflection-operator-v6`. Legacy probability inputs
normalize Strategy/Prompt weights with Code fixed at zero; all-zero weights skip
normal mutation. The independent source gate still runs.

Each normal LLM-mode child stores `pre_crossover_code_checks` entries with
`source_candidate_id`, `gate_candidate_id`, `healthy`, `reflection_status`,
`revision_required`, and `artifact_path` (`../{gate_id}/mutation/code_reflection`).
Source A uses a deterministic source-check ID; donor B, when needed,
uses a deterministic donor-check ID. Evidence belongs to check candidates, never
the evaluated source-parent directory. A defective/failed check emits its
one-parent diagnosed child, preserving the fixed offspring count.

Resolved configs carry `evolution_protocol: eagle-dsl-pre-crossover-v1` and
`strategy_policy_format: eagle-strategy-dsl-v1`. Resume requires the protocol
marker before touching run artifacts. Candidate/artifact schema versions remain
current, with an additional `strategy_policy_format` field; operator state uses
`eagle-reflection-operator-v6`. Historical runs remain inspectable, but cannot
resume under the changed algorithm.

All executable prompt bodies live as individual UTF-8 text files under
`prompts/`. Python and YAML may reference, render, bound, transport, and validate
prompt resources but may not contain alternate executable prompt bodies.

In `llm` materialization with `inherited_genotype`, only gated healthy sources participate in independent
component crossover. Strategy and Prompt preserve the selected Java input for the
final Generator. Corrective children instead retain one source's complete genotype
and revise its exact Java at materialization, preserving source provenance.

## 7. LLM Java generation and validation

In `generated_phenotype` mode, generation 0 remains the decoder exception: the
configured policy uses `initial_java_seed_path` as a fixed phenotype without a
Generator call. In inherited `configured_seeds` mode,
`initial_java_seed_path` is the third pre-generation component for every
replicated seed candidate; each candidate makes an independent bounded Generator
call and persists normal request, raw response, attempt, validation, and
compilation evidence. In inherited `llm_generated_policies` mode it is the
shared third component; policy-only LLM calls fill the remaining population
slots and every slot then performs normal bounded Java decoding in generation
zero.

In `llm` materialization, except for Code Reflection children, final materialization consumes the two active prompt
genes plus the fixed checked-in Java scaffold/API constraints and returns
exactly one complete Java source file. In `inherited_genotype` mode it
additionally receives the selected inherited Java component as revision
context; default mode receives no parent Java. A Code Reflection child instead
enters this boundary with the complete source returned by the operator. It
never receives game logs. Raw response, extracted source, normalized source,
attempts, actual endpoint/model identity, errors, and timing are persisted.

The required `model` section owns initialization, reflection, and prompt rewrite.
Its ordinary fields define the primary endpoint. Both local runtime paths
enable managed startup; omit both to call an external primary directly. It may additionally
contain an ordered `additional_endpoints` list with zero or one entry of the
form `{base_url, model}`. The additional endpoint is an unmanaged
OpenAI-compatible service: it has no local GGUF or llama-server path, is never
adopted or stopped by EAGLE, and is used only through request dispatch and
preflight.

Optional `generation_model` routes Java generation, corrective revision and
compile repair to its own already running server. Different model identities
require distinct hosts/ports. Omitting it reuses `model` concurrently. Only the
primary runtime with both local paths is managed; generation and additional servers remain
unmanaged. No runtime model switching occurs.

The extracted response must itself satisfy the complete-file external envelope:
package/class/superclass, constructors, lifecycle methods, security restrictions,
and exactly one ordered strategy-marker pair. After that check, the decoder
deterministically constructs
normalized_candidate.java` from the configured
canonical scaffold plus only the extracted strategy region. Model edits outside
the strategy region therefore remain visible in `response_raw.txt` and
`extracted_candidate.java` but cannot enter validation, compilation, or the
canonical phenotype. A partial, structurally invalid, or prohibited response is
not made valid by scaffold normalization.

Offspring decoding may use up to `generation_max_attempts`. Normal attempt 1
consumes the authoritative active-genotype generation request; a Code Reflection
attempt 1 consumes the already-returned complete source without another LLM
call. A normal extraction failure may repeat that base request. After a complete
source fails validation or compilation, the
next attempt consumes the separate compile-repair prompt containing the unchanged
authoritative genes, immutable scaffold/API guide, the immediately previous
complete source as untrusted phenotype evidence, and only that attempt's
structured validation/compiler diagnostics. Compile repair changes no gene,
lineage, AOS state, selection case, or strategy intent and is distinct from Code
Reflection. Each actual request and source owns its hash and evidence. The first
validation+compilation success is the sole canonical phenotype. If all attempts
fail, the final attempt owns the candidate failure classification and remains
generation evidence rather than a canonical phenotype. Fixed-Java generation
zero loads once per candidate without a Java LLM attempt; inherited
`configured_seeds` and `llm_generated_policies` generation zero use the
configured bounded attempt budget independently for every candidate.

Validation requires:

- package `ai.generated`;
- public final class `CandidateAgent`;
- superclass `AbstractionLayerAI`;
- required one- and two-argument constructors;
- `getAction`, `reset`, and `clone` contracts;
- token-equivalent checked-in source outside the single editable strategy
  region;
- strategy-helper scope and array-shape constraints, including an explicit
  `AgentContext context` parameter for every helper that reads `context`, local
  or parameter ownership for `gameTime`, and `int[][]` for nested coordinate
  pairs; direct strategy-region `GameState.free(...)` and
  `PhysicalGameState.getTerrain(...)` reads are rejected in favor of the fixed
  bounds-safe `isFreeCell(context, x, y)` helper;
- no network, process execution, unauthorized file I/O, runtime modification,
  or unavailable dependencies.

The token-equivalent scaffold check applies to the normalized complete source.
Strategy validation and javac also consume that same source, so every successful
phenotype contains the configured scaffold around the generated strategy rather
than a model reconstruction of fixed code.

Internal helper names and implementation inside the editable strategy region
remain flexible within those deterministic Java/API constraints.

## 8. Shared compilation and integration

Each decoder-attempt Java source that passes validation is compiled at
most once in an attempt-isolated class directory with the MicroRTS classpath and
`-Xlint:all`. Structured, deduplicated errors and warnings are persisted. The
first successful class tree is promoted without recompilation and is the only
tree visible to Integration. Integration or runtime failure does not trigger a
new decoder attempt.

Before matches, the standalone integration probe performs seven ordered checks:
class loading, AI inheritance, constructors, reset, clone, getAction, and valid
PlayerAction. The `getAction`/`PlayerAction` checks load the populated real
8×8 bases/workers map into independent states, exercise both candidate sides
with independent one-argument instances, and verify action integrity, safe
issuance, and one cycle. A failed prerequisite blocks later checks and prevents
matches. Integration failure does not re-enter the decoder.

`eagle/evaluation/microrts_runner.py` owns only this integration probe.
`eagle/evaluation/runtime_evaluation.py` is the sole match-execution owner.

## 9. Evolution evaluation

`evaluation.mode` selects `fixed_roster` (default) or `self_play`. Both modes
use the same ten-opponent-slot, three-map, three-round, two-side matrix, so every
runnable candidate has 180 matches. Their selection objectives differ:
fixed-roster uses ten opponent-wise lexicase cases; self-play uses only scalar
Game Performance.

The fixed search roster is:

1. PassiveAI
2. RandomAI
3. RandomBiasedAI
4. LightRush
5. HeavyRush
6. WorkerRush
7. AllInBot
8. Mayari
9. COAC
10. TMA

Every runnable candidate uses the same source and compiled classes for 180
matches: ten opponents × three maps × three rounds × two player sides. Each
`evaluation.maps` entry may define its own positive `tick_limit`; string-only
map entries inherit the top-level `tick_limit` for backward compatibility. The
resolved per-map cap is carried by the match matrix and is used unchanged by
normal evaluation, AOS head-to-head evaluation, and final testing.

AllInBot preflight verifies the pinned upstream class/JAR before execution.
Its separately compiled reflection adapter is outside the candidate phenotype
and only contains upstream `Exception`, null-action, or invalid-action faults
with a permanent legal passive fallback. A completed contained match retains
its observed raw evidence but has canonical opponent-fault fields and a neutral
zero-score draw for candidate scoring; it is neither a candidate win nor a
candidate runtime failure.

In `self_play`, the maintained opponent pool and each generation's immutable
evaluation context are separate. The pool starts with every entry in
`SEARCH_OPPONENT_REGISTRY`. `allinbot`, `mayari`, `coac`, and `tma` are permanent
protected members: they are never eligible for pool tournaments or eviction.
The other six built-in baselines (`passive`, `random`, `randombias`,
`lightrush`, `heavyrush`, `workerrush`) and admitted generated agents are
tournament-eligible. `evaluation.self_play_opponent_library_capacity` sets total
pool capacity, including the four protected members; it defaults to 50 and must
be at least 10.

After generation zero and each completed offspring evaluation, add novel
eligible agents while capacity remains. Deduplicate by candidate ID, source,
and semantic phenotype. When full, each novel entrant challenges one seeded,
sampled nonprotected incumbent in a complete head-to-head of three maps, three
rounds, and both sides (18 matches). Count each win as 1, draw as 0.5, and loss
as 0. Replace the incumbent only when the entrant has strictly more wins than
losses; ties retain the incumbent. Incomplete or failed duels cannot promote
the entrant, and their failure evidence is retained. The tournament does not
call an LLM; it reuses the entrant's source/classes and prepares the defender
with the existing opponent adapters.

Generation zero evaluates all ten built-in sources using the same fixed slot
schema as later contexts: the four protected members use their actual case IDs,
and the six other built-in sources occupy `self_play_000`…`self_play_005`. At
generation one and each subsequent `evaluation.self_play_refresh_interval`
boundary (generations 1, 6, 11, ... with the default interval 5), retain those
protected case IDs and fill the six diagnostic slots with a deterministic
sample of nonprotected pool members. Every slot has equal weight, and the
candidate matrix remains 180 matches. Context rows record `source_opponent_id`
for each built-in source; `source_candidate_id` and `source_generation` are null
for built-ins.
Re-evaluate phenotype-preserving fresh-ID parent replicas whenever this
context changes, before selection; only candidates evaluated against the same
context may enter selection.

Persist the pool in `archives/self_play_opponents.json` (`eagle-opponent-pool-v1`)
with capacity, protected IDs, member references, and phenotype hashes. Persist
each duel under
`archives/opponent_pool_tournaments/generation_NNNN/<entrant_id>/result.json`
with per-match evidence, and record tournament duration as the
`opponent_pool_tournament` timing event. Context snapshots use
`eagle-self-play-snapshot-v4`, member references, and a context hash. Checkpoint
pool state in the existing `resume_archives` and restore it before replay.
Snapshot `runtime_identity` hashes the actual configured MicroRTS `src`, `bin`,
and `lib` assets, builtin opponent JARs, opponent adapters/support libraries,
and map file bytes. `load_self_play_snapshot` verifies this identity before
cached fitness reuse; asset changes require a new run. Persisted
`evaluation/game_performance.json` also includes `evaluation_configuration`,
`evaluation_context_id`, and `fitness_case_ids` alongside scores so resume can
confirm cached fitness belongs to the active context. Tournament evidence
hashes the prepared/renamed runtime class tree used for a candidate defender.
Builtin entries retain source and resolved-class hashes when available.
Self-play resolved configs require
`evaluation.self_play_pool_policy: tournament-v1`. A self-play run without
this exact marker cannot resume under the changed policy; inspection remains
supported. `fixed_roster` behavior is unchanged. The old cohort archive helper
may remain for historical reads, but it does not schedule active contexts.

Self-play currently requires `reflection_operator_mode: static` and
`parent_evaluation_mode: reuse_cached`; the fixed-opponent archive is not
updated by self-play runs.

Fixed-roster fitness is a maximized mapping with the ten opponent case IDs.
Self-play fitness is `{game_performance: value}`; failed or incomplete
candidates receive `-1000.0`. Fixed-roster aggregate Game Performance is
reporting-only, using weights `0.5` for PassiveAI, RandomAI, and
RandomBiasedAI, `1` for the three rush opponents, and `2` for AllInBot, Mayari,
COAC, and TMA. Self-play uses the unweighted mean as its objective.

Self-play additionally enables a versioned nine-state semantic dataset:
exactly the configured three maps at early, middle, and late trajectory phases,
always for the configured player side. A fresh full `CandidateAgent` instance
acts on each reloaded state. Unit actions are canonically ordered and hashed;
the ordered nine-action vector defines exact equivalence for the opponent
library, while semantic distance is normalized Hamming distance over the nine
action hashes.
Scores within `fitness_tie_tolerance` (default and canonical value `1.0`,
inclusive) of a tier's maximum are equal for selection. Tiers use that maximum
as a fixed anchor, so pairwise chaining cannot merge a worse candidate. Missing
or incompatible signatures are fallback evidence, never maximally novel.
Within the top tier, parent B minimizes compatible semantic distance to parent A,
excluding parent A when another tier member exists. A singleton tier reuses its
only member. Equal distances use seeded choice in candidate-ID order. Survivor
boundary selection retains seeded farthest-first max-min diversity.

Code Quality is a diagnostic and mutation-evidence signal, not a selection
objective. Successful Code Quality is:

`100 - (40C + 25N + 20L + 15F)`

where the terms are normalized cyclomatic complexity, nesting, logical LOC, and
longest-function LOC. Failure Code Quality is `-1000.0`. Compiler diagnostics remain available to reflection and failure records. Normal
evaluation does not call Function Capability or Strategy Alignment and writes no
related diagnostic files or timing. The standalone helper modules remain available
to explicitly invoked tooling.

## 10. Match evidence

Each match owns one directory and one compressed tick stream:
`match_trace.jsonl.gz`. The trace contains structured state, source tick text,
fallback result evidence when no round-state file exists, metadata, result, and
an integrity report. Strategy Reflection consumes this same trace. A second
`match_log.jsonl.gz` format is prohibited.

Compact mode may remove replay and raw round-state files after canonical
telemetry and trace persistence. Parent traces remain available until every
same-generation sibling has been constructed. Only after atomic survivor
persistence may traces for retired parents and discarded offspring be removed;
survivor traces remain available to the next generation.

## 11. Run schema

New and supported runs use only `eagle-run-v2`:

- `manifest.json`
- fully resolved `config.yaml`
- `timing.jsonl`
- `summary.json`
- `generations/`
- `candidates/`
- `generated_agents/`
- `classes/`
- `archives/`
- `llm_logs/`
- `final_test/`

Generation files contain compact candidate references, metrics, AOS state, and
timing references. Each generation also has a policy JSONL sidecar containing
artifact references for every population member with a non-empty
`strategy_prompt`; it does not duplicate strategy text. Candidate state lives once under
`candidates/<id>/candidate.json`, with `genotype/policy_prompt.txt`,
`genotype/code_generation_prompt.txt`, optional
`genotype/inherited_java.java`, `phenotype/CandidateAgent.java`, and
specialized generation, validation, compilation, integration, evaluation,
mutation, lineage, and timing artifacts beside it.

The fully resolved `config.yaml` preserves every functional profile's endpoint list in its
configured order. That ordered list is execution-affecting resume identity and
cannot be added, removed, reordered, or retargeted during resume. Every LLM call
index and timing event records the actual endpoint and model selected for that
request; recording only the profile's primary identity is insufficient when an
additional endpoint is configured.

Derived analysis uses each generation file's selected population as that
generation's survivor snapshot. Per-agent, per-opponent, and per-match analysis
rows therefore use the snapshot generation on plot axes; the candidate's own
creation generation is retained separately as `birth_generation`. A survivor
appearing in multiple population snapshots appears once at each corresponding
generation without duplicating its canonical candidate artifact.

An LLM-generated generation-zero policy additionally owns
`initialization/policy_generation/`, containing one directory per attempt with
the exact request, raw response, result, and timing, plus a compact result that
references the canonical genotype policy. Raw output is written before parsing;
the run timing stream has one `initial_policy_generation` event per request. Its
request includes the same immutable gameplay contract used by strategy mutation,
so diversity sampling is not limited to Worker Rush but remains inside actual
MicroRTS mechanics.

Strategy Reflection candidates additionally retain under
`mutation/strategy_reflection/` the exact parent strategy prompt, the single
selected worst-match record and its parsed Commentator diagnosis, the structured
and rendered Coach input (including the all-match global evaluation summary),
raw and parsed Coach output, the normalized child strategy prompt, and the
strategy value supplied to Generator. Selection uses the parent resolved by
lineage `strategy_parent_id`; unavailable trace or exhausted commentary retains
the parent policy through the existing failure artifact. These are
observability artifacts only and do not introduce a separate policy state.

`resolved_config.json`, `generation_metrics.jsonl`, `final_population.json`,
root `errors.jsonl`, duplicate match results, and `eagle-run-v1` readers are not
supported.

## 12. Experiment lifecycle

The production entrypoint is:

```bash
./experiment.sh CONFIG_FOLDER_OR_YAML [--mock] [--skip-final-test]
./experiment.sh --resume RUN_DIR_OR_CONFIG_FOLDER [--mock] [--skip-final-test]
```

It delegates to `python -m eagle experiment`. Python owns sorted config
discovery, validation of `model` and optional `generation_model`, managed-local
llama.cpp start/health checks, all-endpoint chat preflight, per-run restart,
dependency-driven scheduling, search, resume, final test, and owned-process
cleanup. `RuntimeManager` owns only the primary local llama.cpp process.
An additional endpoint is always external and unmanaged; it is never adopted,
restarted, switched, signalled, or killed. Mock mode does not construct a runtime
manager.

For a directory batch, the selected config directory owns `experiment.yaml`
with `schema_version: eagle-experiment-index-v1` and a `runs` mapping from each
exact config filename to an ordered list of absolute run-directory strings.
List positions are zero-based replicate indices. The index is updated
atomically as each run is created and is excluded from config discovery,
preserving partial runs. A pre-existing `experiment-v2` config named `experiment.yaml` remains a
config and is never overwritten by the index writer.

When `--resume` targets such a config directory, Python reads the existing
index instead of resetting it. Each slot's effective seed is checked against
the configured replicate schedule. Indexed runs that have not completed their
required lifecycle are processed first: interrupted/failed search resumes from
its latest atomic generation, while a search-complete run without a required
final-test summary resumes at final testing. Fully completed slots are skipped.
Missing replicate slots are created after indexed recovery; each new run is
added atomically to the same index. A fresh launch starts a fresh index. A direct
run-directory target retains the single-run resume behavior. If interruption
occurred before generation 0 was atomically recorded, a framework-slot run with
a validated run-owned frozen bundle resumes in place from its framework startup
checkpoint and replays generation-zero initialization without another provider
call. Partial generation-zero evidence is archived first. Other runs replace
that slot with a new run and update the index because no resumable population or
startup checkpoint exists; prior evidence remains on disk.

Legacy plain filename-to-path mappings remain readable as one-item replicate
lists and are upgraded atomically the next time a run is recorded. The exact
filename-to-runs index is also the identity anchor for folder resume.
It may therefore tolerate a corrected human-readable `experiment_name` while
still requiring every execution-affecting config field to match the immutable
run-local definition. Direct config-plus-run resume remains strict, including
the experiment name.

`python -m eagle analyze` and `analyze.sh` are the only offline analysis
entrypoints. Separate `run`, `runtime`, `run.sh`, and `run_env.sh` compatibility
surfaces are prohibited.

## 13. Verification

Behavior changes require focused contract tests followed by:

```bash
python3 -m compileall eagle
python3 -m unittest discover -s tests
git diff --check
```

A bounded real Java/MicroRTS integration probe may supplement unit tests. A full
evolutionary experiment is never required for repository validation unless the
operator explicitly requests it.

## 14. Implementation ownership

Executable Python is packaged under `eagle`. `eagle/evolution` owns run and generation orchestration, `eagle/operators` owns independently editable EA operators, `eagle/generation` owns source generation/validation, and `eagle/evaluation` owns decoding, opponent preparation, match dispatch, scoring, and candidate evaluation. Internal imports target the actual owner; obsolete import shims are removed. The [repository map](implementation/repository_map.md) specifies module entrypoints. Configuration, assets, and serialized run/checkpoint contracts remain unchanged.


## 15. Java materialization modes

`java_materialization_mode` is independent of `candidate_java_mode`. Its absent
value defaults to `llm`, retaining historical behavior. `llm` keeps the existing
active genotype (policy and generation prompt, plus optional inherited Java),
LLM generation/revision flow, and its established version markers.

`deterministic_dsl` uses only the complete normalized `strategy_prompt` as its
active genotype. Generation prompt and inherited Java are inactive compatibility
data and must not be passed to phenotype materialization or presented as active
genes. It allows whole-policy copy/crossover and Strategy mutation only; it
disables Prompt Reflection, Code Reflection/source repair, the Java source gate,
Java Generation, and compile-repair requests. It does not add rule-level
crossover. The protocol is `eagle-dsl-compiler-v1`; compiler version is
`eagle-dsl-java-v1`. The typed-IR compiler and canonical Java scaffold create the
complete phenotype deterministically, then normal validation, javac, Integration,
semantic probe, and match evaluation continue. Equal normalized policy,
compiler version, and scaffold must yield byte-identical source. Compiler,
validation, or javac failure retains stage evidence and uses the canonical
failure sentinel; no LLM fallback is allowed. Fitness, objective, self-play,
fixed-roster, and selection formulas are unchanged.

The checked-in generation-zero WorkerRush seed is the only reference policy in
DSL v1. It has empty `rules` and `reference_agent: "WorkerRush"`. Deterministic
materialization delegates to the vendored canonical
`ai.abstraction.WorkerRush`, replays its complete `PlayerAction` through the
fixed CandidateAgent action boundary, and records the exact vendored source
hash. LLM initialization and Strategy mutation cannot emit reference policies;
all evolved policies remain ordinary finite rules.

Candidate artifacts record mode, compiler version, and
`active_genotype_components`; deterministic values are exactly
`["strategy_prompt"]`. Compiler evidence uses `generation/compiler_evidence.json`
(`eagle-dsl-materialization-v1`), `generation/normalized_policy.json`,
`generation/compiled_candidate.java`, and `generation/scaffold.java`. Evidence readback checks the normalized policy, emitted source, and scaffold hashes; resume checks the configured scaffold hash against persisted evidence. The result records operation
`deterministic_dsl_compile`, policy/scaffold/source hashes, deterministic
diagnostics, and an empty `llm_attempts` array. It also records nullable
`reference_agent` and `reference_source_sha256`; readback verifies the vendored
source hash whenever a reference policy is active. Deterministic candidate snapshots
use `eagle-candidate-v7`, and their generation results use `phase4-v7`;
shared downstream stage schemas retain their existing versions. The LLM path retains `eagle-candidate-v6`
and `phase4-v6`. Deterministic configuration requires `candidate_java_mode: generated_phenotype` and `parent_evaluation_mode: reuse_cached`; any other values are rejected. Resume rejects unknown compiler versions, protocol mismatches,
and attempts to cross materialization modes before replay. Historical configs
without the field remain LLM mode. Focused contracts and bounded real self-play
validation pass; see `testing/test_contracts.md` for verification and environment
limitations.

## 16. Framework bootstrap and finite-slot mode

`framework_slots` is a third Java materialization mode. On fresh startup, EAGLE
uses an explicit external `framework.bundle_path` if supplied. Otherwise, startup
requires `framework.design_brief` and accepts optional `framework.model`
(default `openai/gpt-oss-120b`) to bootstrap the framework inline.
`framework.bootstrap_backend` selects the default `groq` API path, the `mistral`
API path, the direct `gpt` OpenAI API path, the `codex` CLI-first path with GPT
API fallback, or the configured local llama-server path.
`framework.bootstrap_scope` defaults to `run`; `experiment` assigns the first
scheduled seed as the sole inline-bootstrap owner and copies its exact initial
bundle into each later run. `framework.bootstrap_max_attempts` is the total
HTTP-generator attempt limit.
Groq reads `GROQ_API_KEY`, Mistral reads `api_key/mistral`, and GPT reads
`api_key/gpt`; the local path reads no API key. The standalone
`python -m eagle framework` CLI remains available for compatibility. Startup
persists raw responses before parsing and publishes one strictly validated
`eagle-framework-bundle-v1`. `GROQ_API_KEY` is read only from the environment
when the selected backend is `groq`; `api_key/mistral` is read only when the
selected backend is `mistral`; `api_key/gpt` is read only when the selected
backend is direct `gpt` or a failed `codex` attempt. The GPT path targets
`https://api.openai.com/v1/chat/completions` and uses `gpt-6.1-sol` when selected
by the experiment config. The `codex` path invokes one read-only, ephemeral,
schema-constrained `codex exec` using the existing Codex login; a missing
executable, timeout, nonzero exit, or invalid output activates bounded GPT API
fallback. These providers are used only for initial bootstrap;
`framework.evolution_mode: reflection` continues
to use the top-level local experiment model for all later reflection calls.
Bootstrap is a startup operation, not part of EA;
`framework.evolution_mode` selects local evolution (the default), the opt-in
Coach-assisted selection path, or self-play framework `reflection` described below.
The structured bundle has exactly `schema_version`, `framework_id`,
`java_template`, `slots`, `slot_generation_prompt`, and `report`. Each slot has
exactly `slot_id`, `kind`, `marker`, `default`, `minimum`, `maximum`, `step`,
`choices`, and `purpose`; its canonical marker is
`{{EAGLE_SLOT:<slot_id>}}`. Kinds are finite-lattice `integer`, finite-lattice
`number`, or `expression_choice`. Every expression choice has exactly
`choice_id`, `java_expression`, and `description`; the candidate stores only the
choice ID, so formulas are selected from bundle-frozen expressions rather than
generated as source. The report has exactly `architecture_summary`,
`decision_flow`, `invariants`, `slot_rationale`, `assumptions`, and `risks`, with
`slot_rationale` mapping exactly all slot IDs to nonempty strings. The complete
schema and bootstrap prompt contract are canonical in
[framework slots](architecture/framework_slots.md).

External bundles are validated during config resolution; inline bundles are validated during startup. Both paths freeze exact bytes and record their schema
version and SHA-256. Run creation freezes a run-owned copy; each replicate bootstraps its own framework unless all use the same explicit bundle path or the config selects experiment scope. Experiment-scoped later runs copy the first seed's bytes and then evolve independently. Resume compares design brief, bootstrap backend/model, scope/attempt limit, and evolution mode, rejects
version/hash drift and never adopts a changed external file. The frozen bundle,
resolved config, and manifest form an atomic pre-generation startup checkpoint.
If generation zero is absent, resume archives partial post-bootstrap work and
replays generation-zero initialization from that checkpoint without calling the
bootstrap provider again. The only active
candidate component is `control_genome`. In the default `local` evolution policy,
generation zero samples complete legal genomes; seeded uniform crossover selects
each slot independently with `slot_parent_ids`, and mutation changes at most one
slot to a different legal value. `llm_coach` requests one complete legal
genome for each initial slot. Optional `framework.coach_offspring_probability`
selects an exclusive Coach offspring route before crossover; `null` (the
default) preserves legacy Coach behavior, and numeric values from `0.0` through
`1.0` select that fraction of later offspring stochastically using an
independent seeded RNG; this is not an exact per-generation quota and is
independent of `mutation_rate`.
The Coach route copies parent A's genome and requests a complete replacement,
without crossover or parent B. The traditional route preserves the existing
configured `crossover_rate` and donor selection, followed by local single-slot
mutation at `mutation_rate`. At `0.0` all later offspring use the traditional
route; at `1.0` all use Coach. Generation-zero genomes remain Coach-selected at
all values. Resume fences the effective setting, interpreting a missing field
in older manifests as `null`. Validation is against the same frozen bundle.
Equal bundle/genome/materializer inputs produce byte-identical complete Java
and reconstructible hashes.

Framework-slot mode uses `candidate_java_mode: generated_phenotype`,
`parent_evaluation_mode: reuse_cached`, `reflection_operator_mode: static`, and
protocol/materializer version `eagle-framework-slots-v1`. The default
`framework.evolution_mode: local` performs no candidate-time LLM request. The
opt-in `llm_coach` mode uses the configured experiment model for initial
complete-genome selection. With legacy `coach_offspring_probability: null`, it
also uses the existing one-worst-match Commentator/Coach Strategy path after
crossover; an explicit numeric probability selects Coach as an exclusive
offspring operator before crossover. It does not call a Java Generator, Code Reflection, source repair,
or compile repair. Both modes render locally, and render failure has no fallback.
Successfully rendered source continues through unchanged security validation,
one javac, Integration, semantic probe, objectives, parent-plus-offspring
selection, and ten-opponent x three-map x three-round x two-side evaluation.
The bundle, slot domains, template, materializer version, and bundle hash remain
frozen in `local` and `llm_coach`; resume also compares the resolved
`framework.evolution_mode` and effective Coach offspring probability. The
latter defaults to `null` for older manifests; a numeric value requires
`llm_coach` and is rejected in the other modes.

With `framework.evolution_mode: reflection`, initial design uses the configured
bootstrap backend/model, while the local experiment model reflects on the whole
framework and every preceding survivor's complete slot list and fitness at
self-play refresh boundaries. For interval 5, G6/G11/G16 use G5/G10/G15 evidence;
G1 only refreshes the initial opponents, and the terminal generation triggers
no additional reflection. The model may change the entire architecture, slot
count, and finite domains/choices while retaining the strict slot bundle and
CandidateAgent contracts. Mating and mutation use only seeded local operators.
Generation zero begins with ten distinct authored
natural-language strategy descriptions, including faithful WorkerRush behavior;
Coach fills each initial genome following its description. Malformed initial
filling fails initialization after at most four calls, without random/default
production fallback. Only initial descriptions must differ; later descriptions
may converge and selection imposes no description-uniqueness constraint. At refresh, a
separate batch Qwen strategy reflection first revises all source individuals'
descriptions from performance, then a separate Coach stage fills their complete
new-framework genomes following those revised descriptions and using old/new
frameworks and all prior slots/fitness. It covers exactly every source ID and pins the new
exact-byte bundle hash. There is no mating/mutation Coach or Commentator call.

The initial reflection proposal plus at most three diagnostic-guided repair
calls must pass schema validation and Java validation/compilation before
activation; exhausted attempts retain the preceding active framework. Each
accepted version is immutable under `framework/versions/<sha256>/bundle.json`.
Root initial bundle/config identity is preserved; only a completed generation
snapshot activates a new version for resume. Parent replicas use Coach-selected
complete genomes, then rerender and reevaluate under the refreshed opponent
context. There is no automatic default migration. Coach parse/selection/compile
failure rejects the complete transition and shares the outer framework repair
budget; exhaustion retains the old framework, descriptions, and population.
Candidates preserve optional `strategy_description`; local offspring inherit
parent A's description without an LLM request. Source candidate artifacts
remain immutable. See [framework slots](architecture/framework_slots.md).
Successful description/genome transitions are retained even if the proposed
framework bundle itself is unchanged. Mock initialization retains sampled
genomes and the authored descriptions without external calls.

`framework.evolution_mode: option_reflection` is the frozen-bundle counterpart
to that periodic population transition. It requires self-play, uses the same
authored generation-zero descriptions and G6/G11/G16/... refresh barriers, and
keeps ordinary offspring crossover/mutation local. At each boundary the model
may revise every supporting `strategy_description` and must return one complete
legal `control_genome` for every source survivor under the original exact-byte
bundle hash. The Java template, framework/report architecture, slot IDs,
numeric lattices, expression choices, and bundle hash cannot change. The
two-stage transition is compilation-gated and bounded to four attempts; failure
retains the previous descriptions/genomes. Successful replicas are reevaluated
against the refreshed opponent context before reproduction. No framework
version is created, and resume rejects any population that is not pinned to the
root bundle.

`GROQ_API_KEY`, the Mistral key, and the GPT key are accepted only from their provider-specific
credential sources and are never written to prompt, request, config, bootstrap,
run, candidate, or failure artifacts. Raw provider output and structured report
are untrusted evidence;
schema validation, Java-envelope checks, ordinary validation, javac, and
Integration remain mandatory trust boundaries.

In `llm_coach`, each initial-selection and Coach response must be exactly an
`eagle-framework-selection-v1` object with `schema_version`, the run-frozen
`framework_bundle_sha256`, and a complete `control_genome`. Every slot key must
match the bundle exactly and every value must belong to its finite domain;
expression slots contain declared `choice_id` values only. Raw responses are
persisted before parsing, attempts are bounded and timed, and invalid/exhausted
initial selection fails initialization. Invalid/exhausted mutation retains the complete pre-Coach child genome on a
failed child and does not choose a random fallback.
