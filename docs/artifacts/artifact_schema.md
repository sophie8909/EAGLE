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
├── run_summary.json
└── generations/
    └── generation_<n>/
        ├── population.json
        └── candidates/
            └── <candidate_id>/
                ├── lineage.json
                ├── genotype/
                │   ├── strategy_prompt.txt
                │   ├── previous_code.java
                │   └── generation_prompt.txt
                ├── crossover/
                │   └── provenance.json
                ├── mutation/
                │   ├── metadata.json
                │   ├── reflection_request.txt
                │   ├── reflection_response_raw.txt
                │   ├── rewrite_request.txt
                │   └── rewrite_response_raw.txt
                ├── generation/
                │   ├── request.txt
                │   ├── response_raw.txt
                │   ├── extracted_candidate.java
                │   └── normalized_candidate.java
                ├── validation/result.json
                ├── compilation/
                │   ├── command.txt
                │   ├── stdout.txt
                │   ├── stderr.txt
                │   └── result.json
                ├── integration/result.json
                ├── strategy_alignment/
                │   ├── request.txt
                │   ├── response_raw.txt
                │   └── result.json
                ├── matches/
                │   ├── match_00/
                │   ├── ...
                │   └── match_09/
                ├── evaluation/
                │   ├── game_performance.json
                │   ├── code_quality.json
                │   └── objectives.json
                ├── timing.json
                └── candidate_result.json
```

The specification calls this layout recommended while making the underlying evidence mandatory. If a different physical layout is retained, it must be versioned, lossless, and documented here before use. Do not maintain duplicate equivalent files without a compatibility reason and removal plan.

## Run-level contracts

`config.yaml` preserves the supplied configuration. `resolved_config.json` records actual runtime values, including population/generation sizes, operator rates/policy, 10-match LightRush protocol, map/cycles/seeds, LLM/retry/prompt versions, objective/artifact versions, and Git commit. `run_summary.json` records completion state, selected population, Pareto fronts, objective names, and failure counts.

Never silently override an input without writing the resolved value.

## Variation and generation contracts

For a mutated candidate, retain both mutation interactions even if Rewrite or final generation fails. `metadata.json` records `applied`, mutation `type`, model identifiers, attempt counts, status, and errors. For no mutation, record `applied: false` and `type: null`.

Every offspring persists final generation request, every raw response/retry, extracted source, normalized source, and generation error. Accepted source must be byte-identifiable (for example with SHA-256) across compile and all 10 match records.

## Stage result payloads

Each stage result JSON records:

- schema version, candidate ID, stage, status, start/end references, and error;
- stage input/output artifact paths;
- validation checks or compiler/integration diagnostics;
- source/class hashes where applicable.

`candidate_result.json` is an index/summary, not a replacement for stage evidence. It includes identity, lineage reference, status/failure stage, objective values, completed-match count, and artifact references.

## Match directory contract

Each `match_<index>/` contains `result.json`, `replay.xml`, `round_states/`, `stdout.txt`, `stderr.txt`, `telemetry.json`, `performance_breakdown.json`, and `timing.json`.

Required metadata:

- `candidate_id`, `match_index`, `candidate_player`, `opponent`;
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
mutation/ contains canonical reflection_request.txt, reflection_response_raw.txt,
rewrite_request.txt, and rewrite_response_raw.txt, plus metadata.json; stage-specific
attempt files remain available for compatibility and retry inspection. The final
Java-generation stage owns generation/request.txt, response_raw.txt,
extracted_candidate.java, normalized_candidate.java, and result.json. Final generation
failures do not remove the earlier mutation evidence.

## Phase 4 implementation note

Evaluation artifacts use `artifact_schema_version = phase4-v1`. Each candidate writes one directory per match plus canonical `strategy_alignment/` and `evaluation/` payloads for game performance, Function Capability, Code Quality, objective values, evaluation summary, and runtime failure evidence. Existing flat candidate files remain temporary compatibility aliases for current readers and are tracked for removal in the migration plan.
## LLM stage identity

Each Reflection, Rewrite, and Generation stage artifact records stage, the logical llm_profile (general or coder), and the configured model alias. The alias is the launcher --alias value, not a filename inferred from .gguf or an arbitrary /v1/models response. The resolved configuration records the centralized routing: Reflection and Rewrite use general; Generation uses coder.
