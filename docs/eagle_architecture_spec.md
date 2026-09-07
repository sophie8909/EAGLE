# EAGLE architecture specification

Status: authoritative current contract, 2026-09-07.

This document describes executable EAGLE behavior. Historical NSGA-II,
two-objective, seven-opponent, split-runtime, inline-prompt, and `eagle-run-v1`
contracts are intentionally absent; Git history is the archive for those designs.

## 1. System boundary

EAGLE evolves prompt-defined Java MicroRTS agents offline. An LLM may generate or
reflect on candidates before evaluation, but a running match never calls an LLM.
Each phenotype is one complete `ai.generated.CandidateAgent` Java source file.

EAGLE does not evolve patches, runtime LLM policies,
surrogate fitness models, or previous-generation self-play opponents.

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
compile status, ten-case fitness, diagnostics, failure state, artifact
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
zero persists those policy-only calls, but all candidates inherit and directly
evaluate the same configured Java seed without a Java Generator call. The
tracked mixed initialization uses a Worker Rush policy and Worker Rush Java, so
the generated strategies diversify only the policy gene at this boundary; they
are not instances of the MicroRTS `RandomAI` opponent.

Each later generation produces a fixed-size offspring population and performs:

1. seeded lexicase parent selection;
2. optional uniform component crossover (two prompt components, plus an
   independent Java-component choice in `inherited_genotype` mode);
3. optional Strategy, Prompt, or Code mutation;
4. final complete-file Java generation for Strategy, Prompt, and unmutated
   children; a Code Reflection child instead supplies its complete Java here;
5. validation, compilation, integration, and evaluation;
6. optional AOS reward collection;
7. seeded lexicase survivor selection without replacement from the joint
   parent-plus-offspring (`mu_plus_lambda`) pool;
8. atomic generation persistence.

The fixed-size survivor population is selected from the joint evaluated parent
and offspring pool. Parent and offspring candidates compete under the same
ten cases; aggregate Game Performance and generation age do not break ties.

## 4. Reproducibility

`random_seed` controls EA randomness, lexicase case ordering, operator choice,
crossover choices, and deterministic reflection sampling. Match repetitions are
identified by `round_index`; EAGLE does not claim seeded MicroRTS match
reproducibility and does not pass a match-seed JVM property. It also does not
make stochastic LLM sampling deterministic; initial policy generation is
reconstructable from request/response artifacts rather than from `random_seed`
alone. Its role-specific temperature controls sampling diversity.

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
ten-case lexicase fitness.

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

Code mutation first reflects on the selected parent Java, then revises it. The
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
as the parent source and directly produces the child's candidate Java while
retaining the selected input as lineage evidence.

## 7. Java generation and validation

In `generated_phenotype` mode, generation 0 remains the decoder exception: the
configured policy uses `initial_java_seed_path` as a fixed phenotype without a
Generator call. In inherited `configured_seeds` mode,
`initial_java_seed_path` is the third pre-generation component for every
replicated seed candidate; each candidate makes an independent bounded Generator
call and persists normal request, raw response, attempt, validation, and
compilation evidence. In inherited `llm_generated_policies` mode it is both the
shared third component and the unchanged generation-zero phenotype; policy-only
LLM calls fill the remaining population slots, and Java decoding starts with
generation 1.

Except for Code Reflection children, final generation consumes the two prompt
genes plus the fixed checked-in Java scaffold/API constraints and returns
exactly one complete Java source file. In `inherited_genotype` mode it
additionally receives the selected inherited Java component as revision
context; default mode receives no parent Java. A Code Reflection child instead
enters this boundary with the complete source returned by the operator. It
never receives game logs. Raw response, extracted source, normalized source,
attempts, model identity, errors, and timing are persisted.

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
`configured_seeds` generation zero uses the configured bounded attempt budget
independently for every replicated candidate.

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

`evaluation/microrts_runner.py` owns only this integration probe.
`evaluation/runtime_evaluation.py` is the sole match-execution owner.

## 9. Evolution evaluation

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

Fitness is a maximized mapping with exactly the ten opponent IDs. Failed or
incomplete candidates receive `-1000.0` for every case. Aggregate Game
Performance is reporting-only, using weights `0.5` for PassiveAI, RandomAI, and
RandomBiasedAI, `1` for the three rush opponents, and `2` for AllInBot, Mayari,
COAC, and TMA.

Code Quality is a diagnostic and mutation-evidence signal, not a selection
objective. Successful Code Quality is:

`100 - (40C + 25N + 20L + 15F)`

where the terms are normalized cyclomatic complexity, nesting, logical LOC, and
longest-function LOC. Failure Code Quality is `-1000.0`. Compiler diagnostics,
Function Capability, and Strategy Alignment are persisted diagnostics only.
Strategy Alignment is not applicable to an empty policy prompt and is persisted
as skipped with a null score and no LLM attempt.

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
discovery, model validation, llama.cpp start/reuse/switch/health checks, search,
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

`python -m eagle analyze` and `analyze.sh` are the only offline analysis
entrypoints. Separate `run`, `runtime`, `run.sh`, and `run_env.sh` compatibility
surfaces are prohibited.

## 13. Verification

Behavior changes require focused contract tests followed by:

```bash
python3 -m compileall eagle evaluation generation
python3 -m unittest discover -s tests
git diff --check
```

A bounded real Java/MicroRTS integration probe may supplement unit tests. A full
evolutionary experiment is never required for repository validation unless the
operator explicitly requests it.
