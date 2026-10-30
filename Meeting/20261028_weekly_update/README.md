# EAGLE weekly appendix, 2026-10-28

## Deliverable

`deliverables/EAGLE_20261028_weekly_update_combined.pptx` contains the 44-slide cloud master followed by 12 new Traditional Chinese slides, numbered 45–56. A byte-identical copy is saved in `J:\我的雲端硬碟\Lab\Meeting\EAGLE_20261028_weekly_update_combined.pptx`.

The original cloud file remains unchanged (SHA-256 `e90a4e13b0d6a3392904e35347b0d91c6ec955ee0dd0d71ee4cfb46e43254ff6`). Only the page-count denominator changes on the retained pages in the combined copy.

## Evidence

- `source_report.md` is the original text attachment recovered from the referenced conversation. Its result and run-status tables are the 2026-10-24 historical snapshot, not live status.
- The source deck, pages 38 and 44, supplies the historical local-search timing baseline. Plot values convert the original seconds to hours, rounded to six decimal places. Source seconds remain in the new slide notes.
- New pages distinguish implementation, historical tests, scheduled experiments and completed runs. No new experiment or source-code test run was performed for this presentation task.

## Validation

- Opened the source and final combined candidate with native PowerPoint. Rendered all 44 source slides and all 12 appended slides, and visually inspected the appendix.
- Final combined package: 56 slides, 11 native charts, zero package-integrity findings.
- All original 44 slide text payloads and historical chart numeric caches match the cloud master, excluding the slide-number shapes. The cloud master is unchanged, and the delivered cloud copy matches the repository copy.
- Exactly one native slide-number field on each of 56 slides.
- The appendix separately passed package, layout, reference-font, first-party import and native-chart/workbook checks: 7 native tables and 2 editable charts with embedded workbooks. Native charts use Source Han Serif TW throughout.
- Strict whole-deck chart/workbook checking detects pre-existing cache-versus-cell inconsistencies on source pages 39, 40 and 41. Those historical charts and workbooks were preserved rather than rewritten. The combined deck is not claimed to pass that whole-deck consistency gate.

Final SHA-256: `8abf08fdd642a7d689514cf08ab47ee91b7bf93d6fdcea6b713e7f06631aecbd`.

Private build scripts, previews and detailed validation receipts remain under ignored `build/`.
