# Uniform crossover

Uniform crossover operates on exactly two whole prompt components:

```text
child.strategy_prompt   <- choice(A.strategy_prompt, B.strategy_prompt)
child.generation_prompt <- choice(A.generation_prompt, B.generation_prompt)
```

The choices are independent. No text is spliced within either component and no
Java phenotype participates in crossover.

Persist `strategy_parent_id`, `generation_prompt_parent_id`, both direct
`parent_ids`, the operator, and any later mutation type. Provenance is recorded
even when parent prompt strings are equal. There is no
`previous_code_parent_id` in new-run lineage or crossover provenance.

Tests force all four two-bit parent-choice combinations, verify exact
component provenance, verify the child phenotype starts empty, and verify final
Java generation still occurs from the two-gene child plus fixed scaffold.
