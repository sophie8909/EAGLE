# EAGLE Search Lifecycle

The active search contract is opponent-wise seeded lexicase selection. See
[`../opponent-wise-lexicase.md`](../opponent-wise-lexicase.md). Older NSGA-II
steps in this file are historical and do not describe the live implementation.

`eagle.search.run_search` is the only evolutionary search entrypoint. It owns
run preparation, parent/operator selection, survival selection, generation
manifests, and the final run summary. `eagle.evaluation.evaluate_population`
owns the shared child pipeline after source creation.

## Generation lifecycle

1. Validate the experiment and preflight the configured MicroRTS opponent.
2. Prepare the run directory, resolved role topology, prompt snapshot, and timing log.
3. Build the seed population and evaluate generation zero.
4. For each generation, rank the population, select two parents, and choose crossover or copy followed by the configured mutation operator.
5. Send every child through the same evaluation boundary.
6. Apply NSGA-II non-dominated sorting, crowding, and survival selection.
7. Persist the generation population manifest and generation timing event.
8. Stop at the generation limit or configured front-0 stagnation, then write the final run summary.

## Offspring paths

Mutation is explicit in `eagle.search.create_offspring`: select the feedback
parent, choose `strategy` or `code`, run `reflector`, run `rewriter`, and leave
the resulting prompt genotype ready for the generator. Crossover is explicit in
`eagle.crossover.crossover`: select each inheritable component from the two
parents and create one complete child genotype. Neither operator validates,
compiles, evaluates, or calculates objectives.

## Shared child pipeline

`eagle.evaluation.evaluate_candidate` is the single post-source boundary:

`source assembly -> validation -> compilation -> integration -> ten-match runtime evaluation -> code-quality/game-performance objectives -> candidate artifacts -> canonical candidate result`

Known generation, validation, compilation, integration, and runtime failures
become one failed candidate result with stage, details, timing, and artifact
references. Unexpected programming errors propagate. Population update consumes
the objective values produced by this boundary; offline analysis reads those
persisted values instead of recomputing them.

## Timing semantics

Mutation and crossover timing ends when child source/genotype creation ends and
therefore excludes downstream evaluation. Generation timing includes the full
generation lifecycle. The child timing artifact records the combined pipeline,
and individual request records retain each LLM attempt, retry, status, and duration.

## Final evaluation

The current repository has no post-evolution final-test executable. The four
supported entrypoints end at the canonical evolution artifacts and offline
analysis; external opponent assets remain only because the active evolution
roster uses them during the normal match matrix.
