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

Generation zero does not call the Generator LLM. It loads the complete source
from `initial_java_seed_path`, paired with a blank policy gene, and enters the
same validation/compilation/integration/evaluation stages. Offspring generation
continues to use the normal two-gene decoder described above.
The seed and decoder scaffold are separate checked-in files: hardening fixed
offspring helpers must not alter the historical generation-zero source or hash.

Each configured seed policy file creates one generation-zero candidate; a seed
is not duplicated to fill the later-generation `population_size`. Seed
generation evidence records the resolved checked-in source path and normalized
source SHA-256. Its generation request and raw-response files are empty, and its
`generation_llm` timing has null boundaries/duration and no attempts.

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
the token-equivalent fixed scaffold outside the editable strategy markers, and
prohibited network/process/file/runtime-modification capabilities. Inside the
editable region, deterministic strategy-contract checks reject Java shapes that
the immutable prompt explicitly forbids: a helper using `context` without an
`AgentContext context` parameter, a helper reading an undeclared `gameTime`,
one-dimensional arrays initialized with nested coordinate pairs, and unavailable
`getUnitAt` lookups. These checks classify invalid generation before `javac`;
they do not repair source or add another LLM stage.

Hard tests prove the request uses the checked-in scaffold rather than
`parent.generated_java`, and prove Generator/Evaluation preserve both prompt
genes exactly.
