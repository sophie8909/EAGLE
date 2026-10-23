# Artifact schema

## DSL and pre-crossover source contract (LLM materialization mode)

New `strategy_prompt` payloads are canonical `eagle-strategy-dsl-v1` JSON;
historical natural-language artifacts are read-only and incompatible resume is
rejected. Each source check owns candidate/check-ID `mutation/code_reflection/`
evidence; source-parent files are never overwritten. Normal children retain
compact `pre_crossover_code_checks` references. Code gate/controller state is v6;
normal AOS rewards cover Strategy and Prompt only.

Each normal child stores `pre_crossover_code_checks` entries with
`source_candidate_id`, `gate_candidate_id`, `healthy`, `reflection_status`,
`revision_required`, and `artifact_path` (`../{gate_id}/mutation/code_reflection`).
Source A uses a deterministic source-check ID; donor B, when needed,
uses a deterministic donor-check ID. Evidence belongs to check candidates, never
the evaluated source-parent directory. A defective/failed check emits its
one-parent diagnosed child, preserving the fixed offspring count.
Healthy audit-only check snapshots use `operator: code_check` (with
`mutation_type: code`); actual corrective offspring use `operator: mutation`.
Semantic analysis excludes `code_check` audits from candidate/unavailable counts,
so population statistics describe actual individuals. Source parents remain unchanged.

Resolved configs carry `evolution_protocol: eagle-dsl-pre-crossover-v1` and
`strategy_policy_format: eagle-strategy-dsl-v1`. Resume requires the protocol
marker before touching run artifacts. Candidate/artifact schema versions remain
current, with an additional `strategy_policy_format` field; operator state uses
`eagle-reflection-operator-v6`. Historical runs remain inspectable, but cannot
resume under the changed algorithm.


This document owns the LLM-mode `eagle-run-v2`, `eagle-generation-v3`, and `eagle-candidate-v6` layout (`phase4-v6`), plus the deterministic-mode artifact version described below. Timing and lineage fields are defined by `timing_schema.md` and `lineage_schema.md`.

## Run root

```text
runs/<run_id>/
├── manifest.json
├── config.yaml
├── summary.json
├── timing.jsonl
├── generations/
├── candidates/
├── generated_agents/
├── classes/
├── archives/
│   ├── strategy.json
│   ├── semantic_signature_cache/
│   └── error_memory.jsonl       # created when failures exist
├── llm_logs/
├── framework/                    # framework_slots only
│   └── bundle.json
└── final_test/
```

`config.yaml` is the one immutable, fully resolved experiment definition used by
runtime and search. It contains defaults, absolute runtime paths where needed, the
primary `model` and optional `generation_model`, LLM behavior, EA settings
including `survivor_selection: mu_plus_lambda`, `candidate_java_mode`,
`java_materialization_mode`, `java_compiler_version`, and `parent_evaluation_mode`,
reflection mode/probabilities, and the evaluation matrix. Deterministic mode
requires `candidate_java_mode: generated_phenotype` and
`parent_evaluation_mode: reuse_cached`. `evaluation.match_workers`, model
`gpu_layers`, `threads`, and `parallel` are rejected config keys. The persisted
`evaluation.match_execution` is `parallel` by default and may be `serial` for
one-worker match execution. The runtime uses GPU layers `999`, eight model
threads, two server slots, two LLM workers, and ten match workers by default;
serial mode uses one. `context_size` remains the per-request limit; the server allocates
twice that amount for two slots. `match_timeout_seconds` and
`match_artifact_mode` remain top-level because they describe process limits and
evidence retention. Every resolved `evaluation.maps` entry is a `{path,
tick_limit}` mapping, even when the source config used a string map path and
inherited the top-level fallback. New runs do not write `source_config`,
`resolved_config.json`, or `prompt_snapshot.json`.

For deterministic reference policies, `generation/compiler_evidence.json` and
the projected generation result include `reference_agent` and
`reference_source_sha256`. Both are null for ordinary rule policies. Readers
accept only `WorkerRush` and verify the hash against the vendored canonical
source before reconstructing a successful candidate.

