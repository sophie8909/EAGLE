# Lineage schema

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
`strategy_parent_id` is policy-gene provenance and
`generation_prompt_parent_id` is code-generation-gene provenance. There is no
Java parent in default mode. In `inherited_genotype` mode, `java_parent_id`
identifies the candidate whose successful phenotype (or retained inherited
input after failure) supplied the child's pre-generation Java component.

Copy assigns all active component fields to one parent. Crossover makes two
independent prompt choices and, in inherited mode, an independent Java choice.
Mutation retains inherited provenance and records which operator rewrote one
prompt gene. Text/source equality never determines
provenance. Every referenced parent resolves to an earlier generation, lineage
is written before evaluation, and downstream failure cannot erase it.
