# Candidate model

## Genotype and phenotype modes

In `java_materialization_mode: llm`, active genes are `strategy_prompt` and
`generation_prompt`. The default `candidate_java_mode: generated_phenotype`
keeps complete Java as phenotype/evidence; `inherited_genotype` adds a complete
pre-generation Java component that the Generator revises into the phenotype.

`java_materialization_mode` is independent of candidate Java state mode. An
absent value defaults to `llm` for old configs. In `deterministic_dsl`, only the
complete `strategy_prompt` is active genotype. Generation prompt and optional
inherited Java are inactive compatibility data and do not participate in
materialization, crossover, or mutation. Candidate snapshots record mode,
compiler version, and `active_genotype_components: ["strategy_prompt"]`.
Deterministic mode uses whole-policy copy/crossover only; it has no rule-level crossover. New deterministic configs require `candidate_java_mode: generated_phenotype` and `parent_evaluation_mode: reuse_cached`.

LLM-mode initialization and inheritance continue to follow the configured
`generated_phenotype`/`inherited_genotype` and seed initialization modes. The
Generator call and inherited-Java context apply only when materialization mode is
`llm`; deterministic materialization consumes normalized policy and the canonical
scaffold.

## Policy contract

`strategy_prompt` stores canonical `eagle-strategy-dsl-v1` JSON, validated by
`eagle/strategy_dsl.py`. Ordered rules contain `actor`, `when`, `action`; intrinsic
legality guards are fixed, and empty rules idle. The LLM Generator or the
`deterministic_dsl` compiler implements this policy offline without a runtime
DSL interpreter. New runs reject natural language. The independent Java source
gate and corrective Code Reflection apply only to `llm` mode. See
[mutation](mutation.md) for the mode-specific mutation contract.

## Required logical fields

| Group | Fields |
| --- | --- |
| Identity | `candidate_id`, `generation`, `parent_ids` |
| Genotype | `active_genotype_components`; mode-specific prompt and optional inherited Java values |
| Phenotype | `generated_java`, `generated_java_path` |
| Variation | `operator`, `mutation_type` |
| Component provenance | `strategy_parent_id`, `generation_prompt_parent_id`, optional `java_parent_id` |
| State/failure | `status`, `failure_stage`, `failure_reason` |
| Objectives/evidence | active-mode fitness, executable semantic signature, game/code diagnostics |
| Persistence references | `artifacts`, `timing` |

New runtime IDs use `gen_<zero-padded-generation>_<12-hex-random-suffix>`.
Explicit IDs loaded from supported artifacts remain opaque and unchanged.

## Construction invariants

- A child genotype is complete only when every active component and its provenance are known.
- In `llm` mode, whole-component crossover chooses the two prompt genes
  independently and, in inherited mode, Java independently.
- In `deterministic_dsl` mode, whole-policy copying/crossover is the only
  genotype operation; rule-level crossover is absent.
- Strategy mutation may change only `strategy_prompt` in either materialization
  mode.
- Prompt Reflection may change only `generation_prompt` in `llm` mode and is
  disabled in deterministic mode.
- Code Reflection preserves active genes and revises Java only in `llm` mode;
  deterministic mode disables Code Reflection and source repair.
- Java materialization and Evaluation do not modify active genotype
  components.
- The LLM Generator uses the canonical scaffold and receives selected parent
  Java only in inherited candidate mode. The deterministic compiler uses
  normalized policy and canonical scaffold only.
- Failure never erases genotype, partial phenotype, lineage, mutation
  evidence, or timing.
- `semantic_signature` describes the compiled full agent on the versioned
  probe dataset; it is distinct from prompt-derived `strategy_signature` metadata.
## Compatibility

New candidate artifacts use `genotype/policy_prompt.txt`,
`genotype/code_generation_prompt.txt`, and `phenotype/CandidateAgent.java`.
Historical artifacts remain read-only. Resume rejects incompatible natural-language
policy and old reproduction/operator contracts; it never silently converts them.
