# Lineage schema

Lineage schema `2.0` records ancestry and exactly two component sources:

```json
{
  "lineage_schema_version": "2.0",
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

`strategy_parent_id` is policy-gene provenance and
`generation_prompt_parent_id` is code-generation-gene provenance. There is no
Java phenotype parent field. In particular, new-run lineage never writes
`previous_code_parent_id`.

Copy assigns both component fields to one parent. Crossover makes two
independent whole-component choices. Mutation retains inherited provenance and
records which operator rewrote one gene. Text equality never determines
provenance. Every referenced parent resolves to an earlier generation, lineage
is written before evaluation, and downstream failure cannot erase it.
