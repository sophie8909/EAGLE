# EAGLE architecture specification

Status: authoritative current contract, 2026-09-23.

This document describes executable EAGLE behavior. Historical NSGA-II,
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

Every candidate has two evolving prompt values:

1. `strategy_prompt` — the game-playing policy gene (`policy_prompt` conceptually)
2. `generation_prompt` — the reusable policy-to-Java translation gene (`code_generation_prompt` conceptually)

`candidate_java_mode` selects the Java state boundary. The default
`generated_phenotype` mode keeps Java as non-inherited phenotype/evidence.
The explicit `inherited_genotype` mode adds a third component: the complete
Java source selected from a parent or the configured generation-zero Java
seed. The Generator consumes that inherited source and produces the candidate's
new Java component and phenotype. Evaluation does not overwrite either prompt
gene or the persisted pre-generation Java input.

First-class candidate state includes identity, generation, direct parents,
operator, mutation type, component-source IDs, generated Java, validation and
compile status, active-mode fitness, executable semantic summary, diagnostics, failure state, artifact
references, and timing.

New candidate identities are generation-qualified as
`gen_<zero-padded-generation>_<random-suffix>` so run artifacts remain unique
and easy to navigate. Persisted IDs are opaque references and are never renamed
while loading or resuming a run.

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

Each later generation produces a fixed-size offspring population and performs:

1. a complete generation plan: mode-specific parent selection, optional
   uniform component crossover (two prompt components, plus an independent
   Java-component choice in `inherited_genotype` mode), and optional Strategy,
   Prompt, or Code mutation assignment for every offspring slot before any
   mutation LLM call;
2. all assigned reflection and prompt-rewrite work; Code Reflection records its
   structured diagnosis here but does not yet revise Java;
3. one final materialization phase: complete-file Java generation for Strategy,
   Prompt, and unmutated children, or diagnosis-guided parent-Java revision for
   Code Reflection children;
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

## 4. Reproducibility

`random_seed` is the EA-wide root seed. Execution always seeds controllable
randomness; there is no deterministic/non-deterministic mode switch. Legacy
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
tie-breaking are independent of scheduling. CPU/GPU settings, temperatures,
and worker counts remain configurable. New generation checkpoints preserve
stagnation and bounded EA archive state; independent generation streams allow
same-version resumes to continue the same seeded trajectory. Uncommitted
candidate/decoder/class artifacts and their LLM logs are retained under
`archives/interrupted_work/attempt_<nnnn>` before replaying their stable IDs.
The controller resumes from the manifest's exact completed checkpoint.

Reproducibility requires the same code, inputs, configuration (apart from
worker count), and deterministic task outputs. Request seeds ask an external
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

- `static`: fixed Strategy/Prompt/Code probabilities and no reward work;
- `aos_opponent`: execution-first ten-case rank-change reward against the
  recorded mutation-evidence parent;
- `aos_head2head`: configured mutation-evidence-parent versus offspring match
  matrix reward.

Both adaptive modes use the same alpha-`0.20` EMA and probability-matching
updater with the configured minimum probability floor. AOS never changes the
active fitness contract; adaptive modes apply to fixed-roster lexicase runs.

The adaptive comparison parent is the same evaluated candidate used to build
the mutation context: the policy-component parent for Strategy mutation; the
generation-prompt parent for Prompt and Code mutation in default mode; and the
Java-component parent for Prompt and Code mutation in inherited mode. Component
provenance, rather than direct-parent position or prompt-text equality, selects
this parent. Both reward providers consume the resulting
`comparison_parent_id`.

Strategy mutation performs Match Commentator sampling and Coach reflection. It
changes only `strategy_prompt`, after which the normal final Generator decodes
the child. Initial policy generation, Match Commentator, Coach, the library
Strategy path, and Strategy Alignment receive the immutable closed-world
MicroRTS gameplay contract. The contract permits arbitrary legal strategy types.

Prompt mutation is the former Code Reflection behavior. In default mode it
compares the source parent's policy with its Java phenotype. In inherited mode
it compares the child's independently selected policy with its inherited Java.
The Reviewer receives only the editable Java strategy region, the policy, the
immutable action/API guide, and source-matching validation/compiler diagnostics.
It never receives game performance, opponent scores, W/D/L summaries, match
results, traces, logs, aggregate fitness, or other gameplay evidence. The Prompt
Rewriter then returns one validated reusable-rule delta and changes only
`generation_prompt`; the normal final Generator decodes the child from the
updated prompt gene.

Code mutation first reflects on the selected parent Java, then defers revision
until every child has completed its reflection/rewrite work. The
Reflector receives the child's `strategy_prompt`, the complete selected parent
Java, the immutable gameplay and action/API contracts, the canonical fixed
scaffold, a concise fixed-interface and complete-unit reference, and source-matching
validation/compiler diagnostics. It independently reports strategy fidelity, code
simplicity, and game compliance, with required changes and behaviors to preserve.
The Java revision call receives that exact parsed conclusion plus the same
authoritative inputs only when at least one dimension requires correction. An
all-passing conclusion preserves the parent Java without a revision call. Neither call receives game performance, opponent scores,
W/D/L summaries, match results, traces, logs, aggregate fitness, other gameplay
evidence, or `generation_prompt`. The revision response
must be exactly one complete `CandidateAgent.java`; both prompt genes and the
pre-mutation inherited Java remain unchanged. The returned source enters the
normal validation and compilation stages directly, so a successful Code
Reflection is not overwritten by a third final Generator call. If diagnosis or
extraction fails, the selected parent Java is preserved. Validation or javac
failure may enter the existing bounded diagnostic-only compile-repair chain.

