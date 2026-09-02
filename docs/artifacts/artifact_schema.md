# Artifact schema

This document owns the current `eagle-run-v2`, `eagle-generation-v3`, and
`eagle-candidate-v5` layout. Timing and lineage fields are defined by
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
│   ├── opponents.json
│   └── error_memory.jsonl       # created when failures exist
├── llm_logs/
└── final_test/
```

`config.yaml` is the one immutable, fully resolved experiment definition used by runtime and search. It contains defaults, absolute runtime paths where needed, the complete model section, LLM behavior, EA settings including `survivor_selection: mu_plus_lambda` and `candidate_java_mode`, reflection mode/probabilities, and evaluation matrix. Every resolved `evaluation.maps` entry is a `{path, tick_limit}` mapping, even when the source config used a string map path and inherited the top-level fallback. New runs do not write `source_config`, `resolved_config.json`, or `prompt_snapshot.json`.

`manifest.json` stays small: schema/run identity, timestamps, status, experiment/model/reflection identity, and `latest_generation`. Terminal status is `complete`, `interrupted`, or `failed`; interrupted/failed records include resumability and their interruption/failure metadata without replacing the last atomic generation. It never embeds the config. `summary.json` stores completion/reporting fields, final population IDs, and a reference to the best runnable candidate in the final population; the reference is `null` when every final candidate failed. It does not copy candidate snapshots.

`timing.jsonl` is the canonical append-only run timing stream. Archive data lives only below `archives/`.

## Generation snapshot

`generations/generation_<nnnn>.json` contains:

- generation number;
- population entries with candidate ID, status, and ten-case fitness vector;
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

The AOS record contains `mode`, probabilities before/after, nullable
Strategy/Code/Balance rewards, `reward_source`, operator state, and transitions.
Static mode records `reward_source: static`, null rewards, and unchanged
probabilities. Resume restores adaptive state from the latest generation file.
There is no `generation_metrics.jsonl` or `final_population.json` in new runs.

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
├── phenotype/                         # compilation success only
│   └── CandidateAgent.java
├── crossover/provenance.json
├── mutation/
│   ├── strategy_reflection/
│   ├── code_reflection/
│   └── balance_reflection/
├── aos/
├── generation/
│   ├── request.txt
│   ├── response_raw.txt
│   ├── extracted_candidate.java
│   ├── normalized_candidate.java
│   ├── repair_ledger.json
│   ├── attempts/
│   │   └── attempt_<nnn>/
│   │       ├── request.txt
│   │       ├── response_raw.txt
│   │       ├── extracted_candidate.java
│   │       ├── normalized_candidate.java
│   │       ├── repair_input.json       # compile_repair attempts only
│   │       ├── validation/
│   │       ├── compilation/
│   │       ├── timing.json
│   │       └── result.json
│   └── result.json
├── validation/validation_result.json
├── compilation/
├── integration/
├── matches/
├── strategy_alignment/
└── evaluation/
    ├── game_performance.json
    ├── commentary_aggregation.json
    ├── function_capability.json
    ├── code_quality.json
    └── objectives.json
```

`candidate.json` is the only candidate-level index. It stores identity, generation, parents/component provenance, operator, status/failure, fitness vector, aggregate Game Performance, strategy metadata, compact mutation/AOS metadata, timing summary, and relative artifact references. Large data remains in its stage owner: Java source, LLM text, compiler output, match records, and telemetry are never embedded in the index.

For every bounded LLM decode, including inherited-mode generation zero, every
attempt owns its actual post-truncation
request and hash, raw response, extracted/normalized source, validation,
compilation, and timing. `request_kind` distinguishes `initial_decode`,
`initial_decode_retry`, and `compile_repair`. Repair records also identify
`repair_of_attempt`, the previous source SHA-256, and a `repair_input.json`
containing only that previous attempt's structured diagnostics. The compact
`repair_ledger.json` links the chain without duplicating source or diagnostics.
Attempt directories are append-distinct and failed evidence is never replaced
by a later attempt. The flat `generation/`, `validation/`, and `compilation/`
files project the selected success or final representative failure. A
`phenotype/CandidateAgent.java` exists only after compilation success; an
exhausted final source remains `generation/normalized_candidate.java` and is
indexed as `failed_generation_source`. `generation/result.json` records
`max_attempts`, nullable `selected_attempt`, `final_attempt`, canonical attempt
reference (null on exhaustion), representative selected/final-failure attempt
reference, and the projected request SHA-256. Attempt class workspaces are transient and
candidate-isolated; only promoted canonical classes remain for Integration and
matches. A partial persisted attempt is audit-only and a rerun refuses to
overwrite it; resume starts from the last atomic generation boundary rather than
continuing a half-decoded candidate. Default fixed-seed generation zero has no
`generation/attempts/` LLM evidence.

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
Request/raw-response files are empty. In `inherited_genotype` mode,
`genotype/inherited_java.java` retains the exact pre-generation no-op Java input
for each replicated seed candidate; each candidate then owns ordinary bounded
generation attempts and a separately generated phenotype. Later children use
the same file for the selected parent Java component, with `java_parent_id` in
candidate/lineage/crossover provenance. Full inherited Java is never embedded
in candidate or generation JSON.

