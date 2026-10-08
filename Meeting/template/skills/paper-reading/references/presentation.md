# Presentation and infographic modes

## Presentation

Use $research-report for Markdown content preparation and $reference-matched-presentations separately for PPT authoring when requested. Always include the paper's complete algorithm flow, measured experimental results with charts, time/cost evidence, and comparison with the paper's own baselines/ablations. Read methods, algorithms, experiments, appendices and captions; do not restrict the evidence to the abstract or an existing summary.

Use the paper's actual framework and vocabulary. Mark unreported timings or missing measurements explicitly without inventing data. A novelty summary or result-status table does not replace algorithm flow or outcome charts. Create an actual PPTX only when requested, through the available Presentations workflow. Preserve narrower infographic/translation requests.

## Infographic summary
Use these five sections:
1. **基本資訊** — Algorithm name, paper title, year, venue/source, and principal research institutions (university/company), all verified.
2. **創新貢獻** — 3–4 technical contributions when supported. Start each with a keyword and approximately 30 Chinese characters of description. Do not manufacture extra contributions to meet the count.
3. **演化目標** — Encoding/representation, number of objectives (single/multi), and objective/fitness functions.
4. **演化演算法流程** — First identify the actual framework (e.g. GA, GP, DE). For an EA, explain initialization, individual evaluation, parent selection, crossover, mutation, and environmental selection as applicable. Explicitly mark missing mechanisms; for non-EA papers describe their actual framework instead.
5. **大型語言模型之使用** — For every LLM role identify stage, input, and output. Cover context-engineering mechanisms, including how solutions or feedback are collected, filtered, and included.

Keep evidence traceable through compact references or accompanying source notes. Do not force the full technical-notes format into infographic copy.

## Infographic layout
When asked for the visual itself, use this geometry:
- Left 1/3: basic information above, contributions below.
- Right 2/3: optimization targets above, algorithm flow in the middle, LLM usage below.

Use an available visual/artifact workflow for actual rendering. An infographic-summary request alone calls for content, not automatic image generation. Preserve the requested layout and paper terminology.