The canonical probability keys are `strategy_reflection_probability`,
`prompt_reflection_probability`, and `code_reflection_probability`; operator
IDs are `strategy_reflection`, `prompt_reflection`, and `code_reflection`.
Reflection-operator state uses `eagle-reflection-operator-v5`; state containing
`balance_reflection`, `generate_code_reflection`, or
`prompt_compliance_reflection` cannot resume under the new semantics.

All executable prompt bodies live as individual UTF-8 text files under
`prompts/`. Python and YAML may reference, render, bound, transport, and validate
prompt resources but may not contain alternate executable prompt bodies.

In `inherited_genotype` mode crossover/copy chooses the Java component before
mutation. Strategy and Prompt preserve it for the final Generator. Code uses it
as the parent source and directly produces the child's candidate Java during
the common final materialization phase while retaining the selected input as
lineage evidence.

## 7. Java generation and validation

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

Except for Code Reflection children, final materialization consumes the two prompt
genes plus the fixed checked-in Java scaffold/API constraints and returns
exactly one complete Java source file. In `inherited_genotype` mode it
additionally receives the selected inherited Java component as revision
context; default mode receives no parent Java. A Code Reflection child instead
enters this boundary with the complete source returned by the operator. It
never receives game logs. Raw response, extracted source, normalized source,
attempts, model identity, errors, and timing are persisted.

The required `model` section owns initialization, reflection, and prompt rewrite.
An optional `generation_model` section may select a different GGUF/runtime
profile for final Java generation, deferred Code Reflection revision, and
compile-guided generation repair. The orchestrator switches the one owned
llama.cpp runtime only at phase boundaries and restores `model` before the next
generation's reflection work. When `generation_model` is omitted, `model` owns
both phases.

The extracted response must itself satisfy the complete-file external envelope:
package/class/superclass, constructors, lifecycle methods, security restrictions,
and exactly one ordered strategy-marker pair. After that check, the decoder
deterministically constructs `normalized_candidate.java` from the configured
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

## 8. Compilation and integration

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

In `self_play`, the run owns a persisted opponent library. The library is
seeded from the current population's compiled candidates that have no failure
state and completed the configured match batch at generation zero and is updated
only at each `evaluation.self_play_refresh_interval` generation (the supported
minimal protocol uses five generations). At an update, newly eligible
candidates are merged into the library after LISS-style exact behavior-vector
deduplication: candidates with the same ordered probe/action vector share one
retained representative. A deterministic stable-order selection from the
library then materializes the immutable ten-slot context. The
library, rather than the current population alone, is therefore the source of
the next opponent snapshot. Between refreshes the active context is unchanged.
Its selected candidates are cycled in stable order into `self_play_000` through
`self_play_009`; a five-candidate context therefore gives each source two slots.
Self-matches are retained and all self-play slots have weight `1.0`. At refresh,
fresh-ID parent replicas preserve the existing Java phenotype without an LLM
call and are evaluated against the new context before reflection and offspring
generation. If semantic deduplication changes the generation-zero context after
its initial evaluation, the same phenotype-preserving migration runs before
the first offspring generation. Only refreshed/migrated parents and offspring
with the same context ID may enter survivor selection. Library, context, and
refresh sidecars make this transition resumable.
`evaluation.self_play_opponent_library_capacity` bounds retained entries; when
the library exceeds that capacity, the oldest entries are removed before active
context selection.
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
`mutation/strategy_reflection/` the exact parent strategy
prompt, ordered selected-match records, each parsed Commentator response, the
structured and rendered Coach input, raw and parsed Coach output, the normalized
child strategy prompt, and the strategy value supplied to Generator. These are
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
discovery, validation of `model` and optional `generation_model`, llama.cpp
start/health checks, per-run restart, phase-boundary model switching, search,
resume, final test, and owned-process cleanup. An occupied foreign endpoint is
never adopted or killed. Mock mode does not construct a runtime manager.

For a directory batch, the selected config directory owns `experiment.yaml`, an
atomically updated mapping from each config filename to its absolute run folder.
The index is updated as soon as a run is created, is excluded from config
discovery, and therefore preserves resumable partial runs. A pre-existing
`experiment.yaml` with `schema_version: experiment-v2` remains a config and is
never overwritten by the index writer.

When `--resume` targets such a config directory, Python reads the existing
index instead of resetting it. Indexed runs that have not completed their
required lifecycle are processed first: interrupted/failed search resumes from
its latest atomic generation, while a search-complete run without a required
final-test summary resumes at final testing. Fully completed indexed configs
are skipped. The remaining unindexed configs then start as fresh runs in
filename order, with every new run added atomically to the same index. A direct
run-directory target retains the single-run resume behavior. If interruption
occurred before generation 0 was atomically recorded, folder resume starts a
replacement run for that config and updates the index because no resumable
population exists.

The exact filename-to-run index is also the identity anchor for folder resume.
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