`manifest.json` stays small: schema/run identity, timestamps, status,
experiment/reflection identity, `model_name`, `generation_model_name`, and
`latest_generation`. Terminal status is `complete`, `interrupted`, or `failed`;
interrupted/failed records include resumability and their interruption/failure
metadata without replacing the last atomic generation. It never embeds the
config. `summary.json` stores completion/reporting fields, final population IDs,
and a reference to the best runnable candidate in the final population; the
reference is
null` when every final candidate failed. It does not copy
candidate snapshots.

`timing.jsonl` is the canonical append-only run timing stream. Archive data lives only below `archives/`.

For `framework_slots`, an explicit `framework.bundle_path` is validated during
config resolution and its bundle version and exact-byte SHA-256 are recorded.
Without that path, fresh startup requires `framework.design_brief` and uses
optional `framework.model` (default `openai/gpt-oss-120b`) to create the bundle.
Both paths publish the validated exact bytes as run-owned
`framework/bundle.json` before search and point the runtime config at that file.
The manifest records `framework_bundle_version`, `framework_bundle_sha256`, and
`framework_bundle_artifact: framework/bundle.json`. The frozen file is immutable.
Resume validates its exact bytes, compares design brief, bootstrap backend/model, and
evolution mode, and never regenerates a framework. Failed bootstrap preserves
attempts and a failed manifest; pending config cannot resume without a usable
frozen bundle. Failed replicate startup does not bind a folder-batch index slot.
The resolved `framework.evolution_mode` defaults to `local` and must match on
resume; it does not alter the bundle or materializer version.
In `llm_coach` mode, `framework.coach_offspring_probability` is resume-fenced
and recorded as manifest field
`framework_coach_offspring_probability`. A missing field in an older manifest
means `null`, preserving legacy Coach behavior. `null` is the default; numeric
values are in the inclusive range `0.0`–`1.0`. A numeric value requires
`framework.evolution_mode: llm_coach`; config validation rejects it in `local`
mode.
## Generation snapshot

`generations/generation_<nnnn>.json` contains:

- generation number;
- population entries with candidate ID, status, active-mode fitness, and compact semantic signature;
- best/reporting candidate ID;
- aggregate objective, opponent, diversity, and timing-derived metrics;
- one canonical reflection-operator/AOS generation record.

Generation metric match counts are population totals: `expected_match_count`
and `completed_match_count` sum the corresponding values from every candidate,
including candidates blocked before matches.

Each generation also has a lightweight flat sidecar at
`generations/generation_<nnnn>_policies.jsonl`. It contains one
`eagle-generation-policy-v2` record, in population order, for every population
candidate with a non-empty `strategy_prompt`. Records contain the generation,
candidate ID, strategy-parent ID, operator, mutation type, and a run-relative
reference to the candidate's canonical `genotype/policy_prompt.txt`. When
known, they also reference the parent strategy prompt and the candidate's
Strategy Reflection metadata. Full strategy text is not duplicated in this
index.

Only the non-canonical `parent_evaluation_mode: regenerate_same_genotype`
treatment additionally writes
`generations/generation_<nnnn>_parent_rematerialization.json`. Each record maps
an immutable source parent to its fresh evaluation replica and includes the
three genotype component hashes, source/new Java hashes, replica fitness and
status, corresponding source fitness/status, direct genotype/Java-change flags,
and survivor flag. The old parent candidate directory remains immutable.

The `eagle-reflection-operator-v6` AOS record contains `mode`, probabilities before/after, nullable
Strategy/Prompt rewards, `reward_source`, operator state, and transitions.
Static mode records `reward_source: static`, null rewards, and unchanged
probabilities. Resume restores adaptive state from the latest generation file.
There is no `generation_metrics.jsonl` or `final_population.json` in new runs.

Derived `eagle-analysis-v2` agent, opponent-win-rate, and single-match rows are
expanded from these selected-population snapshots. Their `generation` column is
the survivor snapshot generation used on plot axes, while `birth_generation`
retains the candidate's creation generation. A retained parent is consequently
represented in every generation where it remains selected, without copying its
canonical candidate state.

## Candidate snapshot and evidence

```text
candidates/<candidate_id>/
├── candidate.json
├── lineage.json
├── timing.json
├── genotype/
│   ├── policy_prompt.txt
│   ├── strategy_signature.json
│   ├── code_generation_prompt.txt
│   └── inherited_java.java             # inherited_genotype mode only
├── initialization/
│   └── policy_generation/               # LLM-generated seed policies only
│       ├── result.json
│       └── attempts/attempt_<nnn>/
│           ├── request.txt
│           ├── response_raw.txt
│           ├── result.json
│           └── timing.json
├── phenotype/                         # compilation success only
│   └── CandidateAgent.java
├── crossover/provenance.json
├── mutation/
│   ├── strategy_reflection/
│   ├── prompt_reflection/
│   ├── code_reflection/
├── aos/
├── generation/
│   ├── attempts/
│   │   └── attempt_NNN/
│   │       ├── request.txt
│   │       ├── response_raw.txt
│   │       ├── extracted_candidate.java
│   │       ├── normalized_candidate.java
│   │       ├── repair_input.json       # compile_repair only
│   │       ├── validation/
│   │       ├── compilation/
│   │       ├── timing.json
│   │       └── result.json
│   ├── repair_ledger.json
│   ├── failed_candidate.java           # source_without_generation only
│   └── result.json                     # selected/final pointers
├── validation/validation_result.json
├── compilation/
├── integration/
├── matches/
└── evaluation/
    ├── game_performance.json
    ├── commentary_aggregation.json
    ├── code_quality.json
    ├── semantic_signature.json
    └── objectives.json
