---
name: reference-matched-presentations
description: Turn an experiment-report Markdown into a concise editable research PowerPoint, or refine a deck to match visual references. Research slides include each in-interval change, required baselines even outside the interval, complete algorithm flow, outcome charts, measured timing and comparison analysis. Does not replace the separate research-report MD skill.
---

# Research PowerPoint and reference matching

## PPT input and scope

This skill authors PPT, not the research MD. Use the report MD and its chart-ready data as the content input. If no adequate MD exists, invoke $research-report as a separate preparation stage, then return here. Do not silently rewrite supplied evidence or assume a summary is complete.

For experiment interval reports, the main deck must explicitly show:
- Each relevant in-interval change: date/revision, before/after behavior, purpose, affected runs, measured impact or `尚未驗證`. Compact rows are fine; a vague multi-day engineering summary is insufficient.
- Necessary baseline experiments, preserving original date/version/settings even outside the interval. Label only out-of-interval baselines `區間外基準`. Keep them in result/time comparisons, not only in notes.
- Complete algorithm flow with actual inputs, state, initialization, iteration, model roles, evaluation, state updates, decisions, loops, bounded retries/failure exits, stopping conditions and final outputs. Use linked overview/detail diagrams when needed. Apply only mechanisms the source establishes.
- Experimental outcome tables and native charts with metric definitions, units, sample counts, seeds/repeats and actual execution/run status. PASS/config tables do not replace outcomes.
- Total run and completed-generation timing, initialization separately, plus useful recorded stages/cost. Include a native timing comparison chart when measurements exist. Distinguish wall time, stage sums, partial runs and parallel execution.
- Baseline/variant comparisons of both results and time, controlled conditions/confounders, supported interpretation and the next discriminating experiment. Separate search fitness from common final-test results, mock from actual LLM, and observation from causal claims.

Keep required evidence gaps visible as `未提供`/`無法取得` with missing fields. Do not invent chart data. Route missing source analysis back to $research-report; a request for PPT does not authorize new experiments. Respect explicit slide limits by merging related evidence; ask only if complete coverage becomes impossible.

## Native authoring and visual authority

Use the available Presentations skill for authoring, rendering and package validation. Convert the MD's Mermaid flow to connected native PowerPoint shapes. Keep charts, tables and text editable; cite source locators in relevant speaker notes.

Inspect actual reference slides/images before styling. Reuse master, theme, layouts, dimensions, fonts, palette and recurring artwork. An older reference controls appearance, not current facts. For visual-only edits, preserve approved content and major geometry.

- EAGLE default: $artifact-template-eagle-0917. A user-selected reference overrides it.
- Only for an explicitly selected Meeting 0830 profile, read [references/meeting-0830.md](references/meeting-0830.md).
- Use one coherent icon family only if it explains content; retain source/license information. Do not add decoration or flatten full slides.
- A reusable template is native POTX; a populated report is separate PPTX.

## Concision and acceptance

Lead with dated changes, then method/experiments/results/time/comparison as needed. Use compact change tables and one substantive claim per slide. Avoid repeated disclaimers, decorative labels, generic summary pages, lengthy chronology narration and build commentary. Keep conclusion-changing caveats visible and detailed provenance in notes.

Reconcile every change, baseline, diagram stage and chart value against the MD. Verify diagram branches/loops, units, sample counts, timing scope, comparison conditions, package integrity, native evidence and every rendered slide. A successful export or visual match alone does not establish completeness.

Keep scratch files out of delivery folders, preserve unrelated work, follow the workspace commit policy, and state native PowerPoint validation limits briefly.
