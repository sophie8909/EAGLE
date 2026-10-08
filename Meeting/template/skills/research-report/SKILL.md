---
name: research-report
description: Compile a requested experiment date interval into concise Traditional Chinese Markdown, including every relevant change, necessary baselines outside the interval, complete algorithm flow, measured outcomes, timing and comparison analysis. Use for experiment-window reports and research MD preparation. Does not author PPT files.
---
# Experiment interval report MD

Write Traditional Chinese, retaining official names and symbols. Produce the Markdown evidence report only. Use compact change records, diagrams and tables; omit repeated narration. PPT authoring belongs to $reference-matched-presentations.

## Interval and baseline scope

The requested date interval selects the main experiment and change inventory. State the timezone and inclusive date boundaries; state how runs crossing a boundary are included. Inspect the relevant report files, Git history and run artifacts. Include every relevant change within the interval as a separate traceable entry: date/revision, previous behavior, new behavior, purpose, affected runs, and measured impact or `尚未驗證`. Do not collapse distinct changes into a generic phase summary or imply expected impact was observed.

Select the actual reference experiment(s) needed to interpret each comparison, even when they fall outside the requested interval. Keep the original date, revision, settings, results and timing for every baseline. Label only baselines outside the interval `區間外基準`. Do not silently replace a historical baseline with a newer run. Include an experiment-to-change mapping so each run can be interpreted under its actual version/config.

Keep failed/interrupted/partial runs in the inventory with their status and available evidence. Order changes by date; organize result/comparison sections around research questions. Use run-local metadata to resolve start/end dates and distinguish execution time from analysis time. For interval requests, ask only if the date range is absent or the baseline choice would materially change the comparison and evidence cannot resolve it.

## Required evidence

1. **Complete algorithm flow.** Read the actual method/pseudocode or the relevant repository version. Include inputs, state/representation, initialization, each iteration's computation and data flow, evaluation/objective, state update or selection, branches/retries/failure exits, stopping conditions, final evaluation and outputs. Include LLM roles with inputs/outputs when present. Apply only mechanisms the method actually uses. Show loops and dependencies. One overview plus linked detail diagrams is acceptable; together they must cover the complete procedure.
2. **Experimental results and charts.** Identify each run/arm, source revision, actual execution mode, seeds/repeats, completed/failed/interrupted state, budget, evaluation context and metric definition. Show measured outcome values in a table and appropriate chart: trajectory for generations, grouped comparisons for arms, distributions for repetitions, or W/L/D/E composition. Include counts/denominators and uncertainty supported by the samples. A status-only or reproducibility report still needs its available measurements, with missing performance data stated explicitly.
3. **Measured time and cost.** Include total run elapsed time and completed-generation timings, with initialization separate. Add LLM/evaluation/compile stages, throughput or cost when recorded and useful. Label wall time versus summed stage time and parallel versus serial execution. Prefer persisted timing records to terminal estimates. Mark incomplete run timings partial. Never treat missing time as zero or multiply per-candidate work into an unsupported total. Show a timing comparison chart when measurements exist.
4. **Comparison analysis.** Compare method versus baseline and/or variants/ablations, actual results and time. Record controlled conditions and confounders: source version, hardware/model/runtime, starting state, seeds, evaluation opponents/maps, search budget and final-test protocol. Separate search fitness from common final-test performance. Show absolute differences and relative changes only when well-defined. Explain observations, supported causes, limits and the next discriminating experiment. Single runs and changed multi-factor configurations cannot establish causality.

## Source rules

Use supplied sources first; retrieve missing method/result/timing evidence from accessible paper appendices, run-local config, snapshots, metrics, final-test files and committed timing records. Historical runs retain their historical settings. EAGLE architecture must match the relevant source revision; its architecture/artifact skills can guide inspection when needed.

Cite verified file/section/page/figure/algorithm or run locators. Distinguish reported data, newly calculated values and inference. Separate mock from actual LLM, completed from partial, and deterministic contracts from observed reproducibility. Do not claim fresh tests or experiments when citing a prior report.

For unavailable evidence, use `未提供`/`無法取得` plus the exact missing field/source. Keep the corresponding content slot visible. Deliver available work with its limitations; do not mark the evidence complete until the gaps are resolved.

## Compact report MD

Use this structure, adapting table columns to the actual research. Remove guidance/placeholders from the finished report, while retaining explicit data-gap labels.

```markdown
# [Research topic]
資料截點／來源版本：[date/revision]。核心發現：[one supported sentence]。

## 區間與逐次變更
報告區間：[start–end]。基準涵蓋範圍：[dates / selection reason]。
| 日期 / revision | 變更前 | 變更後 / 目的 | 受影響實驗 | 已觀察影響 / 尚未驗證 |
| --- | --- | --- | --- | --- |

## 演算法
輸入、狀態、目標與輸出：[short definitions with sources]
[Complete Mermaid flowchart with branches, loops and exits]
[Only details needed to read the diagram and reproduce the procedure]

## 實驗設定
| 區間內 / 區間外基準 | 日期 / Arm / run | Version / mode | Budget | Seeds / repeats | Evaluation | Status |
| --- | --- | --- | --- | --- | --- | --- |

## 結果
| Arm / run | Metric / unit | Value / sample count | Source |
| --- | --- | --- | --- |
[Chart-ready series or a linked chart, with labels and units]

## 時間與成本
| Arm / run | Total wall time | Initialization | Completed-generation times | Stage / cost | Source |
| --- | --- | --- | --- | --- | --- |
[Timing chart-ready data. Mark missing/partial evidence explicitly]

## 比較分析
| Comparison | Result difference | Time difference | Controlled conditions / confounders | Supported interpretation |
| --- | --- | --- | --- | --- |
[Short finding, meaningful limitation and next test]
```

Keep chart-ready data with exact labels, units and source locators; include linked plots when useful. Hand off the MD and its data/plots to $reference-matched-presentations only when PPT is requested. Do not create PPT files as part of this skill.

## MD acceptance check

Verify every method stage/branch/loop against its source. Reconcile every chart point with the result table. Check run IDs, mode, sample count, units, time scope and comparison conditions. Ensure the full flow, outcome charts, timing, and comparison are present or explicitly identified as evidence gaps. Verify every in-scope change appears separately and every comparison includes its necessary baseline, including out-of-interval runs. Check before/after behavior and run-to-change mapping. Remove repeated disclaimers and build commentary, while retaining limitations that change interpretation.