```

In `framework_slots`, the mode-specific candidate subset replaces prompt files
with `genotype/control_genome.json` and adds
`generation/framework_evidence.json` plus, when rendering produced source,
`generation/rendered_candidate.java`. Candidate/lineage schema versions are
`eagle-candidate-v8` and `4.0`. The candidate index pins
`framework_bundle_sha256`, references `../../framework/bundle.json`, and records
all `slot_parent_ids`; it does not serialize policy/prompt/Java-parent fields.
For explicit numeric `framework.coach_offspring_probability`, the candidate
index also records `metadata.framework_reproduction_route` as `coach` or
`traditional` for later offspring.
Framework evidence schema `eagle-framework-materialization-v1` records operation
`framework_slot_assembly`, materializer version, framework ID, exact-byte and
canonical bundle hashes, template/genome/source hashes, complete control genome,
and slot provenance. Successful compilation still promotes the only canonical
phenotype to `phenotype/CandidateAgent.java`.

Under `framework.evolution_mode: llm_coach`, initial selection artifacts live
under the candidate's `initialization/framework_coach/` directory; the stage
retains `input.json`, numbered `coach_request_attempt_NNN.json` and
`coach_response_attempt_NNN.json` files, `coach_call.json`, and either
`selection.json` or `failure.json`. Strategy
mutation retains its Commentator and Coach attempts under the candidate's
`mutation/strategy_reflection/` owner. The exact response schema is
`eagle-framework-selection-v1`; raw bytes precede parsing, and each attempt
records validation outcome and timing. A failed initial selection has
`failure_stage: initialization`; a failed Coach child retains its pre-Coach
complete `control_genome`, records `failure_stage: reflection`, and is not
silently replaced by random values. Local mode has no such LLM artifacts.

`candidate.json` is the only candidate-level index. It stores identity, generation, parents/component provenance, operator, status/failure, active-mode fitness, aggregate Game Performance, compact executable semantic summary, strategy metadata, compact mutation/AOS metadata, timing summary, and relative artifact references. Full canonical probe actions remain in the run-local cache rather than the index. Large data remains in its stage owner: Java source, LLM text, compiler output, match records, and telemetry are never embedded in the index.

For every bounded Java LLM decode, including both inherited initialization modes in
generation zero, every
attempt owns its actual post-truncation
request and hash, raw response, extracted/normalized source, validation,
compilation, and timing. `request_kind` distinguishes `initial_decode`,
`code_reflection_output`, `initial_decode_retry`, and `compile_repair`. Repair records also identify
`repair_of_attempt`, the previous source SHA-256, and a `repair_input.json`
containing only that previous attempt's structured diagnostics. The compact
`repair_ledger.json` links the chain without duplicating source or diagnostics.
Attempt payloads are written once; only the final outcome is updated. The
`generation/result.json` pointers identify selected and final attempts.
`phenotype/CandidateAgent.java` exists only after compilation success;
the candidate index's `failed_generation_source` references the representative
attempt's normalized source. A
`source_without_generation` failure points to `generation/failed_candidate.java`. `generation/result.json` records
`max_attempts`, nullable `selected_attempt`, `final_attempt`, canonical attempt
reference (null on exhaustion), representative selected/final-failure attempt
reference, and the projected request SHA-256. Attempt class workspaces are transient and
candidate-isolated; only promoted canonical classes remain for Integration and
matches. A partial persisted attempt is audit-only and a rerun refuses to
overwrite it; resume starts from the last atomic generation boundary rather than
continuing a half-decoded candidate. Zero-LLM source paths (`initial_java_seed` and self-play refresh) have no
attempts or `generation/attempts/` directory.

`extracted_candidate.java` is the normalized text extracted from the model's
complete-file response and therefore preserves model-authored fixed-region
drift for audit.
normalized_candidate.java` is the configured canonical
scaffold with only that extracted file's strategy region inserted. Structural
envelope and security checks run before this assembly, so normalization does not
turn a partial or prohibited response into a valid source. Validation, javac,
the promoted phenotype, source hashes used by matches, and compile-repair parent
source references all use
normalized_candidate.java`.

For default-mode generation-zero candidates, `genotype/policy_prompt.txt`
retains the configured seed policy and `generation/result.json` records
operation `initial_java_seed`, no attempts, and checked-in source provenance.
No Java LLM request/raw-response files are created. In inherited `configured_seeds` mode,
`genotype/inherited_java.java` retains the exact pre-generation no-op Java input
for each replicated seed candidate; each candidate then owns ordinary bounded
generation attempts and a separately generated phenotype. Later children use
the same file for the selected parent Java component, with `java_parent_id` in
candidate/lineage/crossover provenance. Full inherited Java is never embedded
in candidate or generation JSON.

For `llm_generated_policies`, the first candidate's policy comes from the
configured seed file and the remaining candidates own
`initialization/policy_generation/`. First-wave policy requests use the same
configured-seed snapshot with distinct task seeds. Policy transport is stateless;
only Java-generation request context is thread-local. Results and duplicate
retries are resolved in candidate order. Each attempt persists its exact rendered
request before transport (including the immutable MicroRTS gameplay contract),
raw response before parsing, semantic result, and UTC timing. Attempt results also
retain backend/model/endpoint identity and request/response hashes. The compact
result references `genotype/policy_prompt.txt` rather than duplicating the
accepted policy text. `candidate.json` identifies the policy as configured or
LLM-generated and references the initialization result. Failed or interrupted
attempts remain evidence even when generation zero is not committed. For a valid
first-wave response rejected as a population duplicate, the attempt `result.json`
may include `population_decision` with
`{status: rejected_duplicate, reason, duplicate_of_candidate_id}`. The attempt
keeps `status: success` and `selected: false`; its timing record and run-level LLM
request event also remain successful. The initialization result records the
ordered retry outcome and may fail after `initial_policy_max_attempts` is
exhausted, even when each response was valid but duplicated. Every accepted
policy then owns ordinary bounded Java-generation attempts; its
WorkerRush `genotype/inherited_java.java` is prompt context rather than the
phenotype.

Self-play persists its maintained pool at `archives/self_play_opponents.json`
with schema `eagle-opponent-pool-v1`. The archive records configured capacity,
protected opponent IDs, member references, and phenotype hashes; candidate
artifacts remain the Java-source owner. Pool tournaments are archived at
`archives/opponent_pool_tournaments/generation_NNNN/<entrant_id>/result.json`
with each match result. Pool state is checkpointed in the existing
`resume_archives` and restored before replay.

Each immutable context is written to
`generations/generation_<nnnn>_self_play_snapshot.json` using
`eagle-self-play-snapshot-v4`, member references, and a context hash. Generation
zero evaluates all ten built-in sources under the fixed slots: the protected
four use their actual case IDs, and the other six map to
`self_play_000`…`self_play_005`. Refresh contexts keep the protected case IDs
and use those six diagnostic slots for sampled pool members. Context rows record
`source_opponent_id`; built-ins have null `source_candidate_id` and
`source_generation`. Parent refresh sidecars continue to link source parents
to fresh replicas, Java hashes, old/new context hashes, and survivor status;
replicas reuse the phenotype and make no LLM attempts. Resume restores the pool
checkpoint before replay and validates the exact policy marker. Old
self-play resolved configs without `evaluation.self_play_pool_policy:
tournament-v1` are inspection-only and cannot resume under this contract.
Historical cohort artifacts and readers may remain for inspection but do not
drive active scheduling. See the [architecture spec](../eagle_architecture_spec.md#9-evolution-evaluation)
for admission, tournament, capacity, and context rules.

The v4 snapshot's `runtime_identity` hashes the actual configured MicroRTS
`src`/`bin`/`lib`, builtin opponent JARs, opponent adapters/support libraries,
and configured map file bytes. Snapshot loading verifies these hashes before
reusing cached fitness; changed runtime or map assets require a new run.
`evaluation/game_performance.json` persists `evaluation_configuration`,
`evaluation_context_id`, and `fitness_case_ids` alongside scores. Tournament
results retain a hash for the candidate defender's prepared/renamed runtime
class tree and, when available, builtin source and resolved-class hashes.

Normal evaluation does not call Function Capability or Strategy Alignment and
does not write their diagnostic files or timing. The standalone helper modules
remain available to explicitly invoked tooling.

Prompt Reflection evidence is stored under `mutation/prompt_reflection/`. It
retains the exact alignment-review request/raw response, the separately bounded
prompt-rewrite requests/raw responses, structured reusable-rule delta, attempts,
and errors. The Reviewer sees the policy and selected parent's editable Java
strategy region plus source-matching validation/compiler diagnostics, but no game
performance, opponent scores, W/D/L, match, trace, log, or aggregate-fitness
evidence. The Rewriter deterministically changes only
`genotype/code_generation_prompt.txt`.

Code Reflection evidence is stored under `mutation/code_reflection/`. It
retains `reflection_conclusion.json`, numbered request/raw attempt files, and
`representative_attempt_artifacts` pointers for Reflector and Revision calls, `parent_candidate.java`, `reflected_candidate.java`, hashes, attempt
timing, and terminal status. The parsed conclusion independently records strategy
fidelity and code correctness. The revision request contains the
exact parsed conclusion, the explicit interface/unit reference, and the
source-matching validation/compiler diagnostics supplied to the diagnosis; neither
Code Reflection stage receives gameplay-performance evidence. When every dimension
passes, revision status is
ot_required` and the parent Java is preserved. A
successful reflected source enters the normal generation attempt ledger as
`code_reflection_output` but causes no additional final Generator LLM request.
Between diagnosis and the child's own materialization step, its schema is
`eagle-code-reflection-v6` with `revision_status: pending`; materialization
updates the same artifact to its terminal status without discarding the original
diagnosis/evidence. `reflection_model` and `revision_model` separately identify
the permanently bound reflection and generation models.

