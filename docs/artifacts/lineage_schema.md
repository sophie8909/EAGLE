# Lineage schema

## DSL and pre-crossover source contract (2026-10-11)

Selected sources pass their own DSL-policy/Java checks before actual variation.
Defective or failed checks yield a one-parent child with unchanged source genes
and provenance. Healthy children retain compact `pre_crossover_code_checks` refs.
Source-parent artifacts remain immutable.

Lineage schema `3.0` records ancestry, two prompt sources, and an optional Java
component source:

```json
{
  "lineage_schema_version": "3.0",
  "candidate_id": "",
  "generation": 0,
  "parent_ids": [],
  "operator": "seed",
  "mutation_type": null,
  "strategy_parent_id": null,
  "generation_prompt_parent_id": null,
  "source_candidate_ids": []
}
```

`java_parent_id` is an optional field present in inherited mode.
`strategy_parent_id` is policy-gene provenance and identifies the evaluation
parent used to select the single worst completed match for Strategy Reflection;
`generation_prompt_parent_id` is code-generation-gene provenance. There is no
Java parent in default mode. In `inherited_genotype` mode, `java_parent_id`
identifies the candidate whose successful phenotype (or retained inherited
input after failure) supplied the child's pre-generation Java component.

Copy assigns all active component fields to one parent. Crossover makes two
independent prompt choices and, in inherited mode, an independent Java choice.
Mutation retains inherited provenance and records whether Strategy rewrote the
DSL policy or Prompt rewrote the generation prompt. Independent Code gating
records source checks; corrective children revise one source Java without
crossover or ordinary mutation. Text/source equality never determines
provenance. Every referenced parent resolves to an earlier generation, lineage
is written before evaluation, and downstream failure cannot erase it.

Generation-zero candidates have no parent IDs in either initialization mode.
The optional candidate metadata `initial_policy_source` distinguishes
`configured_seed` from `llm_generated`; it is origin evidence, not ancestry and
does not populate a component-parent field.

Healthy audit-only source checks use `operator: code_check` and
`mutation_type: code`; they are provenance evidence, not population individuals.
Actual corrective offspring use `operator: mutation` with one source parent.
Semantic analysis excludes audit snapshots from candidate/unavailable counts;
source-parent lineage and artifacts remain unchanged.
