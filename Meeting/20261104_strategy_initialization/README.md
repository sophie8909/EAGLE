# Description-guided initialization presentation

Current output: `deliverables/EAGLE_1105_strategy_initialization_implemented.pptx`
(76 slides). The earlier `EAGLE_1105_with_strategy_initialization.pptx` remains
as the previous design-only revision.

Slides 66–67 now describe the implemented opt-in
`framework.initial_strategy_mode: llm_plus_authored`: one LLM-generated strategy
description plus the nine existing non-WorkerRush profiles. A separate Coach
stage uses each description to fill a complete genome. Historical 1030 results
and initialization remain unchanged. The executable config is
`configs/experiments/1104_description_guided/experiment.yaml`.

The source is the previous 74-slide genotype deck in
`../20261104_genotype/deliverables/`. Every original slide body is unchanged
except page-number text; all other 331 non-slide package parts outside the
presentation manifests are byte-identical. The final package retains 20 charts
and adds two editable tables. Package, geometry, fonts and import checks passed;
slides 65–68 rendered and both changed slides visually inspected. Native
PowerPoint application verification was not performed.

Code validation: 69 of 70 related regression checks passed; the one failure
loads an unchanged historical bundle with an existing Windows line-ending SHA
mismatch. The new config freezes the expected original bytes. One-generation
mock CLI search and resume passed, including descriptions, 24-slot genomes,
and inheritance. No real model request or real experiment was executed.

Rebuild: use bundled Node/Python runtimes, link build/node_modules to bundled
packages, and set RUNTIME_NODE_MODULES. Copy scripts/build.mjs and
scripts/render.mjs into build before executing them; execute
scripts/finalize.mjs and scripts/merge.py in between. The finalizer requires a
fresh output path.