Resume rebuilds a `Candidate` from `candidate.json` plus mode-specific active genotype files, optional inactive compatibility data, phenotype, evaluation, code-quality, and timing files. The loader has isolated
fallback reads for old prompt/phenotype paths, but ignores legacy
`previous_code` and phenotype-parent provenance. New writers never emit them.
`individual.json`, `candidate_result.json`, `evaluation/summary.json`, and
`evaluation/matches.json` are not written.

Generic successful LLM-call records use `eagle-llm-call-v2` metadata with canonical run-relative request/response references. The task-specific seed derived from the replicate root `random_seed` is recorded as `sampling_seed` and sent as the OpenAI-compatible request `seed`. Raw bytes are persisted before parsing; failures without durable references retain inline payloads. Mutation requests and responses live in numbered attempt artifacts; selected request/raw convenience aliases are not emitted. Loader fallbacks remain limited to the documented legacy prompt and phenotype paths.

The standalone seed-restart diagnostic writes a versioned stability matrix
outside the canonical run tree: each `seed_<n>/stability_report.json` owns its
raw responses and hashes, while `stability_matrix.json` records cross-seed
comparison and the server restart lifecycle.

Strategy Reflection selection metadata uses `strategy-reflection-match-selection-v3`.
It records `selection_rule` and `sampling_priority`, both set to
`lowest_performance_then_match_id`, `requested_sample_size: 1`, and
`actual_sample_size` of zero or one. The selected parent is resolved by lineage `strategy_parent_id`.
Legacy `sample_count` configuration remains readable but does not change the
requested count; retained `random_provenance` is audit metadata and does not
break equal-score ties. Missing/non-finite performance uses outcome score loss
`-100`, draw `0`, win `100`; failed matches are excluded.

