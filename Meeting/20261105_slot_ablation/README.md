# EAGLE cumulative weekly presentation

## Standing workflow

The user-facing presentation is `J:\我的雲端硬碟\Lab\Meeting\EAGLE.pptx`. Keep updating that same file. Add each weekly update as a new section at the end, and edit only the current week's section. Preserve older sections, including their existing page-number text. The versioned repository copy is `Meeting/deliverables/EAGLE.pptx`.

## 1105 section

The 1105 section contains 11 editable slides, pages 59–69 of the cumulative 69-slide deck. Sections 1021 (44 slides) and 1028 (14 slides) are preserved. All 326 original package parts other than the three shared package/slide-list manifests remain byte-identical, including all historical slide XML, charts, workbooks, notes, images, masters and layouts. Only the previously empty 1105 section is populated.

Content source: `configs/experiments/1030_gpt_framework_slot_ablation_seed8_10/RESULTS.md`, updated 2026-11-02, copied unchanged to `source_report.md` for provenance. Settings and the local variation flow were checked against the experiment README/YAML and `eagle/evolution/offspring.py` / `eagle/operators/framework_slots.py`.

Topics: three-treatment design; common framework and local EA flow; treatment-1 fixed evaluation; local baseline seeds 8/9/10; paired seed-8 initialization and G100 comparison; permanent opponents; semantic diversity; final candidate; run status and timing gaps; conclusions and next evaluation.

The evidence supports a seed-8 result, not a final cross-seed ranking. Treatment 3 has one complete seed in the supplied snapshot. Symmetric ten-opponent checkpoints and measured wall/generation timing are missing. No experiments were launched or resumed, and remote run state was not rechecked.

## Validation

- New 11-slide section: package integrity, geometry, reference font, first-party import, native table checks and five native charts with embedded workbook/cache consistency pass.
- Combined file: native PowerPoint opened 69 slides and recognized 1021 / 1028 / 1105 with 44 / 14 / 11 slides. All 11 new pages were rendered in PowerPoint and visually inspected, with original background artwork visible.
- Original 58 slides, their assets and charts remain byte-identical. Historical chart data were preserved rather than revalidated.
- Match totals and displayed win rate were checked. The deck retains the source snapshot date 2026-11-02 despite delivery on 2026-11-04.
- Private build scripts, original backup, renders and validation receipts are excluded under `build/`.

Original SHA-256: `c32044583879aa458c64b8b5622347be6ee7decce69a68853c1684d69f49b522`.
Final SHA-256: `84dcad0c6b2d9f891ae08042818f3ee288a51fd08453e7c632111539b564b120`.
