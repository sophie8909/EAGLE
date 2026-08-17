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
├── strategy_archive.json
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
        │   ├── strategy_signature.json
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
        │   ├── match_selection.json
        │   ├── global_evaluation_summary.json
        │   └── mutation_intent.json
        ├── aos/
        │   ├── reward.json
        │   └── head_to_head/matches/match_<index>/
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

`config.yaml` preserves the supplied configuration. `resolved_config.json` records actual runtime values, including population/generation sizes, operator rates/policy, the fixed seven-opponent × 18-match evaluation matrix, maps/rounds/sides/seeds, LLM/retry/prompt versions, objective/artifact versions, and Git commit. `summary.json` records completion state, selected population, seven opponent objective names, reporting metrics, and failure counts.

`generations/generation_<nnnn>.json` is the only surviving-population snapshot for a generation. It uses `eagle-generation-v2`; `final_population.json` uses `eagle-final-population-v2`. Both retain the resumable genotype/phenotype, fitness objectives, and timing, but omit raw process output, telemetry, and full mutation LLM envelopes. The run root does not write a second flat `generation_<n>_population.json` or an evolution-level `results.jsonl`.

`strategy_archive.json` is an analysis-only, schema-versioned map from known
strategy niche to one successfully evaluated representative. It does not
    participate in the seven-case fitness, lexicase survivor selection, or parent
selection. `genotype/strategy_signature.json` contains the structured Coach
signature and mutation metadata. Legacy snapshots without these fields are
read as `unknown`; no signature is inferred from prompt text.

Never silently override an input without writing the resolved value.

## Variation and generation contracts

For a mutated candidate, retain both mutation interactions even if Rewrite or final generation fails. `metadata.json` records `applied`, mutation `type`, model identifiers, attempt counts, status, and errors. For no mutation, record `applied: false` and `type: null`.

Each mutated offspring also records `aos/reward.json` after evaluation. The
`eagle-aos-reward-v2` payload identifies `generation`, `offspring_id`,
`comparison_parent_id`, and `operator` (`strategy` or `code`), with the stable
internal `operator_id` retained for generation-statistic joins. It records `reward_source`, reward,
parent/offspring runnable status, the direct matrix maps/rounds/sides and W/D/L/
error totals, match-artifact references, and operator quality/probability before
and after the generation-level update. Detailed direct matches remain owned by
`aos/head_to_head/matches/`; `reward.json` does not duplicate their process or
telemetry payloads.
Generation-level AOS state is stored in the `aos` field of
`generation_metrics.jsonl`, including selection probability, usage count,
reward count, mean reward, quality before/after, direct W/D/L/error totals, and
execution-transition counts. Analysis can therefore reconstruct each
generation's Strategy/Code probability, reward, and parent-vs-offspring record.

Every offspring persists final generation request, every raw response/retry, extracted source, normalized source, and generation error. Accepted source must be byte-identifiable (for example with SHA-256) across compile and all 126 match records.

## Stage result payloads

Each stage result JSON records:

- schema version, candidate ID, stage, status, start/end references, and error;
- stage input/output artifact paths;
- validation checks or compiler/integration diagnostics;
- source/class hashes where applicable.

`candidate_result.json` is an index/summary, not a replacement for stage evidence. It includes identity, lineage reference, status/failure stage, objective values, completed-match count, and artifact references. `mutation/reflection_context.json` is the immutable evidence snapshot used to build the Reflection request; it retains the seven opponent objective values, reporting aggregate, and normalized stage/failure evidence without recalculating fitness.

Strategy Reflection additionally persists `reflection/match_selection.json` before
deleting temporary raw match logs. It records the coverage-aware selection rule,
eligible and selected match IDs, sampled opponents/maps/player positions/results,
coverage counts, requested/actual sample size, generation/candidate identity, and
the run-derived random provenance. The sampler uses opponent coverage, then map
coverage, then LOSS/DRAW/WIN priority with seeded random tie breaking.
`reflection/global_evaluation_summary.json` is a deterministic breadth summary built
from all evaluated match summaries; it records every active opponent, map and player
side counts, overall W/D/L totals, win rate, and fully-beaten diagnostics.

`evaluation/game_performance.json` and `evaluation/objectives.json` retain both the
aggregate `game_performance` and ordered `opponent_scores`. The former also contains
`opponent_results`, with one resource/unit/W-D-L/status/failure record per opponent,
the configured weight, raw score, and weighted contribution. It records
`fixed_weight_sum`, `total_weight`, `weighted_numerator`, and the
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

Each Reflection, Rewrite, and Generation stage artifact records the stage
operation and the one configured model path. Reflection, Rewrite, Generation,
and Strategy Alignment all use the same llama.cpp endpoint/model. No model
alias, profile topology, or per-operation endpoint is persisted.

## Post-evolution artifacts

The current repository has no separate post-evolution final-test writer or
schema. All persisted evaluation evidence belongs to the normal evolution
candidate tree under `runs/<run_id>/candidates/<candidate_id>/`.


## Strategy Reflection artifacts

Temporary per-match traces are `matches/<match_id>/match_log.jsonl.gz`. They are
streamed one tick per JSONL record and deleted after terminal Match Commentator
handling. Permanent compact evidence is:

```text
matches/<match_id>/match_result.json
candidates/<candidate_id>/commentary/<match_id>/match_analysis.json
candidates/<candidate_id>/commentary/<match_id>/commentary_status.json
candidates/<candidate_id>/reflection/coach_request.json
candidates/<candidate_id>/reflection/coach_response.json
candidates/<candidate_id>/reflection/coach_result.json
```

Role envelopes contain the role, candidate and generation identity, request ID,
model-configuration identity, prompt version, and schema version. Coach artifacts
never contain raw tick logs. Coach results retain both parent
and replacement strategy prompts.
