# Artifact schema

This is the canonical owner of run/candidate artifact paths and payload responsibility. Normative source: specification sections 21 through 23, 26, and 27. Timing and lineage field definitions are delegated to [`timing_schema.md`](timing_schema.md) and [`lineage_schema.md`](lineage_schema.md).

## Schema principles

- Persist enough data to reconstruct genotype, phenotype, lineage, variation, generation, validation, compilation, integration, matches, objectives, and timing.
- Write raw LLM responses before parsing or downstream work.
- Keep pre-generation `previous_code` separate from newly generated Java.
- Keep one directory per candidate and one directory per match.
- Version artifact and objective schemas in resolved configuration and result payloads.
- Use UTF-8 text and JSON with explicit field names; do not rely on filenames alone for identity.

## Canonical layout

```text
runs/<run_id>/
├── config.yaml
├── resolved_config.json
├── manifest.json
├── summary.json
├── final_population.json
├── generation_metrics.jsonl
├── timing.jsonl
├── generations/
│   └── generation_<nnnn>.json
└── candidates/
    └── <candidate_id>/
        ├── lineage.json
        ├── genotype/
        │   ├── strategy_prompt.txt
        │   ├── previous_code.java
        │   └── generation_prompt.txt
        ├── crossover/provenance.json
        ├── mutation/
        │   ├── metadata.json
        │   ├── reflection_context.json
        │   ├── reflector_request.txt
        │   ├── reflector_response_raw.txt
        │   ├── rewriter_request.txt
        │   └── rewriter_response_raw.txt
        ├── reflection/
        │   └── match_selection.json
        ├── generation/
        │   ├── request.txt
        │   ├── response_raw.txt
        │   ├── extracted_candidate.java
        │   └── normalized_candidate.java
        ├── validation/validation_result.json
        ├── compilation/
        │   ├── command.txt
        │   ├── stdout.txt
        │   ├── stderr.txt
        │   └── compilation_result.json
        ├── integration/integration_result.json
        ├── strategy_alignment/
        │   ├── request.txt
        │   ├── response_raw.txt
        │   └── result.json
        ├── matches/match_<index>/
        ├── evaluation/
        │   ├── game_performance.json
        │   ├── matches.json
        │   ├── code_quality.json
        │   ├── objectives.json
        │   └── summary.json
        ├── timing.json
        ├── individual.json
        └── candidate_result.json
```

The specification calls this layout recommended while making the underlying evidence mandatory. If a different physical layout is retained, it must be versioned, lossless, and documented here before use. Do not maintain duplicate equivalent files without a compatibility reason and removal plan.

## Run-level contracts

`config.yaml` preserves the supplied configuration. `resolved_config.json` records actual runtime values, including population/generation sizes, operator rates/policy, the weighted ten-opponent × 18-match evaluation matrix, adaptive `eagle_previous_best` settings, maps/rounds/sides/seeds, LLM/retry/prompt versions, objective/artifact versions, and Git commit. `summary.json` records completion state, selected population, Pareto fronts, objective names, and failure counts.

`generations/generation_<nnnn>.json` is the only surviving-population snapshot for a generation. It uses `eagle-generation-v2`; `final_population.json` uses `eagle-final-population-v2`. Both retain the resumable genotype/phenotype, fitness objectives, and timing, but omit raw process output, telemetry, and full mutation LLM envelopes. The run root does not write a second flat `generation_<n>_population.json` or an evolution-level `results.jsonl`.

Never silently override an input without writing the resolved value.

## Variation and generation contracts

For a mutated candidate, retain both mutation interactions even if Rewrite or final generation fails. `metadata.json` records `applied`, mutation `type`, model identifiers, attempt counts, status, and errors. For no mutation, record `applied: false` and `type: null`.

Every offspring persists final generation request, every raw response/retry, extracted source, normalized source, and generation error. Accepted source must be byte-identifiable (for example with SHA-256) across compile and all 180/198 match records.