When the policy prompt is empty, `strategy_alignment/result.json` records
`status: not_applicable`, a null score, and no attempts; its request/raw files
are empty. This is distinct from an Alignment blocked by an earlier evaluation
failure.

Balance Reflection evidence is stored under `mutation/balance_reflection/`.
Its `reflection_context.json` is only the bounded opponent/map/side W/D/L
table; the directory retains the reflection request/raw response and separately
named strategy/code rewrite request/raw-response artifacts. Metadata records
both rewrite statuses without embedding raw response bodies. The code rewrite
raw response is a `remove_rule_ids`/`add_rules` delta, while its
`rewritten_prompt` metadata field is the deterministically rendered canonical
generation prompt. A failed reflector or either failed rewrite retains completed
evidence and leaves both prompt genes unchanged.

Resume rebuilds a `Candidate` from `candidate.json` plus the two prompt files,
optional inherited Java, phenotype, evaluation, code-quality, and timing files. The loader has isolated
fallback reads for old prompt/phenotype paths, but ignores legacy
`previous_code` and phenotype-parent provenance. New writers never emit them.
`individual.json`, `candidate_result.json`, `evaluation/summary.json`, and
`evaluation/matches.json` are not written.

Raw LLM output is persisted before parsing. Mutation retains reflection/rewrite
request, raw response, UTC-bounded attempts, status, and failure evidence even
when later generation fails. Strategy Coach parsed output preserves the model's
parent-policy echo, while validated `coach_result.json` takes the parent policy
from the authoritative input artifact. Mutation-role run timing references the
candidate-owned evidence without duplicating its prompt/response under
`llm_logs/`. Adaptively credited offspring retain `aos/reward.json`; its
`comparison_parent_id` resolves the evaluated mutation-evidence parent through
component provenance. Head-to-head match evidence remains below
`aos/head_to_head/`.

In default mode Code Reflection metadata records `reviewed_phenotype_artifact`
as a run-relative reference to the evaluated source candidate's canonical Java
phenotype. In inherited mode it instead records `java_parent_id`,
`reviewed_java_input: inherited_java`, and the child's canonical
`reviewed_inherited_java_artifact`; that source is also the explicit Java input
to the Generator. The persisted Reviewer request contains only that source's
editable strategy region plus the immutable API guide, never fixed scaffold
source. The Code Rewriter raw response is a `remove_rule_ids`/`add_rules` delta;
its `rewritten_prompt` field is the deterministic canonical rule rendering that
becomes `genotype/code_generation_prompt.txt`. Neither path restores an
implicit `previous_code` field.

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
├── stdout.txt
├── stderr.txt
└── timing.json
```

Every normal-evaluation `result.json` and `match_metadata.json` records a
non-null canonical `opponent_id`. The 180 match directories must reconstruct
exactly the ten configured case IDs with 18 matches per opponent, without
mapping Java class names back to fitness cases. Each `result.json` `max_cycles`
and `match_metadata.json` `evaluation_configuration.tick_limit` must equal the
resolved cap of the associated map. Final-test summary map entries likewise
retain `tick_limit` beside map ID and path.

Compact mode removes transient raw replay/round-state inputs after durable telemetry/trace creation. `raw_result.json` is the unnormalized Java-runner payload and therefore is not a duplicate. New writers do not emit `match_result.json`.

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
`eagle-final-test-v2` schema. The summary records contained upstream-opponent
faults separately; a recovered containment is an explicit neutral draw rather
than a candidate win. Incomplete indexed entries are
resumed before unindexed configs; completed entries are skipped. Index paths
written by new batches and accepted by folder resume are absolute.
