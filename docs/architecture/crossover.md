# Uniform crossover

Uniform crossover always operates on two whole prompt components:

```text
child.strategy_prompt   <- choice(A.strategy_prompt, B.strategy_prompt)
child.generation_prompt <- choice(A.generation_prompt, B.generation_prompt)
```

In `inherited_genotype` mode it makes a third independent choice:

```text
java_parent          <- choice(A, B)
child.inherited_java <- java_parent.generated_java
                        or java_parent.inherited_java on failed generation
```

No text or Java source is spliced within a component. Default mode does not
perform the third choice.

Persist `strategy_parent_id`, `generation_prompt_parent_id`, optional
`java_parent_id`, both direct `parent_ids`, the operator, and any later mutation
type. Provenance is recorded even when component values are equal.

Tests force independent component choices, verify exact provenance and empty
pre-evaluation phenotype, and verify final Java generation consumes the active
genotype plus fixed scaffold.
