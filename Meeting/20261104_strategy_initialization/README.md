# Description-guided initialization design

Output: `deliverables/EAGLE_1105_with_strategy_initialization.pptx`, 76 slides.
Source: previous 74-slide genotype deck in `../20261104_genotype/deliverables/`.

Added slides 66–67 describe the user's requested next design: one LLM-generated strategy description plus the nine previously authored non-WorkerRush strategies, with each individual's description supplied to LLM slot selection. The original WorkerRush profile position is replaced by the new strategy. The design is explicitly prospective; historical 1030 results and their initialization remain unchanged.

This update changes presentation files only. It does not implement a new initialization protocol, generate a production strategy, modify experiment settings, or run experiments. Existing profiles were checked against `prompts/framework_initial_strategies.txt` entries 2–10. Descriptions guide slot choice but do not guarantee distinct genomes or behavior.

Validation: two added slides passed package, geometry, editable-table, font and import checks. Final 76-slide package integrity passed, retaining 20 charts. Original 74 slide bodies are equivalent excluding page-number text; other 331 non-slide parts outside presentation manifests are byte-identical. Slides 65–68 rendered; both added slides visually inspected. Native PowerPoint application verification was not performed.

Rebuild: use bundled Node/Python runtimes. Create build/node_modules linked to bundled packages and set RUNTIME_NODE_MODULES. Copy scripts/build.mjs and scripts/render.mjs into build before executing them; execute scripts/finalize.mjs and scripts/merge.py in between. Finalizer requires a fresh output path.
