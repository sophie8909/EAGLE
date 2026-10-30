# EAGLE experiment comparison, 2026-10-29

## Deliverable

`deliverables/EAGLE_20261029_experiment_comparison_combined.pptx` is the existing deliverable, updated in place. A byte-identical copy at the same existing cloud filename is maintained in `J:\我的雲端硬碟\Lab\Meeting\`.

The deck contains the cloud-edited original 47 pages, the seven three-version comparison pages (48–54), and four nearest-versus-farthest pages (55–58). No new deliverable filename was created for the latter comparison. Original page contents remain unchanged; page-number denominators now show 58.

## Evidence

`source_report.md` records the supplied three-version snapshot, the historical farthest cohorts, exact run IDs, full-precision fitness and final-test calculations, source paths and comparison limits.

The farthest comparison uses both complete six-seed cohorts from `Meeting/20261021_current_workflow/stability_report_data.json` (2026-10-22 historical snapshot), with pre-28ea6606 selector code establishing the maximum-distance rule. Nearest full precision and run IDs come from the read-only remote chat “整理三版實驗數據”. Raw remote run files were not fetched anew.

Nearest mean final fitness 10.687600 exceeds farthest A 5.883962 and B 5.375332. Final-test win rates are 34.75%, 32.33% and 31.17%, respectively. Historical runs are cross-date observations; other code/runtime differences have not been isolated. Nearest timing on the same boundary is missing.

## Validation

- Opened and rendered the 58-slide candidate in native PowerPoint; visually inspected all four added pages and repaired crowded chart labels. Template artwork and editable tables/charts remain present.
- Added four-page section: 3 native tables, 2 native charts with embedded workbooks; package, geometry, reference-font, first-party import and chart/workbook checks pass.
- Whole deck: 58 slides, 15 native charts, zero package-integrity findings. Exactly one native slide-number field per slide.
- All prior 54 slide text payloads except slide-number shapes and prior chart numeric caches match the preceding deliverable.
- Verified match totals, percentages, means and differences. The 12 farthest runs are shown as two repeated six-seed cohorts, not twelve independent seeds.
- Existing historical chart/workbook consistency was not revalidated. No code tests or experiments were run for this presentation edit.

Before-edit SHA-256: `92749f39531ab356266d09eb37f9752fec848cdddf04319da9f9c85e96d8accd`.
Current SHA-256: `a009e03fd7b62d3e6bcd0787bdf9fcf40358fd7df7df8f3c14e30970c732d9df`.

Private build scripts, backups, previews and validation receipts remain under ignored `build/`.
