# Candidate model

## Genotype and phenotype

The canonical genotype has exactly two evolvable prompt components:

| Concept | Current field | Meaning |
| --- | --- | --- |
| Policy gene | `strategy_prompt` | Concrete MicroRTS game-playing policy (`policy_prompt` conceptually). |
| Translation gene | `generation_prompt` | Reusable instructions for faithfully translating policy into Java (`code_generation_prompt` conceptually). |

The phenotype is the generated complete `ai.generated.CandidateAgent` Java
source. Java source is evaluation and Code Reflection evidence; it is never a
genotype component and is never inherited into a child Generator request.
Generation-zero seeds use one shared checked-in callable no-op Java phenotype
paired with the policy from each configured seed file. A seed policy may be
empty or non-empty; this initialization exception does not add an evolvable
field.

## Required logical fields

| Group | Fields |
| --- | --- |
| Identity | `candidate_id`, `generation`, `parent_ids` |
| Genotype | `strategy_prompt`, `generation_prompt` |
| Phenotype | `generated_java`, `generated_java_path` |
| Variation | `operator`, `mutation_type` |
| Component provenance | `strategy_parent_id`, `generation_prompt_parent_id` |
| State/failure | `status`, `failure_stage`, `failure_reason` |
| Objectives/evidence | opponent fitness cases, game/code diagnostics |
| Persistence references | `artifacts`, `timing` |

New runtime IDs use `gen_<zero-padded-generation>_<12-hex-random-suffix>`.
Explicit IDs loaded from supported artifacts remain opaque and unchanged.

## Construction invariants

- A child genotype is complete only when both prompt genes and their provenance are known.
- Whole-component uniform crossover makes exactly two independent parent choices.
- Strategy Reflection may change only `strategy_prompt`.
- Code Reflection may change only `generation_prompt`.
- Generator and Evaluation do not modify either prompt gene.
- Generator uses the canonical checked-in scaffold, never a parent phenotype.
- Failure never erases genotype, partial phenotype, lineage, mutation evidence, or timing.

## Compatibility

New candidate artifacts use `genotype/policy_prompt.txt`,
`genotype/code_generation_prompt.txt`, and `phenotype/CandidateAgent.java`.
The resume loader may read the old prompt/phenotype paths, but ignores legacy
`previous_code` and `previous_code_parent_id`; compatibility cannot reintroduce
the old third gene into active state.