Raw LLM output is persisted before parsing. Mutation retains reflection/rewrite
request, raw response, UTC-bounded attempts, status, and failure evidence even
when later generation fails. Strategy Coach parsed output preserves the model's
parent-policy echo, while validated `coach_result.json` takes the parent policy
from the authoritative input artifact. Bounded Rewrite attempts retain their request/raw files; compact metadata points
to the representative attempt. A retry request includes the prior deterministic
validation error; raw invalid output is never rewritten in place.
Coach and strategy-contract-rewriter responses use rule-per-line JSONL. Each
complete matching rule record is validated independently; accepted rules retain
physical-line order, while non-JSON lines and whole invalid rule records are
discarded. Partial extraction succeeds when at least one legal rule remains;
zero accepted rules follows the bounded retry/failure path. The exact
unfiltered response remains in the numbered attempt artifact. Successful roles
also write `coach_strategy_extraction.json` or
`strategy_contract_rewriter_extraction.json` with schema
`eagle-strategy-rule-extraction-v1`, accepted line numbers, discarded line
reasons, counts, mode, and raw/extracted/canonical hashes. Parsed output stores
the assembled policy as a serialized DSL string for compatibility, and the
candidate stores its canonical form. Legacy whole-policy responses remain
all-or-nothing.
Mutation-role run timing references the candidate-owned evidence without
duplicating its prompt/response under `llm_logs/`. Adaptively credited offspring
retain `aos/reward.json`; its
`comparison_parent_id` resolves the evaluated mutation-evidence parent through
component provenance. Head-to-head match evidence remains below
`aos/head_to_head/`.