## Stage result payloads

Each stage result JSON records:

- schema version, candidate ID, stage, status, start/end references, and error;
- stage input/output artifact paths;
- validation checks or compiler/integration diagnostics;
- source/class hashes where applicable.

`candidate_result.json` is an index/summary, not a replacement for stage evidence. It includes identity, lineage reference, status/failure stage, objective values, completed-match count, and artifact references. `mutation/reflection_context.json` is the immutable evidence snapshot used to build the Reflection request; it retains the canonical two-objective values and normalized stage/failure evidence without recalculating fitness.

Strategy Reflection additionally persists `reflection/match_selection.json` before
deleting temporary raw match logs. It records the available loss/draw/win counts,
the strict priority rule, eligible and selected match IDs, requested/actual sample
size, generation/candidate identity, and the run-derived random provenance.

`evaluation/game_performance.json` and `evaluation/objectives.json` retain both the
aggregate `game_performance` and ordered `opponent_scores`. The former also contains
`opponent_results`, with one resource/unit/W-D-L/status/failure record per opponent,
the configured weight, raw score, and weighted contribution. It records
`fixed_weight_sum`, `eagle_weight`, `total_weight`, `weighted_numerator`, and the
previous-generation reference when present. Generation metrics retain candidate-level
fixed-plus-dynamic score arrays, per-opponent weights and failure counts, and each
candidate's best/worst matchup. Readers treat missing
`opponent_scores` as legacy evidence and continue loading the aggregate fields.

## Match directory contract

Each `match_<index>/` contains `result.json`, `raw_result.json`, `stdout.txt`,
`stderr.txt`, `telemetry.json.gz`, `performance_breakdown.json`, and `timing.json`
when `match_artifact_mode: compact` (the default). The gzip stream holds the full
per-tick telemetry used for scoring. `result.json` and higher-level candidate
summaries contain only the compact match summary and a telemetry path; they do not
inline the same tick sequence again.

`result.json`, `evaluation/matches.json`, `evaluation/game_performance.json`,
`individual.json`, `candidate_result.json`, generation snapshots, and run summaries
must not inline match `command`, `stdout`, `stderr`, `raw_result`, or telemetry.
Those values are written once in the owning match directory. This single-owner
rule prevents process logs from being multiplied by matches, candidates, and
generations while preserving fitness and timing records.

`match_artifact_mode: full` additionally retains `replay.xml`, `round_states/`, and
an uncompressed `telemetry.json` for forensic replay/debugging. Raw round-state and
replay output is transient in compact mode: it is consumed to build the telemetry,
then removed only after the telemetry and performance breakdown are written.

Required metadata:

- `candidate_id`, `match_index`, `candidate_player`, `opponent`, `opponent_id`;
- `map`, `seed`, `max_cycles`, `final_tick`, `winner`;
- player/enemy final resources and `unit_material_trace`;
- return code, duration, status, and failure reason.

## Atomicity and failure safety

- Create candidate identity/lineage/genotype artifacts before the first LLM call.
- Write raw responses immediately; never wait for extraction success.
- Use atomic replacement for JSON summaries where partial writes would make a run unreadable.
- On interruption, retain a stage status that distinguishes `running`, `failed`, and incomplete persistence.
- Analysis tools must reject or explicitly migrate unknown schema versions.

## Tests

- Golden tree and JSON-schema checks for seed, crossover-only, both mutation types, and each failure stage.
- Readback reconstructs the exact pre-generation genotype and generated phenotype.
- No duplicate canonical source/result files.
- Every candidate and match references valid files and hashes.
- Raw responses survive parsing, rewrite, generation, compile, and runtime failures.
- Resolved configuration matches actual commands and evaluator behavior.



## Phase 2C implementation note

