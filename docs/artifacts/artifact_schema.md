# Artifact schema

This document owns the current `eagle-run-v2`, `eagle-generation-v3`, and
`eagle-candidate-v6` layout (`phase4-v6`). Timing and lineage fields are defined by
`timing_schema.md` and `lineage_schema.md`.

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
└── final_test/
```

`config.yaml` is the one immutable, fully resolved experiment definition used by runtime and search. It contains defaults, absolute runtime paths where needed, the complete primary `model` section and optional `generation_model` section, LLM behavior, EA settings including `survivor_selection: mu_plus_lambda`, `candidate_java_mode`, and `parent_evaluation_mode`, reflection mode/probabilities, and evaluation matrix. The resolved `evaluation.match_workers` records the bounded match scheduler setting used by normal evaluation, AOS head-to-head, and final-test; the benchmark-derived default is `10` and can be overridden per run. `match_timeout_seconds` and `match_artifact_mode` remain top-level because they describe process limits and evidence retention, not scheduling. Every resolved `evaluation.maps` entry is a `{path, tick_limit}` mapping, even when the source config used a string map path and inherited the top-level fallback. New runs do not write `source_config`, `resolved_config.json`, or `prompt_snapshot.json`.

`manifest.json` stays small: schema/run identity, timestamps, status,
experiment/reflection identity, `model_name`, `generation_model_name`, and
`latest_generation`. Terminal status is `complete`, `interrupted`, or `failed`;
interrupted/failed records include resumability and their interruption/failure
metadata without replacing the last atomic generation. It never embeds the
config. `summary.json` stores completion/reporting fields, final population IDs,
and a reference to the best runnable candidate in the final population; the
reference is `null` when every final candidate failed. It does not copy
candidate snapshots.

`timing.jsonl` is the canonical append-only run timing stream. Archive data lives only below `archives/`.

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

The `eagle-reflection-operator-v5` AOS record contains `mode`, probabilities before/after, nullable
Strategy/Prompt/Code rewards, `reward_source`, operator state, and transitions.
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
drift for audit. `normalized_candidate.java` is the configured canonical
scaffold with only that extracted file's strategy region inserted. Structural
envelope and security checks run before this assembly, so normalization does not
turn a partial or prohibited response into a valid source. Validation, javac,
the promoted phenotype, source hashes used by matches, and compile-repair parent
source references all use `normalized_candidate.java`.

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
`initialization/policy_generation/`. Each attempt persists its exact rendered
request before transport (including the immutable MicroRTS gameplay contract),
raw response before parsing, semantic result, and UTC
timing. Attempt results also retain backend/model/endpoint identity and
request/response hashes. The compact result references
`genotype/policy_prompt.txt` rather than
duplicating the accepted policy text. `candidate.json` identifies the policy as
configured or LLM-generated and references the initialization result. Failed or
interrupted attempts remain evidence even when generation zero is not committed.
Every accepted policy then owns ordinary bounded Java-generation attempts; its
WorkerRush `genotype/inherited_java.java` is prompt context rather than the
phenotype.

Self-play persists a run-local opponent library at
`archives/self_play_opponents.json`. Its versioned entries contain candidate
IDs, birth generations, generated-Java SHA-256 references, and the compact
semantic summary used for LISS-style exact behavior-vector deduplication;
candidate artifacts remain the sole Java-source owner. Each generation-zero or refresh
boundary writes `generations/generation_<nnnn>_self_play_snapshot.json`, which
records the active context ID, refresh interval, selected library sources, a
pointer to the library, and ten `self_play_*` slot mappings. Resume loads the
latest committed snapshot and resolves its immutable candidate references; the
mutable library is consulted only when a later refresh selects the next context.
A refresh also writes
`generation_<nnnn>_self_play_parent_refresh.json`, linking source parents to
fresh replicas, Java hashes, old/new context IDs, and survivor status. Refresh
replicas record generation operation `self_play_fitness_refresh`,
existing-phenotype provenance, and no LLM attempts.

The resolved `evaluation.self_play_opponent_library_capacity` bounds this
archive; FIFO eviction removes only the oldest library references and never a
candidate artifact.

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
fidelity, code simplicity, and game compliance. The revision request contains the
exact parsed conclusion, the explicit interface/unit reference, and the
source-matching validation/compiler diagnostics supplied to the diagnosis; neither
Code Reflection stage receives gameplay-performance evidence. When every dimension
passes, revision status is `not_required` and the parent Java is preserved. A
successful reflected source enters the normal generation attempt ledger as
`code_reflection_output` but causes no additional final Generator LLM request.
Between diagnosis and the generation-wide materialization phase, its schema is
`eagle-code-reflection-v5` with `revision_status: pending`; materialization
updates the same artifact to its terminal status without discarding the original
diagnosis/evidence. `reflection_model` and `revision_model` separately identify
the primary and generation-phase models.

Resume rebuilds a `Candidate` from `candidate.json` plus the two prompt files,
optional inherited Java, phenotype, evaluation, code-quality, and timing files. The loader has isolated
fallback reads for old prompt/phenotype paths, but ignores legacy
`previous_code` and phenotype-parent provenance. New writers never emit them.
`individual.json`, `candidate_result.json`, `evaluation/summary.json`, and
`evaluation/matches.json` are not written.

Generic successful LLM-call records use `eagle-llm-call-v2` metadata with canonical run-relative request/response references. Raw bytes are persisted before parsing; failures without durable references retain inline payloads. Mutation requests and responses live in numbered attempt artifacts; selected request/raw convenience aliases are not emitted. Loader fallbacks remain limited to the documented legacy prompt and phenotype paths.

Raw LLM output is persisted before parsing. Mutation retains reflection/rewrite
request, raw response, UTC-bounded attempts, status, and failure evidence even
when later generation fails. Strategy Coach parsed output preserves the model's
parent-policy echo, while validated `coach_result.json` takes the parent policy
from the authoritative input artifact. Bounded Rewrite attempts retain their request/raw files; compact metadata points
to the representative attempt. A retry request includes the prior deterministic
validation error; raw invalid output is never rewritten in place.
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

Match records use `round_index` for repeated games and do not contain a
`seed` field. Resolved run configuration likewise omits `match_seeds`: the
removed JVM property was never consumed by MicroRTS and therefore could not
support a reproducibility claim.

## Failure and timing rules

Generation, validation, compilation, integration, runtime evaluation, and LLM-backend failures retain their stage evidence and canonical failure classification. A failed stage blocks downstream work without inventing success records. Runtime partial batches retain completed match evidence. All timings use UTC timestamps and non-negative monotonic durations; retries retain per-attempt records.

## Supported schema

Writers, resume, and `eagle.analysis.loader` support only `eagle-run-v2`.
Unknown and historical manifests fail explicitly. The run-local `config.yaml`
is the authoritative model and experiment definition.

## Experiment batch index

When the experiment target is a config directory, the launcher writes
`<config-directory>/experiment.yaml` as a plain mapping from config filenames to
absolute run folders. The file is updated atomically when each run directory is
created and is not a run-root artifact or an experiment config. Config discovery
excludes this generated index. For compatibility, a pre-existing
`experiment-v2` config named `experiment.yaml` is never overwritten.

Folder-level resume reads this mapping without reinitializing it. An indexed
entry is lifecycle-complete when its run manifest is `complete` and, for a
non-mock invocation that does not use `--skip-final-test`, a canonical
`final_test/final_test_summary.json` exists and has the current
`eagle-final-test-v3` schema. The summary records the requested and selected
generation, including whether an older-generation fallback was used, and records contained upstream-opponent
faults separately; a recovered containment is an explicit neutral draw rather
than a candidate win. Incomplete indexed entries are
resumed before unindexed configs; completed entries are skipped. Index paths
written by new batches and accepted by folder resume are absolute.