In default mode Prompt Reflection metadata records `reviewed_phenotype_artifact`
as a run-relative reference to the evaluated source candidate's canonical Java
phenotype. In inherited mode it instead records `java_parent_id`,
`reviewed_java_input: inherited_java`, and the child's canonical
`reviewed_inherited_java_artifact`; that source is also the explicit Java input
to the Generator. The persisted Prompt Reviewer request contains only that source's
editable strategy region plus the immutable API guide, never fixed scaffold
source. The Prompt Rewriter raw response is a `remove_rule_ids`/`add_rules` delta;
its `rewritten_prompt` field is the deterministic canonical rule rendering that
becomes `genotype/code_generation_prompt.txt`. Neither path restores an
implicit `previous_code` field.

Standalone reflection inspections live below `runs/reflection_inspections/`
and are not `eagle-run-v2` search runs. They run Strategy, Prompt, and Code
independently from one fixed subject and retain matching input/output hashes,
requests, responses, mutation artifacts, and field-level diffs.

## Match ownership

Each normal or head-to-head match has one canonical `result.json`. Distinct specialized evidence remains separate:

```text
matches/<match_id>/
├── result.json
├── raw_result.json
├── match_metadata.json
├── match_trace.jsonl.gz
├── match_trace_integrity.json
├── telemetry.json.gz
├── performance_breakdown.json
├── stdout.txt                         # present only when nonempty
└── stderr.txt                         # present only when nonempty
```

