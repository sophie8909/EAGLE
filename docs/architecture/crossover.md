# Uniform Crossover

## Normative source

See specification section 6 and section 28.4. Lineage fields are serialized according to [`../artifacts/lineage_schema.md`](../artifacts/lineage_schema.md).

## Input

For each evaluated parent, expose:

- `strategy_prompt`;
- the latest generated and evaluated Java source (`parent.generated_java`);
- `generation_prompt`;
- `candidate_id`.

Do not read a stale pre-generation `parent.previous_code` unless it has been explicitly synchronized to the latest evaluated Java.

## Operator

Choose each genotype component independently and uniformly from Parent A or Parent B:

```text
child.strategy_prompt  <- choice(A.strategy_prompt, B.strategy_prompt)
child.previous_code    <- choice(A.generated_java, B.generated_java)
child.generation_prompt <- choice(A.generation_prompt, B.generation_prompt)
```

The three choices are independent. The operator may therefore combine components from both parents.

## Output

Crossover returns a genotype only. It does not return a Java phenotype. The crossed `A + B + C` must proceed through optional mutation and then the final Java Generation LLM.

## Required provenance

Persist the parent ID selected for each component:

- `strategy_parent_id`;
- `previous_code_parent_id`;
- `generation_prompt_parent_id`.

Also persist both `parent_ids`, `operator`, and any later `mutation_type`. Provenance must drive mutation feedback selection and must support lineage reconstruction without comparing component text.

## Tests

- Force all eight three-bit parent-choice combinations with a deterministic RNG.
- Prove the `previous_code` source is the selected parent's latest evaluated Java.
- Prove each provenance field matches its selected value.
- Prove crossover output still invokes final Java generation.
- Prove equal component strings do not corrupt provenance or feedback-parent selection.

## Prohibited behavior

- text splicing within a genotype component;
- direct Java mutation;
- using `parent.previous_code` when it is older than `parent.generated_java`;
- recording only one generic behavior parent;
- treating the selected previous code as the final child phenotype.

