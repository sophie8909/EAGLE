# Framework genotype presentation update

- Output: `deliverables/EAGLE_1105_with_genotype.pptx` (74 slides).
- Source: `../20261105_slot_ablation/build/combined.pptx` (69 slides; SHA-256 `84dcad0c6b2d9f891ae08042818f3ee288a51fd08453e7c632111539b564b120`). Source was already present and untracked before this task.
- Added slides 61–65: genotype boundary, six expression-choice genes, twelve numeric controls, six priority genes, and LLM selection/validation/materialization.
- Scope: exact 24-slot `gpt_finite_rule_market_v1` used by the 1030 ablation configs, not a universal count.
- Sources are recorded in slide notes. Numeric ranges and steps are read directly from the bundle.

## Validation

- Five new slides: package, geometry, font policy, editable tables and Artifact Tool import passed; no layout findings.
- Final 74-slide package integrity passed; original 20 charts retained, five editable tables added.
- Original 69 slide bodies are XML-equivalent excluding page-number text. All 316 other original non-slide package parts outside presentation manifests remain byte-identical.
- Final deck imported; slides 60–66 rendered. All five added slides visually inspected for artwork, text fit and numbering.
- No native PowerPoint application verification or new experiments.

## Rebuild

Use bundled presentation Node and Python runtimes. Link `build/node_modules` to bundled Node packages; set `RUNTIME_NODE_MODULES` accordingly. Run `scripts/build.mjs`, `scripts/finalize.mjs`, `scripts/merge.py`, then `scripts/render.mjs`. Finalizer requires a fresh `build/validated/genotype.pptx` output path.
