# EAGLE cumulative weekly presentation

## Standing workflow

Keep updating `J:\我的雲端硬碟\Lab\Meeting\EAGLE.pptx`. Add each weekly update as a new section at the end, and edit only the current week's section. Preserve older sections and the user's manual edits. The versioned repository copy is `Meeting/deliverables/EAGLE.pptx`.

## Current 1105 section

The latest user-saved source has 68 slides, with 10 slides in 1105 (59–68). The user removed the local-evolution flow slide after the previous delivery; this is retained.

The chapter uses the 2026-11-03 `RESULTS.md` snapshot retained in `source_report.md`. Twelve editable charts, a signed-difference grid and the treatment diagram cover initialization, final self-play scores, fixed-opponent averages, diversity, best-candidate W/D/L and completed search matches. Method 3 seeds 8, 9 and 10 all complete G100. Average permanent-opponent results improve, but seed 9 regresses on several metrics. Symmetric ten-opponent checkpoints and measured timing remain unavailable.

## Method 1 reference line, 2026-11-04

Slides 61 and 62 now include a native gold dashed line in each Best/Population Mean chart. All three seed positions repeat method 1's single G0 Search Game Performance, -9.001. This is one GPT candidate, not three independent measurements. Method 1 did not evolve to G100; its G0 score is retained there only as a reference across different search contexts. The fixed-evaluation mean (-9.505) is not mixed into search-score charts.

The line is an editable series linked to the chart's embedded workbook. G100 axes extend to -10. Footnotes and speaker notes state the interpretation limits. Existing chart cache floating-point tails from PowerPoint saving were synchronized to unchanged numeric workbook values; displayed source scores remain the same.

## Validation

- PowerPoint opened the 68-slide result and rendered both affected pages; line position, legend, labels and axis range were visually checked.
- Package integrity and first-party import pass. All four modified native charts pass embedded-workbook/reference/cache consistency checks.
- Exactly 12 package parts changed relative to the latest user-saved source: two slides, two notes, four charts and four embedded workbooks. Every other part remains byte-identical, including historical slide content and assets.
- No experiments were run. Private backups, scripts, renders and verification records remain under ignored `build/`.

User-saved source SHA-256: `7ff33a3d0f94251f5afa8fa2616a3a11edd35e39fe49f24085baeb669ad7b723`.
Current SHA-256: `0bcb657f64a16ba0e253c1c043108ad30db0f12ab45a1437395eb71b22386534`.