Every normal-evaluation `result.json` and `match_metadata.json` records a
non-null canonical `opponent_id`. The 180 match directories must reconstruct
exactly the ten configured case IDs with 18 matches per opponent, without
mapping Java class names back to fitness cases. Each `result.json` `max_cycles`
and `match_metadata.json` `evaluation_configuration.tick_limit` must equal the
resolved cap of the associated map. Final-test summary map entries likewise
retain `tick_limit` beside map ID and path.

Compact mode does not request the transient Java XML replay and removes round-state inputs after durable telemetry/trace creation. Full mode retains both replay and round-state inputs. `result.json` owns match timing; there is no `timing.json`. Empty stdout/stderr files are absent and have null references. `raw_result.json` is the unnormalized Java-runner payload and therefore is not a duplicate. New writers do not emit `match_result.json`.

Mock matches use the same writer and path contract. They synthesize only the initial and final round snapshots before the normal compact/full persistence step; this bounds smoke-test I/O without inventing a second mock artifact schema.

Match records use `round_index` for repeated games. `result.json` and trace
metadata always record the stable positive `match_seed` passed to MicroRTS as
`-Deagle.match.seed`; the seed derives from the EA root seed and match identity.
Resolved configuration omits the obsolete `match_seeds` list and
`deterministic_mode` switch. Generation snapshots include `stagnation_count`
and `resume_archives` (exact text or null for the strategy, error-memory, and
self-play-opponent archives) so resumes preserve stopping and selection context.
Uncommitted generation artifacts and associated LLM logs move to
`archives/interrupted_work/attempt_<nnnn>` before replay; archived log references
point to that preserved evidence. Unfinished opponent-pool tournament generation
directories are also preserved under the interrupted attempt before replay; the
authoritative pool rollback continues to use the existing checkpoint mechanism.
Timing events retain the chronological history.

## Failure and timing rules

Generation, validation, compilation, integration, runtime evaluation, and LLM-backend failures retain their stage evidence and canonical failure classification. A failed stage blocks downstream work without inventing success records. Runtime partial batches retain completed match evidence. All timings use UTC timestamps and non-negative monotonic durations; retries retain per-attempt records.

## Supported schema

Writers, resume, and `eagle.analysis.loader` support only `eagle-run-v2`.
Unknown and historical manifests fail explicitly. The run-local `config.yaml`
is the authoritative model and experiment definition.

## Experiment batch index

When the experiment target is a config directory, the launcher writes
`<config-directory>/experiment.yaml` with
`schema_version: eagle-experiment-index-v1`
and a `runs` mapping from each exact config filename to an ordered list of
absolute run-directory strings. List position is the zero-based replicate
index:

```yaml
schema_version: eagle-experiment-index-v1
runs:
  config.yaml:
    - /absolute/path/run-1
    - /absolute/path/run-2
```
The index is updated atomically as each run is created and is neither a run-root
artifact nor an experiment config. Config discovery excludes it. A pre-existing
`experiment-v2` config named `experiment.yaml` remains a config and is never
overwritten, so that directory cannot also hold the generated index.

For compatibility, legacy plain mappings from filenames to absolute paths are
read as one-item lists and upgraded atomically the next time a run is recorded.
A run directory's canonical `config.yaml` is written before its path is recorded
in the index. Folder resume validates each run's effective seed against its
scheduled slot. It recovers indexed incomplete runs before creating missing
replicate slots. A fresh launch starts a fresh index. If a slot has no
generation-zero evidence, its run path is replaced while prior evidence remains
on disk.
An indexed slot is lifecycle-complete when its run manifest is `complete` and,
for a non-mock invocation that does not use `--skip-final-test`, a canonical
`final_test/final_test_summary.json` exists and has the current
`eagle-final-test-v3` schema. The summary records the requested and selected
generation, including whether an older-generation fallback was used, and
records contained upstream-opponent
faults separately; a recovered containment is an explicit neutral draw rather
than a candidate win. Incomplete indexed entries are
resumed before unindexed configs; completed entries are skipped. Index paths
written by new batches and accepted by folder resume are absolute.

