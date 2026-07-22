# Candidate model

## Normative source

See specification sections 2, 3, 24, 28, and 29. Lineage serialization is owned by [`../artifacts/lineage_schema.md`](../artifacts/lineage_schema.md).

## Genotype and phenotype

| Symbol | Field | Meaning |
| --- | --- | --- |
| `A` | `strategy_prompt` | High-level MicroRTS behavior intent. |
| `B` | `previous_code` | Complete Java source most recently generated for and evaluated as the source parent. |
| `C` | `generation_prompt` | Instructions controlling complete-file Java generation. |

The genotype is `A + B + C`. The phenotype is the new complete `CandidateAgent.java` produced by the final Java Generation LLM.

`previous_code` is not a static seed snapshot. If genotype `A1 + B1 + C1` generates and evaluates Java `B2`, the inheritable evaluated state is `A1 + B2 + C1`.

## Required logical fields

An implementation may use nested records, but it must expose and persist these names or an explicitly versioned lossless mapping:

| Group | Fields |
| --- | --- |
| Identity | `candidate_id`, `generation`, `parent_ids` |
| Genotype | `strategy_prompt`, `previous_code`, `generation_prompt` |
| Phenotype | `generated_java`, `generated_java_path` |
| Variation | `operator`, `mutation_type` |
| Component provenance | `strategy_parent_id`, `previous_code_parent_id`, `generation_prompt_parent_id` |
| State/failure | `status`, `failure_stage`, `failure_reason` |
| Objectives | `game_performance`, `code_quality` |
| Persistence references | `artifacts`, `timing` |

Recommended internal separation:

- `CandidateGenotype`: the three heritable components;
- `CandidatePhenotype`: the newly generated complete Java;
- `CandidateEvaluation`: match evidence, objective values, and failure data.

## Lifecycle

Valid logical states are:

1. `constructed`: genotype and lineage are complete.
2. `generation_started`: final Java request has been persisted.
3. `generated`: raw response, extracted source, and normalized source are persisted.
4. `validated`: source contract passed.
5. `compiled`: one class set is available.
6. `integrated`: MicroRTS can load and initialize the class.
7. `evaluated`: all 10 matches and both objectives completed.
8. `failed`: a terminal failure records the exact `failure_stage` and retains earlier evidence.

These labels are a documentation model, not newly mandated serialized enum values. Serialized status values must be versioned and map unambiguously to the required pipeline stages.

## Construction invariants

- A child is not complete until all three genotype components and component-level provenance are known.
- Crossover reads the evaluated parent phenotype for the `previous_code` component.
- Mutation changes only the component owned by its mutation type. See [`mutation.md`](mutation.md).
- The final generation result is stored separately from the pre-generation `previous_code`; artifact writing must not overwrite either value.
- The next generation inherits the child phenotype as its `previous_code` only after that phenotype has been evaluated.
- A failure does not erase genotype, partial phenotype, lineage, mutation output, or timing.

## Implementation mapping

Current code centers the record in `eagle/candidate.py` and reconstructs it in `eagle/evaluation.py`. The active dataclass lacks several first-class contract fields and artifact writing overwrites the pre-generation evidence. Treat [`../implementation/current_status.md`](../implementation/current_status.md) and gap `G-01` in [`../implementation/architecture_gaps.md`](../implementation/architecture_gaps.md) as migration evidence, not normative behavior.

