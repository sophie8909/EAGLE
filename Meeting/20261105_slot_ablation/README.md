# EAGLE cumulative weekly presentation

## Standing workflow

The user-facing presentation is `J:\我的雲端硬碟\Lab\Meeting\EAGLE.pptx`. Keep updating that same file. Add each weekly update as a new section at the end, and edit only the current week's section. Preserve older sections, including their existing page-number text. The versioned repository copy is `Meeting/deliverables/EAGLE.pptx`.

## 1105 section, updated 2026-11-04

The 1105 section remains 11 slides, pages 59–69 of the cumulative 69-slide deck. Sections 1021 (44 slides) and 1028 (14 slides) are preserved. All 326 historical package parts other than the three shared package/slide-list manifests remain byte-identical to both the initial deck and the prior delivery, including historical slides, charts, workbooks, notes, images, masters and layouts.

Content source: `configs/experiments/1030_gpt_framework_slot_ablation_seed8_10/RESULTS.md`, updated 2026-11-03, copied unchanged to `source_report.md` for provenance. Settings and the local variation flow follow the experiment README/YAML and the previously checked `eagle/evolution/offspring.py` / `eagle/operators/framework_slots.py`.

Method 3 seeds 8, 9 and 10 now all complete G100. The chapter replaces numeric tables with 12 editable native charts, a signed-difference grid and method/algorithm diagrams. The charts show treatment-1 fixed-opponent win rates, paired G0 and G100 scores, three-seed permanent-opponent averages, semantic diversity, best-candidate W/D/L by seed and completed search-match counts. IDs and full best-candidate score details are retained in speaker notes.

The conclusion now reflects consistent initialization gains and favorable three-seed permanent-opponent means, alongside seed-9 regressions and diversity collapse. Symmetric ten-opponent checkpoint evaluations and measured wall/generation timing are still missing. No experiments were launched or resumed, and remote run state was not rechecked.

## Validation

- New section: package integrity, geometry, reference font and first-party import pass. All 12 native charts have embedded workbooks whose values and numeric caches agree. There are no native data tables in the updated chapter.
- Combined file: 69 slides, 27 charts, zero package-integrity findings. PowerPoint opened the deck and rendered all 11 updated pages for visual review. Two repaired chart pages were rendered and inspected again. Original artwork remains visible.
- Original 58 slides and their dependencies remain byte-identical to the initial deck and previous delivery. Historical chart data were preserved rather than revalidated.
- Match totals, initial-advantage claims and best-candidate W/D/L totals were checked. Per-seed difference cells use the report's displayed operands and show one decimal; aggregate improvements retain the report values, which can differ by 0.001 from rounded-row arithmetic.
- Private scripts, original backups, renders and validation receipts remain excluded under `build/`.

Initial SHA-256: `c32044583879aa458c64b8b5622347be6ee7decce69a68853c1684d69f49b522`.
Previous delivery SHA-256: `84dcad0c6b2d9f891ae08042818f3ee288a51fd08453e7c632111539b564b120`.
Current SHA-256: `58457c41413a5e7a5367526de1f8b234fc4811dff6ca5d8abd8f20dcd07751d0`.
