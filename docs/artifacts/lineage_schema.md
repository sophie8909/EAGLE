# Lineage schema

This is the canonical owner of candidate ancestry and component-level provenance. Normative source: specification sections 6.2 and 24.

## Base record

```json
{
  "candidate_id": "",
  "generation": 0,
  "parent_ids": [],
  "operator": "seed",
  "mutation_type": null,
  "strategy_parent_id": null,
  "previous_code_parent_id": null,
  "generation_prompt_parent_id": null,
  "source_candidate_ids": []
}
```

`source_candidate_ids` is the deduplicated set of candidates contributing any inherited component or mutation feedback. `parent_ids` records direct reproductive parents in stable order.

## Operator values

- `seed`: no direct parents; provenance fields are null unless a seed is derived from a named source artifact.
- `copy`: one parent; all three component-parent fields reference it.
- `crossover`: two direct parents; each component field identifies its independent source.
- `mutation`: one parent genotype followed by a mutation; inherited component sources remain explicit.
- `crossover+mutation`: two direct parents, three crossover sources, plus `mutation_type`.

These exact serialized strings follow the specification examples. If implementation retains a different enum, define a versioned mapping here.

## Crossover record

```json
{
  "operator": "crossover",
  "parent_ids": ["parent_a", "parent_b"],
  "strategy_parent_id": "parent_a",
  "previous_code_parent_id": "parent_b",
  "generation_prompt_parent_id": "parent_a"
}
```

For crossover plus Strategy Mutation, the crossed strategy source remains recorded and `mutation_type` becomes `strategy`. The mutation artifact identifies the rewritten output. Apply the same rule for Code Mutation and the generation-prompt source.

## Invariants

- Every non-seed parent/provenance ID resolves to a candidate in an earlier generation or an explicitly versioned external seed source.
- `previous_code_parent_id` identifies the parent whose latest evaluated `generated_java` supplied the component.
- Text equality never determines provenance.
- Mutation feedback sources are reconstructable and compatible with the mutated component.
- A lineage record is written before evaluation and survives every downstream failure.
- Candidate IDs are unique within a run.

## Tests

- Seed/copy/crossover/mutation/crossover+mutation fixtures validate against the schema.
- All provenance IDs resolve and belong to `parent_ids` where required.
- Equal parent component text does not alter provenance.
- Reconstructed child genotype exactly matches persisted pre-generation files.
- Mutation feedback selection follows provenance.
- Lineage graph is acyclic and generation numbers increase along edges.

