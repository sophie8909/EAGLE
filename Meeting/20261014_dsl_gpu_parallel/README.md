# EAGLE final-version introduction

Code snapshot: `94ab1869`. This 17-slide editable presentation introduces the final deterministic DSL mode using Ministral3 8B, seed 8 repeated three times, 3 evolutionary generations and population 2. It covers the effective configuration and complete operation: initialization, DSL semantics, self-play opponents, parent/survivor selection, crossover, Strategy Reflection, compilation/evaluation, parallel execution, mandatory GPU startup and folder resume.

## Current files

- `deliverables/EAGLE_final_version_intro.pptx`: final-version introduction.
- `final_version_explained.md`: slide-by-slide mechanism explanation and sources.
- `content.json`: current editable slide content and native diagrams/tables.
- `build.mjs`, `native_numbers.py`: native-template authoring and automatic numbering.

The preceding version-report deck and report sources remain available separately. They are not part of the final-version introduction.

## Rebuild and validation

Run `build.mjs` with the bundled Node runtime. It imports the native EAGLE 0917 POTX, retains masters/layouts/artwork/fonts, creates native diagrams and tables, exports a draft, preserves automatic slide numbers, validates package/geometry/fonts/import, and renders every slide. Set `EAGLE_DECK_NAME` for a new output revision because the finalizer does not overwrite existing outputs. Other path overrides retain their existing behavior.

The final introduction is validated with Artifact Tool and inspected slide by slide. It has 6 editable tables and no charts. Native PowerPoint application editing was not tested. Presentation creation does not start experiments.
