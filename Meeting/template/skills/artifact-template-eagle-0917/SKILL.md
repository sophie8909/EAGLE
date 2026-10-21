---
name: artifact-template-eagle-0917
description: Create or refine editable EAGLE research presentations with the current infographic composition, EAGLE 0917 palette and original background artwork. Use for EAGLE decks or when this template is selected.
---

# EAGLE research template

## Content first

Use $research-report for report MD preparation and $reference-matched-presentations for PPT authoring as two separate skills. Every interval report shows each change explicitly and includes the necessary baseline experiments even outside the interval. Label baseline dates and actual versions. Every research deck covers the complete source-grounded algorithm, measured results with charts, measured time, and comparison analysis. Retrieve accessible missing run evidence; otherwise retain the section with an explicit evidence gap. Never replace results with only PASS/config/commit tables.

## Native starting files

Read `artifact-template.json`. Use `assets/EAGLE.potx` as the native starting template and `assets/reference.pptx` as the editable page examples. The original 0917 reference is retained as `assets/reference-0917.pptx` for visual comparison. Read `assets/EAGLE.palette.json` for colors.

The editable example pages demonstrate source-grounded compositions such as:

- Complete algorithm flow, a slot-choice grid, opponent-pool diagram and evaluation matrix.
- Native score chart, final result comparison, diversity view and timing evidence.
- Interval change chronology with before/after, purpose, run mapping and outside-baseline provenance.
- Detailed iteration, model roles and failure/retry branches.

These are visual examples, not universal EAGLE facts. Their labels, numbers, opponents, configuration, and claims come from the source material used to create each example. Replace them from the new task's sources before reuse; never carry example data into a new deck as current facts. Add detail pages when needed; template example count does not fix output slide count.

Keep the historical `reference-0917.pptx` and `EAGLE-0917.potx` unchanged for visual comparison, and retain their original twelve native layouts. The current reference contains the approved infographic examples and revised research layouts; its page count does not constrain future decks.

Any invented chart sample values must be visibly marked illustrative. Source-grounded examples retain their original provenance in notes; replace all example data before delivering a new research deck.

## Visual contract

Preserve the original EAGLE background artwork, Source Han Serif TW, dimensions, existing layouts, theme accents, default table style and automatic slide numbering. Use `assets/EAGLE.potx` and `assets/reference.pptx` as the native editable sources. Keep diagrams, tables, charts and text editable.

Restore the original artwork as the native background fill on its master or layout. If a renderer or slide export does not reliably show inherited artwork, apply the same native background fill to that slide as well. Never place a full-slide ivory rectangle over the artwork to conceal it. Verify that the artwork is visibly rendered in the delivered deck.

Keep the reference's concise infographic composition: connected diagrams, choice grids, evaluation matrices and native charts should carry the explanation. Do not revert to paragraph-heavy generic research pages. On the 1672 × 941 canvas, use the current reference geometry: title x64 y36 w1544 h82; subtitle x66 y122 h50; body y190–841; footer y848; one right-aligned slide number at x1450 y906. Use a native slide-number field and show only one visible number per slide.

The template places its single dynamic `slidenum` field on the master as ordinary text rather than a hidden footer placeholder. New slides inherit it automatically; do not add a second page-level number when using this master.

Title and subtitle placeholders must explicitly disable inherited bullets, so typing on a new slide preserves the plain reference typography.

- Table header: dusty blush #DEB4BA, charcoal #423C3B text. Body: ivory #FCF8F5. Pale gold #FAEDC6 only for meaningful emphasis.
- Titles/key numbers: burgundy #47171C. Ordinary text: charcoal #423C3B.
- Comparisons: rose #CF8792 and burgundy #47171C, optional muted rose #CF9BA5. Preserve each series' meaning across charts.
- Keep the palette and flat, legible infographic composition. No paragraph-heavy layouts, repeated takeaway blocks, filler subtitles, dashboard cards or extra decoration.

Use the available Presentations skill for authoring and validation. Check content coverage, native evidence, chart values/units and every rendered page against the MD and reference. Inspect every page visually and confirm the original artwork is visibly rendered; merely finding artwork or a background reference in the PPTX package is insufficient.
