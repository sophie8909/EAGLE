# EAGLE 2026-10-14 DSL / GPU parallel version deck

Code snapshot: `94ab1869`. The selected arm uses deterministic DSL materialization, seed 8 repeated three times, 3 evolutionary generations and population 2. The deck contains 25 editable slides using the native EAGLE 0917 template.

## Files

- `deliverables/EAGLE_20261014_dsl_gpu_parallel_v2.pptx`: final editable PowerPoint.
- `version_report.md`: method and experiment-evidence report.
- `workflow_explained.md`: slide-by-slide explanation and source notes.
- `content.json`: editable content, native diagrams and chart-ready values.
- `runtime_log_excerpt.txt`: user-supplied remote startup log excerpt.
- `build.mjs`, `native_numbers.py`: authoring and native slide-number preservation.

## Rebuild

Run `build.mjs` with the bundled Node runtime. It imports the native EAGLE POTX, retains masters/layouts/artwork/fonts, exports a draft, preserves automatic slide-number fields, validates package/geometry/fonts/import, and renders all slides. Set `EAGLE_PRESENTATIONS_SKILL`, `EAGLE_ARTIFACT_RUNTIME`, `EAGLE_TEMPLATE` or `EAGLE_DECK_NAME` only when paths or output revisions differ. The finalizer does not overwrite existing outputs.

## Validation and evidence boundary

The deck was package-validated and rendered with Artifact Tool; no native PowerPoint application test was performed. Diagrams, text, 11 tables and one chart remain editable. Startup timings derive from the single supplied remote log. No formal target-run outcome or complete generation timing was available; other smoke-run data are not treated as matched performance evidence. Presentation creation did not start experiments.
