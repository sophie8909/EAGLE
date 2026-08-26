# Candidate model

## Genotype and phenotype modes

Every candidate has two evolvable prompt components:

| Concept | Current field | Meaning |
| --- | --- | --- |
| Policy gene | `strategy_prompt` | Concrete MicroRTS game-playing policy (`policy_prompt` conceptually). |
| Translation gene | `generation_prompt` | Reusable instructions for faithfully translating policy into Java (`code_generation_prompt` conceptually). |

In the default `generated_phenotype` mode, the complete
`ai.generated.CandidateAgent` Java source remains non-inherited phenotype and
Code Reflection evidence. In explicit `inherited_genotype` mode, a third
pre-generation component stores the complete inherited Java source and its
parent ID. The Generator revises it into the candidate's new Java phenotype;
that successful phenotype is eligible for independent Java-component
inheritance by children.

Default-mode generation-zero seeds use one checked-in callable no-op phenotype.
Inherited mode requires one seed policy, copies it to `population_size`, gives
every copy the same no-op Java component, and invokes the Generator separately.

## Required logical fields

| Group | Fields |
| --- | --- |
| Identity | `candidate_id`, `generation`, `parent_ids` |
| Genotype | `strategy_prompt`, `generation_prompt`, and optional inherited Java input |
| Phenotype | `generated_java`, `generated_java_path` |
| Variation | `operator`, `mutation_type` |
| Component provenance | `strategy_parent_id`, `generation_prompt_parent_id`, optional `java_parent_id` |
| State/failure | `status`, `failure_stage`, `failure_reason` |
| Objectives/evidence | opponent fitness cases, game/code diagnostics |
| Persistence references | `artifacts`, `timing` |

New runtime IDs use `gen_<zero-padded-generation>_<12-hex-random-suffix>`.
Explicit IDs loaded from supported artifacts remain opaque and unchanged.

## Construction invariants

- A child genotype is complete only when every active component and its provenance are known.
- Whole-component uniform crossover makes two independent prompt choices and,
  in inherited mode, one independent Java choice.
- Strategy Reflection may change only `strategy_prompt`.
- Code Reflection may change only `generation_prompt`.
- Generator and Evaluation do not modify either prompt gene.
- Generator uses the canonical checked-in scaffold. Only inherited mode also
  receives the selected parent Java component.
- Failure never erases genotype, partial phenotype, lineage, mutation evidence, or timing.

## Compatibility

New candidate artifacts use `genotype/policy_prompt.txt`,
`genotype/code_generation_prompt.txt`, and `phenotype/CandidateAgent.java`.
The resume loader may read old prompt/phenotype paths. Missing Java-component
fields mean default mode; compatibility never silently opts an old run into
`inherited_genotype`.