Fixed cross-generation evaluation writes derived analysis to `fixed_evaluation/` (or explicit `--output-dir`). Its frozen `protocol.json` records the root seed and seed scheme, roster, map hashes and tick caps, scoring, and runtime opponent source identities. Each `generation_<nnnn>/` has `compilation.json`, Integration and match evidence, and normal final-test JSON/CSV/Markdown outputs; the shared final-test evaluator also retains `compilation.json` for ordinary final tests. Combined files are `fixed_evaluation_summary.json`, `fixed_evaluation_results.csv`, and `fixed_evaluation_results.md`. Partial progress and failed-match evidence are retained. Asset/source drift leaves `fixed_evaluation_valid: false` in the affected generation's raw summary and excludes that matrix from comparison rows. An explicit output directory must be new or empty; reruns require another directory to preserve prior evidence. These outputs do not alter `final_test/` or search artifacts.


## Deterministic Java materialization artifacts

Deterministic candidates retain canonical `phenotype/CandidateAgent.java` as the
phenotype. The generation directory additionally owns
`generation/compiler_evidence.json` (`eagle-dsl-materialization-v1`),

`generation/normalized_policy.json`, `generation/compiled_candidate.java`, and `generation/scaffold.java`. Evidence records
`operation: deterministic_dsl_compile`, `materialization_mode`, compiler
version, normalized policy, policy/scaffold/source hashes, diagnostics, empty
`llm_attempts`, and compiler timing. `generation/result.json` carries the same
mode/version/hash identity. Deterministic candidates use
`candidate_schema_version: eagle-candidate-v7`; its `generation/result.json`
uses `artifact_schema_version: phase4-v7`. Shared validation, compilation,
integration, and evaluation stage schemas retain their existing versions.
LLM mode retains `eagle-candidate-v6` and `phase4-v6`.

Candidate snapshots identify `active_genotype_components`; this is exactly
`["strategy_prompt"]` in deterministic mode. Stored `generation_prompt` or
inherited Java is inactive compatibility data and does not determine source.
Resume rejects mode/protocol mismatch and unsupported compiler versions before
replay; an absent field in an old config means `llm`.

## Framework bootstrap

Inline bootstrap stores these artifacts under `<run_dir>/framework/`; the standalone command uses its selected output directory. They are run preparation evidence and do not live inside a candidate:

```text
<bootstrap-output>/
├── prompt.txt
├── bundle.json
├── CandidateAgent.template.java
├── slot_generation_prompt.txt
├── report.json
├── bootstrap.json
└── attempts/attempt_NNN/
    ├── request.json
    ├── response_raw.json
    └── result.json
```

`bootstrap.json` records the selected `groq` or `local` backend. `response_raw.json` is flushed before provider-envelope or generated-content
parsing, including failed responses. Attempt schema
`eagle-groq-framework-attempt-v1` records status/retryability, redacted error,
provider/model/endpoint/HTTP status, UTC boundaries, duration, and exact request
and response hashes, including the provider `finish_reason`. `length` is
accepted only for the local backend after the complete response passes local
bundle validation; Groq still requires `stop`. `eagle-groq-framework-bootstrap-v1` records the selected
attempt, total duration, attempt summaries, and the SHA-256 of the exact
published `bundle.json` bytes.

The OpenAI-compatible request uses user content in `messages` and
`response_format` JSON Schema named `eagle_framework` with `strict: false`. The normalized bundle, extracted template,
slot-generation prompt, and report are separate convenience views;
`bundle.json` is the sole experiment input.
Local bootstrap requests additionally set
`chat_template_kwargs.enable_thinking: false` so the framework JSON is emitted
in `message.content` instead of consuming the output budget in
`reasoning_content`.
Each `request.json` records the actual response mode for that attempt. A
provider `json_validate_failed` response is retained as a failed attempt before
the bounded retry switches to JSON Object Mode; the same local bundle parser
and validator remain authoritative for the fallback response.

The API key is never an artifact. Groq reads only `GROQ_API_KEY`; Mistral reads
only `api_key/mistral`. The selected key is sent in the HTTP Bearer
authorization header, excluded from request JSON/config, and redacted from
stored errors. A bootstrap target must be new or empty so previous evidence is
never overwritten. See [framework slots](../architecture/framework_slots.md) for
the exact structured schema and retry boundary.
