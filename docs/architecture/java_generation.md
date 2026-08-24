# Java generation, validation, and compilation

The Generator is a genotype-to-phenotype decoder.

## Exact input and output

Input:

- `strategy_prompt` as the game-playing policy;
- `generation_prompt` as reusable policy-to-Java translation instructions;
- the fixed checked-in Java scaffold, action API guide, and structural/security constraints.

The Generator receives no parent Java and no game logs. It must not independently
improve the policy. Output is one complete `ai.generated.CandidateAgent` Java
source file; patches, methods, JSON, prose, and partial source are rejected.

The raw response is persisted before extraction. Extracted/normalized generation
evidence remains under `generation/`; the canonical phenotype is
`phenotype/CandidateAgent.java`.

## Processing sequence

1. Persist the unchanged two-gene genotype and lineage.
2. Render the two genes with the canonical scaffold/API constraints.
3. Persist the request and every raw response.
4. Extract and validate one complete source.
5. Persist the phenotype, compile once, and run the ordered integration probe.
6. Reuse the identical source/classes for every evaluation match.

Validation enforces package `ai.generated`, public class `CandidateAgent`,
`AbstractionLayerAI`, required constructors/lifecycle methods, available APIs,
and prohibited network/process/file/runtime-modification capabilities.

Hard tests prove the request uses the checked-in scaffold rather than
`parent.generated_java`, and prove Generator/Evaluation preserve both prompt
genes exactly.
