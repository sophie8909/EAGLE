# Evolutionary flow

## Normative source

See specification sections 4, 5, 19, 20, and 30. Operator-local contracts are in [`crossover.md`](crossover.md) and [`mutation.md`](mutation.md).

## Population lifecycle

1. Construct seed candidates with complete three-part genotypes.
2. Generate, validate, compile, integrate, and evaluate every seed candidate.
3. Assign NSGA-II Pareto rank and crowding distance using exactly two maximized objectives.
4. Select each parent by binary tournament.
5. Apply Uniform Crossover at the configured rate, or copy an explicitly recorded parent genotype.
6. Apply at most one selected mutation type at the configured rate.
7. Invoke the final Java Generation LLM for every child.
8. Evaluate each child through the complete pipeline.
9. Combine parents and offspring, then retain complete Pareto fronts plus the highest-crowding members of a partial front.
10. Persist the selected population and continue.

## Parent selection contract

Binary tournament comparison order:

1. lower Pareto rank;
2. higher crowding distance;
3. random tie-break.

Selection does not change candidate state. Any fallback comparison beyond that ordering must be justified by the specification or recorded as a gap.

## Objective contract

- Optimize only `game_performance` and `code_quality`.
- Maximize both values.
- Keep failed candidates eligible for ranking with failure values assigned by the evaluation contract.
- Never expose `strategy_alignment` as a third objective; it is a successful-code-quality component.

The formula owners are [`../evaluation/game_performance.md`](../evaluation/game_performance.md), [`../evaluation/code_quality.md`](../evaluation/code_quality.md), and [`../evaluation/failure_classification.md`](../evaluation/failure_classification.md).

## LLM call accounting

| Offspring path | Variation calls | Final generation call | Total before retries/evaluation |
| --- | --- | --- | --- |
| Crossover/copy only | none | 1 | 1 |
| Strategy Mutation | Reflection + Strategy Rewrite | 1 | 3 |
| Code Mutation | Reflection + Generation Prompt Rewrite | 1 | 3 |

Strategy Alignment evaluation adds a separate evaluation LLM call only after successful execution. Retry counts and durations belong to the timing schema.

## Operational invariants

- Do not evaluate an unevaluated initial population with NSGA-II defaults.
- Do not select mutation feedback by string equality; use recorded component provenance and relevant parent evidence.
- Do not bypass final Java generation for copied, crossed, or mutated offspring.
- Do not regenerate Java during the 10-match batch.
- Persist generation-zero and later population views using the artifact contract.

