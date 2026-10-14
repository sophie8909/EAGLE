# EAGLE final-version introduction

Code snapshot: `94ab1869`. This 20-slide editable presentation introduces the final deterministic DSL mode using Ministral3 8B, seed 8 repeated three times, 20 evolutionary generations and population 10. It covers the effective configuration and complete operation: initialization, DSL semantics, self-play opponents, parent/survivor selection, crossover, Strategy Reflection, compilation/evaluation, parallel execution, mandatory GPU startup and folder resume.

Standard experiment: population 10 × 20 evolutionary generations (generation 0 is separate). Each generation plans 10 offspring and selects 10 survivors. Self-play snapshots refresh at generations 5, 10, 15 and 20, with parent fitness refreshed before comparison. LLM concurrency remains 2 slots.

Runnable config: `../../configs/experiments/1015_deterministic_dsl_20x10_seed8_3runs/ministral3_8b_deterministic_dsl_20x10_seed8_3runs.yaml`. Other settings retain seed 8 repeated three times.

The ordered-rule section is expanded into four pages: actor/when/action checks, a Worker fallback example, cross-unit resource/cell reservations, and explicit idle versus rule exhaustion. Examples illustrate compiler behavior; they are not experiment measurements.

## Current files

- `deliverables/EAGLE_final_version_intro_10x20_dsl_diagrams.pptx`: final-version introduction.
- `deliverables/DSL_01_rule_checks.png` through `DSL_04_idle_and_stop.png`: exported explanation diagrams (slides 5–8).
- `final_version_explained.md`: slide-by-slide mechanism explanation and sources.
- `content.json`: current editable slide content and native diagrams/tables.
- `build.mjs`, `native_numbers.py`: native-template authoring and automatic numbering.

The preceding version-report deck and report sources remain available separately. They are not part of the final-version introduction.

## Rebuild and validation

Run `build.mjs` with the bundled Node runtime. It imports the native EAGLE 0917 POTX, retains masters/layouts/artwork/fonts, creates native diagrams and tables, exports a draft, preserves automatic slide numbers, validates package/geometry/fonts/import, and renders every slide. Set `EAGLE_DECK_NAME` for a new output revision because the finalizer does not overwrite existing outputs. Other path overrides retain their existing behavior.

The final introduction is validated with Artifact Tool and inspected slide by slide. It has 7 editable tables and no charts. Native PowerPoint application editing was not tested. Presentation creation does not start experiments.
