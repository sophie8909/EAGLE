# EAGLE cumulative weekly presentation

## Standing workflow

Keep updating `J:\我的雲端硬碟\Lab\Meeting\EAGLE.pptx`. Add new weekly sections at the end, edit only the current week, and preserve the user's manual changes. The versioned repository copy is `Meeting/deliverables/EAGLE.pptx`.

## 1105 section: completed fixed evaluations

The deck retains the user's 68-slide version and 10-slide 1105 section (59–68). The removed algorithm-flow page remains removed. The source is the 2026-11-04 experiment `RESULTS.md`, copied unchanged to `source_report.md`.

The updated result pages now show the completed frozen ten-opponent benchmark: G0–G100 at five-generation intervals, 21 checkpoints, three seeds per method, 600 matches per representative candidate. Six runs give 126 evaluated representatives and 75,600 fixed-evaluation matches. There are zero match errors; 54 AllInBot upstream faults were safely isolated and neutralized under the protocol, not attributed to candidate runtime failure. All representatives passed compilation, seven integration checks and matrix validation.

Method 3's three-seed mean win rate and match score exceed method 2 at all 21 checkpoints. G100 win rates are 67.50% versus 58.83% (+8.67 percentage points). G100 mean scores are 39.862 versus 21.459. Method 3 peaks at G40 (71.22%, score 46.339) and later declines. Seed 9 remains a counterexample: 56.67% versus method 2's 65.67% at G100. Gains against COAC, AllInBot and TMA are visible in the opponent comparison.

Slides 63/64 now show native checkpoint win-rate and mean-score curves; 66 shows G100 seed comparisons; 67 shows ten-opponent G100 win rates including method 1; 68 shows the 58/63 paired-score advantage and evaluation limits. Slide 59 only updates the snapshot date. Unchanged pages 60/61/62/65 retain their existing valid results. There are 13 editable charts in 1105, 28 in the whole deck.

The fixed benchmark evaluates only each checkpoint's highest-search-score runnable survivor, not the population mean. Three seeds provide descriptive evidence for this frozen protocol; no inferential statistics or broader generalization is claimed. Checkpoints within a run reuse the fixed seed scheme and are not independent evolution repeats. Measured timing remains unavailable.

## Method 1 baselines

The four search-score comparison charts on slides 61/62 preserve their editable gold dashed reference at G0 Search Game Performance -9.001. Method 1 did not evolve to G100, and the repeated seed positions are one reference value rather than three runs.

The new fixed-evaluation curves use the matching fixed-evaluation baselines: 44.17% win rate and -9.505 mean match score from method 1's single 600-match evaluation. These are gold dashed native chart series, separate from the search-score baseline.

## Validation

- All five new result pages were rendered and visually inspected in native PowerPoint, including the repaired curve-axis labels. Original background artwork remains visible.
- Native data checks pass for all six new charts and their embedded workbook/cache references. Package integrity and full-deck first-party import pass (68 slides, 28 charts).
- Source tables were parsed directly; assertions cover all 21 checkpoints, average superiority at each checkpoint, G40 peak, match totals and six endpoint W/D/L sums. Notes retain detailed provenance and endpoint counts.
- All first-58-slide contents and assets remain byte-identical to the prior delivery. The original presentation slide list/order is unchanged. Existing method-1 search reference charts and their workbooks remain byte-identical. Superseded result-page chart/note/workbook dependencies were removed without altering shared dependencies.
- Only 1105 pages 59/63/64/66/67/68 and their corresponding dependencies change. Historical chart data were not revalidated. No experiments were launched or rerun.
- Private scripts, backups, previews and validation records remain under ignored `build/`.

Before SHA-256: `0bcb657f64a16ba0e253c1c043108ad30db0f12ab45a1437395eb71b22386534`.
Current SHA-256: `75e6c1594f7905cb572380222765cea057315a8c1195ab146054c591876249e8`.
