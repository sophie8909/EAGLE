# EAGLE current workflow presentation

Source snapshot: repository HEAD `1fa6662e`, inspected on 2026-10-13 (Asia/Taipei).
This is a process explanation, not an experiment-results report. No experiments or runtime changes were made.

## Files

- `deliverables/EAGLE_20261013_workflow.pptx`: 51 editable slides, with detailed speaker notes and source locators.
- `workflow_explained.md`: the same slide content and full explanations for text search and review.
- `content.json`: the authoritative content used to generate both artifacts.
- `build.mjs`: Artifact Tool builder using the EAGLE native POTX master, palette and fonts.
- `native_numbers.py`: retains native automatic slide-number fields with correct cached slide numbers.

The main example uses the actual 1013 YAML: self-play, inherited Java genotype, static mutation, population 2 and 3 evolutionary generations. The file name contains workers_11, while the content sets workers=9. Fixed-roster, lexicase and adaptive operator modes are explained as alternate branches. Example values are labeled as teaching examples.

## Rebuild

Use the bundled Node and Python runtimes. Optional environment overrides: `EAGLE_PRESENTATIONS_SKILL`, `EAGLE_ARTIFACT_RUNTIME`, `EAGLE_TEMPLATE`, `EAGLE_FONT_REFERENCE`, and `EAGLE_DECK_NAME`. Set a new deck name for each revision because the finalizer refuses to overwrite a final output.

Before a new authoring operation, run the Presentations skill's `container_tools/mark_artifact_operation_started.mjs` once. Then execute `build.mjs`. It verifies source paths, exports a private draft, checks PPTX structure, fonts, dimensions and native tables, confirms import, and renders every slide. Build receipts and previews stay in ignored `.codex-build/`.

## Verification boundary

Source claims were checked against the current local implementation, including an independent opponent/selection/reflection review. Package, geometry, font and import validation plus visual inspection of all slides were performed. PowerPoint desktop validation and new EAGLE experiments were not performed.
