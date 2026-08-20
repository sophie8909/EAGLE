# Migration plan

## Completed migrations

- complete-file candidate model and first-class lineage;
- Strategy/Code Reflection → Rewrite → Generation mutations;
- seven-opponent, 126-match evaluation and seeded lexicase selection;
- three reflection-operator modes with one AOS updater;
- unified experiment/model lifecycle;
- one-file-per-prompt resources;
- removal of fake match seeds;
- compact `eagle-run-v2` artifacts;
- one canonical match runner and match trace;
- one canonical Code Quality module;
- file-only prompt configuration and one `execution_mode`;
- shared fresh/resume search bootstrap;
- removal of obsolete run/runtime CLI wrappers and `eagle-run-v1` analysis.

## Remaining optional hardening

Fine-grained selection/crossover timing may be promoted to dedicated timing
events if future analysis requires it. It has no dependency on current search,
fitness, artifacts, or runtime behavior.

## Migration policy

New migrations update source, tests, configuration, artifacts/readers, the
Chinese overview, current status, repository map, and canonical spec together.
Unsupported historical formats are removed rather than retained as silent
compatibility layers.