The active mutation artifact schema version is phase2c-v1. For each mutated candidate,
mutation/ contains canonical reflector_request.txt, reflector_response_raw.txt,
reflector_prompt_metadata.json, rewriter_request.txt, and rewriter_response_raw.txt,
plus metadata.json; stage-specific
attempt files remain available for retry inspection. `reflection_context.json` retains
the exact canonical evidence envelope used by the reflector. The final
Java-generation stage owns generation/request.txt, response_raw.txt,
extracted_candidate.java, normalized_candidate.java, and result.json. Final generation
failures do not remove the earlier mutation evidence.

The active reflection context schema is `reflection-context-v2`. Reflection metadata
records `estimated_prompt_size`, `section_sizes`, `omitted_sections`,
`truncated_sections`, and `context_schema_version`. Parsed reflection output retains
the structured analysis and proposed revised prompt separately from the later Rewrite
result. Run-level `errors.jsonl` stores deduplicated compact failure signatures; it is
not a replacement for candidate failure or match artifacts.

## Phase 4 implementation note

Evaluation artifacts use `artifact_schema_version = phase4-v3`. Each candidate writes one directory per match plus canonical `strategy_alignment/` and `evaluation/` payloads for game performance, Function Capability, Code Quality, objective values, evaluation summary, and runtime failure evidence. Phase 4 v3 makes higher-level payloads compact indexes and removes duplicate evolution-level result/population files. `evaluation/code_quality.json` persists `code_quality_details` with the four weighted complexity penalties, raw metric values, `metric_version`, and `measured_source`. All active readers consume the versioned canonical candidate tree directly.

## Match Commentator artifacts

The active match directory additionally owns `match_metadata.json`, streamed
`match_trace.jsonl.gz`, `match_trace_integrity.json`, and `match_result.json`.
The `commentary/` child owns one JSON file per contiguous chunk plus
`final_request.json`, `final_response.json`, `match_commentary.json`, and
`commentary_status.json`. Strategy Reflection owns
`reflection/match_selection.json` under the selected child candidate. Raw
commentator logs are removed after selection/terminal commentary handling;
compact match result and scoring artifacts remain match-owned and are not copied
into reflection prompts.
## LLM stage identity

Each Reflection, Rewrite, and Generation stage artifact records stage, the logical llm_profile (reflector, rewriter, or generator), and the configured model alias. The alias is the launcher --alias value, not a filename inferred from .gguf or an arbitrary /v1/models response. The resolved configuration records the centralized routing: Reflector, Rewriter, and Generator use their resolved semantic role profiles.

## Post-evolution Final Test artifacts

Final Test writes only beneath `runs/<run_id>/final_tests/<final_test_id>/` and never overwrites Evolution Evaluation evidence. Schema `eagle-final-test-v1` owns copied/resolved configuration, pre-match selection proof, opponent commits/classes/JAR hashes/adapter hashes, compile-once source/class identity, one evidence directory per scheduled match, JSONL results, failure inventory, aggregation, and timing.

Unknown final-test schemas are rejected by the UI-independent reader. The complete tree and field ownership are defined in [`../evaluation/final_test.md`](../evaluation/final_test.md).


## Strategy Reflection artifacts

Temporary per-match traces are `matches/<match_id>/match_log.jsonl.gz`. They are
streamed one tick per JSONL record and deleted after terminal Match Commentator
handling. Permanent compact evidence is:

```text
matches/<match_id>/match_result.json
candidates/<candidate_id>/commentary/<match_id>/match_analysis.json
candidates/<candidate_id>/commentary/<match_id>/commentary_status.json
candidates/<candidate_id>/reflection/manager_request.json
candidates/<candidate_id>/reflection/manager_response.json
candidates/<candidate_id>/reflection/manager_analysis.json
candidates/<candidate_id>/reflection/coach_request.json
candidates/<candidate_id>/reflection/coach_response.json
candidates/<candidate_id>/reflection/coach_result.json
```

Role envelopes contain the role, candidate and generation identity, request ID,
model-configuration identity, prompt version, and schema version. Manager and
Coach artifacts never contain raw tick logs. Coach results retain both parent
and replacement strategy prompts.
